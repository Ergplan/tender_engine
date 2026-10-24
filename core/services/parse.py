"""ParseService: pdfplumber for text and character boxes, pymupdf for page renders; Docling
(Stage 7, Block 2) for the pages pdfplumber finds no text layer on, and for the table cells
of native pages with tables (the Block 2 benchmark: a cell whose text wraps is not
contiguous in pdfplumber's layout, Docling returns it whole), when the service is
configured and up. Each page records which layer produced it."""

import io
import logging
from typing import Any

import pdfplumber
import pymupdf
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.models import Document, Page
from core.parsing.docling import DoclingClient, DoclingUnavailable
from core.parsing.layers import LayerPage, TextItem
from core.services import jobs
from core.storage import Storage

log = logging.getLogger("parse")

# A page is scanned when it has fewer extractable characters than this and a raster image
# covers most of it: it has no usable text layer, so evidence cannot be located on it until
# an OCR layer reads it. A page with a few native characters and no image (a divider page
# saying "NOT USED", a part title) keeps its text layer, however short: a quote on it
# resolves. The model still sees the page image because extraction sends native PDF pages.
MIN_TEXT_CHARS = 50
IMAGE_COVERAGE_SCANNED = 0.5


class ParseService:
    def __init__(
        self, storage: Storage, settings: Settings, docling: DoclingClient | None = None
    ) -> None:
        self._storage = storage
        self._settings = settings
        self._docling = docling or (
            DoclingClient(settings.docling_url, timeout_seconds=settings.docling_timeout_seconds)
            if settings.docling_url
            else None
        )

    def parse(self, session: Session, document_id: str, *, map_sections: bool = True) -> Document:
        """Store one Page row and one render per page; mark the document parsed, and queue
        its section map (a model call) unless `map_sections` is false: an imported result
        publication (Stage 6) is read by no model and gets no map.

        Safe to re-run: existing pages of the document are replaced.
        """
        document = session.scalar(
            select(Document).where(
                Document.id == document_id, Document.tenant_id == self._settings.tenant_id
            )
        )
        if document is None:
            raise LookupError(f"document {document_id} not found")
        try:
            data = self._storage.get(document.storage_path)
            pages = self._read_pages(document, data)
            self._read_scanned_pages(document, data, pages)
            self._read_table_pages(document, data, pages)
        except Exception as exc:
            session.rollback()
            document.status = "failed"
            document.error = f"{type(exc).__name__}: {exc}"
            session.commit()
            raise
        session.execute(
            delete(Page).where(
                Page.document_id == document.id, Page.tenant_id == document.tenant_id
            )
        )
        session.add_all(pages)
        document.page_count = len(pages)
        document.status = "parsed"
        document.error = None
        if map_sections:
            jobs.enqueue(
                session,
                tenant_id=document.tenant_id,
                kind="section_map",
                payload={"document_id": document.id},
                created_by="worker",
            )
        session.commit()
        return document

    def _read_pages(self, document: Document, data: bytes) -> list[Page]:
        pages: list[Page] = []
        with (
            pdfplumber.open(io.BytesIO(data)) as text_pdf,
            pymupdf.open(stream=data, filetype="pdf") as render_pdf,  # type: ignore[no-untyped-call]
        ):
            if len(text_pdf.pages) != render_pdf.page_count:
                raise ValueError("the two PDF readers disagree on the page count")
            for index, text_page in enumerate(text_pdf.pages):
                page_no = index + 1
                text, boxes = _text_and_boxes(text_page)
                chars = sum(1 for c in text if not c.isspace())
                coverage = _image_coverage(text_page)
                tables = _table_count(text_page)
                pixmap = render_pdf[index].get_pixmap(dpi=self._settings.render_dpi)
                render_key = self._storage.put(
                    f"renders/{document.sha256}/{page_no}.png", pixmap.tobytes("png")
                )
                pages.append(
                    Page(
                        tenant_id=document.tenant_id,
                        created_by="worker",
                        document_id=document.id,
                        page_no=page_no,
                        text=text,
                        width=float(text_page.width),
                        height=float(text_page.height),
                        render_path=render_key,
                        char_boxes=boxes,
                        has_text_layer=has_text_layer(chars, coverage),
                        parser_layer="pdfplumber",
                        layer_detail={
                            "chars": chars,
                            "image_coverage": round(coverage, 3),
                            "tables": tables,
                        },
                    )
                )
                text_page.close()
        return pages

    def _read_scanned_pages(self, document: Document, data: bytes, pages: list[Page]) -> None:
        """Pages pdfplumber found no text layer on go to Docling, OCR forced, as one
        sub-PDF; a page it read gets Docling's text and boxes and `parser_layer = docling`.
        With no service configured, or the service down, the pages stay as they are (the
        layer's absence is recorded on each) and the parse does not fail."""
        scanned = [
            page
            for page in pages
            if not page.has_text_layer
            and (page.layer_detail or {}).get("image_coverage", 0.0) >= IMAGE_COVERAGE_SCANNED
        ]
        for page in pages:
            if not page.has_text_layer and page not in scanned:
                page.layer_detail = {**(page.layer_detail or {}), "docling": "blank page"}
        if not scanned:
            return
        if self._docling is None:
            for page in scanned:
                page.layer_detail = {**(page.layer_detail or {}), "docling": "not configured"}
            return
        sub_pdf = _sub_pdf(data, [page.page_no for page in scanned])
        try:
            result = self._docling.convert(
                sub_pdf, filename=f"{document.sha256[:12]}-scanned.pdf", force_ocr=True
            )
        except DoclingUnavailable as exc:
            log.warning("document %s: %s", document.id, exc)
            for page in scanned:
                page.layer_detail = {**(page.layer_detail or {}), "docling": f"unavailable: {exc}"}
            return
        for position, page in enumerate(scanned, start=1):
            read = result.pages.get(position)
            if read is None or not read.items:
                page.layer_detail = {**(page.layer_detail or {}), "docling": "no text found"}
                continue
            text, boxes = read.text_and_boxes()
            # Docling reports the page in its own units (PDF points for a PDF input); scale
            # to pdfplumber's page size when they differ.
            if (
                read.width
                and read.height
                and (abs(read.width - page.width) > 0.5 or abs(read.height - page.height) > 0.5)
            ):
                sx, sy = page.width / read.width, page.height / read.height
                boxes = [
                    None
                    if box is None
                    else [
                        round(box[0] * sx, 2),
                        round(box[1] * sy, 2),
                        round(box[2] * sx, 2),
                        round(box[3] * sy, 2),
                    ]
                    for box in boxes
                ]
            page.text = text
            page.char_boxes = boxes
            # What the OCR layer read is the page's text layer, however short.
            page.has_text_layer = any(not c.isspace() for c in text)
            page.parser_layer = "docling"
            page.layer_detail = {
                "ocr": True,
                "seconds_for_batch": result.seconds,
                "pages_in_batch": len(scanned),
                **read.detail,
            }

    def _read_table_pages(self, document: Document, data: bytes, pages: list[Page]) -> None:
        """Native pages with tables go to Docling (no forced OCR) as one sub-PDF; its table
        cells are appended to each page's text with their cell boxes, after pdfplumber's
        text, so a wrapped cell resolves as one piece and the rest of the page keeps its
        character-exact boxes. The page says `pdfplumber+docling`. Off without a service
        or with `docling_tables` false; an unavailable service leaves the pages as read."""
        if self._docling is None or not self._settings.docling_tables:
            return
        with_tables = [
            page
            for page in pages
            if page.has_text_layer
            and page.parser_layer == "pdfplumber"
            and (page.layer_detail or {}).get("tables", 0) > 0
        ]
        if not with_tables:
            return
        sub_pdf = _sub_pdf(data, [page.page_no for page in with_tables])
        try:
            result = self._docling.convert(
                sub_pdf, filename=f"{document.sha256[:12]}-tables.pdf", force_ocr=False
            )
        except DoclingUnavailable as exc:
            log.warning("document %s tables: %s", document.id, exc)
            for page in with_tables:
                page.layer_detail = {**(page.layer_detail or {}), "docling_tables": str(exc)}
            return
        for position, page in enumerate(with_tables, start=1):
            read = result.pages.get(position)
            cells = [item for item in (read.items if read else []) if item.kind == "table_cell"]
            if read is None or not cells:
                page.layer_detail = {**(page.layer_detail or {}), "docling_tables": "no cells"}
                continue
            sx = page.width / read.width if read.width else 1.0
            sy = page.height / read.height if read.height else 1.0
            scaled = [
                TextItem(
                    cell.text,
                    None
                    if cell.box is None
                    else [
                        round(cell.box[0] * sx, 2),
                        round(cell.box[1] * sy, 2),
                        round(cell.box[2] * sx, 2),
                        round(cell.box[3] * sy, 2),
                    ],
                    cell.kind,
                )
                for cell in cells
            ]
            extra_text, extra_boxes = LayerPage(
                page.page_no, page.width, page.height, scaled
            ).text_and_boxes()
            page.text = f"{page.text}\n{extra_text}"
            page.char_boxes = [*page.char_boxes, None, *extra_boxes]
            page.parser_layer = "pdfplumber+docling"
            page.layer_detail = {
                **(page.layer_detail or {}),
                "docling_tables": {
                    "cells": len(cells),
                    "seconds_for_batch": result.seconds,
                    "pages_in_batch": len(with_tables),
                },
            }


