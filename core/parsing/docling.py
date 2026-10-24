"""Docling as a parsing layer: docling-serve on the VM, reached over HTTP.

The worker sends the pages it wants read (a sub-PDF of exactly those pages, so nothing
more leaves the worker than needs to) to `POST /v1/convert/source` and maps the
DoclingDocument that comes back to LayerPages: every text item and every table cell with
its page box, converted from Docling's bottom-left origin to the top-left origin pdfplumber
uses. OCR is forced for pages without a text layer (`force_ocr`), and left to Docling's own
judgement otherwise.

The client raises DoclingUnavailable when the service cannot be reached or answers with an
error; the caller decides what a page without the layer keeps.
"""

import base64
import time
from dataclasses import dataclass
from typing import Any

import httpx

from core.parsing.layers import Box, LayerPage, TextItem

CONVERT_PATH = "/v1/convert/source"
HEALTH_PATH = "/health"


class DoclingUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class DoclingResult:
    pages: dict[int, LayerPage]  # by the position in the PDF sent (1-based)
    seconds: float
    detail: dict[str, Any]


class DoclingClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 900.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def healthy(self) -> bool:
        try:
            response = httpx.get(self._base_url + HEALTH_PATH, timeout=10.0)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def convert(
        self, pdf: bytes, *, filename: str = "pages.pdf", force_ocr: bool = False
    ) -> DoclingResult:
        """Read every page of `pdf`. The result's pages are numbered by their position in
        `pdf`, not in the document they came from."""
        body = {
            "options": {
                "to_formats": ["json"],
                "image_export_mode": "placeholder",
                "do_ocr": True,
                "force_ocr": force_ocr,
                "do_table_structure": True,
                "table_mode": "accurate",
                "include_images": False,
            },
            "sources": [
                {
                    "kind": "file",
                    "base64_string": base64.standard_b64encode(pdf).decode("ascii"),
                    "filename": filename,
                }
            ],
        }
        started = time.monotonic()
        try:
            response = httpx.post(self._base_url + CONVERT_PATH, json=body, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise DoclingUnavailable(f"docling: {type(exc).__name__}: {exc}") from exc
        if response.status_code != 200:
            raise DoclingUnavailable(f"docling: HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
        document = (payload.get("document") or {}).get("json_content")
        if not isinstance(document, dict):
            raise DoclingUnavailable("docling: the answer carries no json_content")
        seconds = time.monotonic() - started
        pages = pages_from_document(document)
        detail = {
            "status": payload.get("status"),
            "processing_time": payload.get("processing_time"),
            "errors": payload.get("errors") or [],
        }
        return DoclingResult(pages=pages, seconds=round(seconds, 2), detail=detail)


def pages_from_document(document: dict[str, Any]) -> dict[int, LayerPage]:
    """LayerPages from a DoclingDocument (its JSON form): texts and table cells in the
    document's reading order, each on the page its provenance names."""
    sizes: dict[int, tuple[float, float]] = {}
    for key, page in (document.get("pages") or {}).items():
        size = page.get("size") or {}
        page_no = int(page.get("page_no") or key)
        sizes[page_no] = (float(size.get("width") or 0.0), float(size.get("height") or 0.0))
    items: dict[int, list[TextItem]] = {page_no: [] for page_no in sizes}
    counts: dict[int, dict[str, int]] = {page_no: {} for page_no in sizes}

    def add(page_no: int, item: TextItem) -> None:
        items.setdefault(page_no, []).append(item)
        bucket = counts.setdefault(page_no, {})
        bucket[item.kind] = bucket.get(item.kind, 0) + 1

    # Reading order: Docling's body lists children as refs; items are resolved by ref.
    by_ref: dict[str, dict[str, Any]] = {}
    for collection in ("texts", "tables", "pictures", "groups"):
        for entry in document.get(collection) or []:
            if isinstance(entry, dict) and entry.get("self_ref"):
                by_ref[entry["self_ref"]] = entry

    def walk(node: dict[str, Any]) -> None:
        for child in node.get("children") or []:
            ref = str(child.get("$ref") or "") if isinstance(child, dict) else ""
            target = by_ref.get(ref)
            if target is None:
                continue
            if ref.startswith("#/texts/"):
                _add_text(target, add, sizes)
            elif ref.startswith("#/tables/"):
                _add_table(target, add, sizes)
            walk(target)

    body = document.get("body") or {}
    if body.get("children"):
        walk(body)
    else:  # no body tree: take the collections in order
        for entry in document.get("texts") or []:
            _add_text(entry, add, sizes)
        for entry in document.get("tables") or []:
            _add_table(entry, add, sizes)
    return {
        page_no: LayerPage(
            page_no=page_no,
            width=sizes.get(page_no, (0.0, 0.0))[0],
            height=sizes.get(page_no, (0.0, 0.0))[1],
            items=page_items,
            detail={"items": counts.get(page_no, {})},
        )
        for page_no, page_items in sorted(items.items())
    }


def _add_text(entry: dict[str, Any], add: Any, sizes: dict[int, tuple[float, float]]) -> None:
    text = " ".join(str(entry.get("text") or "").split())
    if not text:
        return
    for prov in entry.get("prov") or [{}]:
        page_no = int(prov.get("page_no") or 1)
        add(
            page_no,
            TextItem(
                text, _box(prov.get("bbox"), sizes.get(page_no)), str(entry.get("label") or "text")
            ),
        )
        break  # one placement per item: the first page it is on


def _add_table(entry: dict[str, Any], add: Any, sizes: dict[int, tuple[float, float]]) -> None:
    prov = (entry.get("prov") or [{}])[0]
    table_page = int(prov.get("page_no") or 1)
    cells = (entry.get("data") or {}).get("table_cells") or (entry.get("data") or {}).get("grid")
    if not cells:
        return
    flat: list[dict[str, Any]] = []
    for cell in cells:
        if isinstance(cell, list):  # grid: rows of cells
            flat.extend(c for c in cell if isinstance(c, dict))
        elif isinstance(cell, dict):
            flat.append(cell)
    seen: set[tuple[int, int]] = set()
    for cell in sorted(
        flat,
        key=lambda c: (
            int(c.get("start_row_offset_idx") or 0),
            int(c.get("start_col_offset_idx") or 0),
        ),
    ):
        key = (
            int(cell.get("start_row_offset_idx") or 0),
            int(cell.get("start_col_offset_idx") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        text = " ".join(str(cell.get("text") or "").split())
        if not text:
            continue
        add(table_page, TextItem(text, _box(cell.get("bbox"), sizes.get(table_page)), "table_cell"))


def _box(bbox: dict[str, Any] | None, size: tuple[float, float] | None) -> Box | None:
    """Docling's {l, t, r, b, coord_origin} as [x0, top, x1, bottom] from the top-left."""
    if not bbox:
        return None
    try:
        left, top, right, bottom = (float(bbox[k]) for k in ("l", "t", "r", "b"))
    except (KeyError, TypeError, ValueError):
        return None
    if str(bbox.get("coord_origin", "")).upper() == "BOTTOMLEFT" and size and size[1]:
        height = size[1]
        top, bottom = height - top, height - bottom
    if bottom < top:
        top, bottom = bottom, top
    return [round(left, 2), round(top, 2), round(right, 2), round(bottom, 2)]
