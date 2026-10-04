"""ParseService: pdfplumber for text and character boxes, pymupdf for page renders."""

import io
from typing import Any

import pdfplumber
import pymupdf
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.models import Document, Page
from core.services import jobs
from core.storage import Storage

# A page with fewer extractable characters than this is treated as scanned: it has no
# usable text layer, so evidence cannot be located on it. The model still sees the page
# image because extraction sends native PDF pages.
MIN_TEXT_CHARS = 50


class ParseService:
    def __init__(self, storage: Storage, settings: Settings) -> None:
        self._storage = storage
        self._settings = settings

    def parse(self, session: Session, document_id: str) -> Document:
        """Store one Page row and one render per page; mark the document parsed.

        Safe to re-run: existing pages of the document are replaced.
        """
        document = session.scalar(
            select(Document).where(
                Document.id == document_id, Document.tenant_id == self._settings.tenant_id
            )
        )
        if document is None:
            raise LookupError(f"document {document_id} not found")
        data = self._storage.get(document.storage_path)
        try:
            pages = self._read_pages(document, data)
        except Exception as exc:
            session.rollback()
            document.status = "failed"
            document.error = f"{type(exc).__name__}: {exc}"
            session.commit()
            raise
        session.execute(delete(Page).where(Page.document_id == document.id))
        session.add_all(pages)
        document.page_count = len(pages)
        document.status = "parsed"
        document.error = None
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
                        has_text_layer=sum(1 for c in text if not c.isspace()) >= MIN_TEXT_CHARS,
                    )
                )
                text_page.close()
        return pages


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
