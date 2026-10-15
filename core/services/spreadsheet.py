"""A spreadsheet rendered as a PDF for the parser.

Agencies post amendments and pre-bid clarifications as workbooks (SECI's are one sheet of
clause, existing text, amended text). The pipeline reads PDF pages with character boxes,
so a workbook is rendered once, deterministically, into a text PDF: one block per row,
one line per cell ("B12: …"), wrapped, sheet by sheet, in document order. Nothing is
summarised or dropped except formatting; a cell's text is on the page as the cell holds
it, so an evidence quote resolves to it. The rendering is stored as the document; the
sha256 and the filename of the workbook as received are kept, so that the same file is
not stored twice and the freshness check matches it by content.
"""

# openpyxl and pymupdf ship no type information; their calls are the only untyped ones here.
# mypy: disable-error-code="no-untyped-call"

import io
import textwrap
from datetime import datetime

import openpyxl  # type: ignore[import-untyped]
import pymupdf
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]

ZIP_SIGNATURE = b"PK\x03\x04"
SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm")
PAGE_WIDTH, PAGE_HEIGHT = 842.0, 595.0  # A4 landscape, points
MARGIN = 36.0
FONT, FONT_SIZE, LEADING = "cour", 8.0, 10.5
WRAP = 150
# Formatted but empty rows run to the sheet's end (SECI's amendment claims a million);
# this many empty rows in a row end the sheet.
EMPTY_ROWS_END = 50
MAX_ROWS = 20_000


def is_spreadsheet(filename: str, data: bytes) -> bool:
    return filename.lower().endswith(SPREADSHEET_SUFFIXES) and data.startswith(ZIP_SIGNATURE)


def workbook_lines(data: bytes) -> list[str]:
    """The workbook as lines of text: a heading per sheet, a block per non-empty row."""
    lines: list[str] = []
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            lines.append(f"Sheet: {sheet.title}")
            lines.append("")
            empty = 0
            for number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                cells = [
                    (get_column_letter(index), _text(value))
                    for index, value in enumerate(row, start=1)
                    if value is not None and _text(value)
                ]
                if not cells:
                    empty += 1
                    if empty >= EMPTY_ROWS_END or number > MAX_ROWS:
                        break
                    continue
                empty = 0
                lines.append(f"Row {number}")
                for column, text in cells:
                    first, *rest = textwrap.wrap(text, WRAP) or [""]
                    lines.append(f"  {column}{number}: {first}")
                    lines.extend(f"      {part}" for part in rest)
                lines.append("")
    finally:
        workbook.close()
    return lines


def _text(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == value.min.time() else value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def render_pdf(data: bytes) -> bytes:
    """The workbook as a text PDF, the same bytes for the same workbook."""
    lines = workbook_lines(data)
    document = pymupdf.open()
    per_page = int((PAGE_HEIGHT - 2 * MARGIN) // LEADING)
    for start in range(0, max(len(lines), 1), per_page):
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        y = MARGIN + FONT_SIZE
        for line in lines[start : start + per_page]:
            page.insert_text((MARGIN, y), line, fontname=FONT, fontsize=FONT_SIZE)
            y += LEADING
    document.set_metadata(
        {
            "title": "",
            "author": "",
            "subject": "",
            "keywords": "",
            "creator": "tender-engine spreadsheet rendering",
            "producer": "tender-engine spreadsheet rendering",
            "creationDate": "",
            "modDate": "",
        }
    )
    rendered: bytes = document.tobytes(deflate=True, garbage=3, no_new_id=True)
    document.close()
    return rendered