def _table_count(page: Any) -> int:
    """Tables pdfplumber finds on the page with at least two rows (ruled tables; a layout
    without rules is not counted, and pdfplumber reads those contiguously anyway)."""
    try:
        return sum(1 for table in page.find_tables() if len(table.rows) >= 2)
    except Exception:  # a page pdfplumber cannot analyse is a page without tables
        return 0


def _sub_pdf(data: bytes, page_numbers: list[int]) -> bytes:
    """A PDF of exactly the given 1-based pages, in order."""
    source: Any = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    out: Any = pymupdf.open()  # type: ignore[no-untyped-call]
    try:
        for page_no in page_numbers:
            out.insert_pdf(source, from_page=page_no - 1, to_page=page_no - 1)
        result: bytes = out.tobytes(deflate=True, garbage=0, no_new_id=True)
        return result
    finally:
        out.close()
        source.close()


def has_text_layer(chars: int, image_coverage: float) -> bool:
    """Native text counts as a text layer unless the page is a picture with at most a few
    stray characters (a scan with a printed header, an OCR'd stamp)."""
    if chars >= MIN_TEXT_CHARS:
        return True
    return chars > 0 and image_coverage < IMAGE_COVERAGE_SCANNED


def _image_coverage(page: Any) -> float:
    """The share of the page's area under raster images (overlaps counted once per image,
    so a page tiled by images can exceed 1; capped)."""
    area = float(page.width) * float(page.height)
    if area <= 0:
        return 0.0
    covered = 0.0
    for image in page.images or []:
        try:
            covered += max(0.0, float(image["x1"]) - float(image["x0"])) * max(
                0.0, float(image["bottom"]) - float(image["top"])
            )
        except (KeyError, TypeError, ValueError):
            continue
    return min(covered / area, 1.0)


def _text_and_boxes(page: Any) -> tuple[str, list[list[float] | None]]:
    """Page text plus one box per character, index-aligned with the text."""
    textmap = page.get_textmap()
    text = textmap.as_string.replace("\x00", " ")
    boxes: list[list[float] | None] = [
        None
        if char is None
        else [
            round(float(char["x0"]), 2),
            round(float(char["top"]), 2),
            round(float(char["x1"]), 2),
            round(float(char["bottom"]), 2),
        ]
        for _, char in textmap.tuples
    ]
    if len(boxes) != len(text):
        raise ValueError("text and character boxes are not aligned")
    return text, boxes
