"""What an upload may be, and how each kind becomes the PDF the parser reads.

The pipeline reads PDF pages with character boxes (core.services.parse). Every accepted
input is normalised to one PDF per document before it is stored:

- a PDF as it is; a PDF protected with an owner password or an empty user password is
  decrypted first (both readers must open it), a PDF that needs a password is refused;
- an .xlsx/.xlsm workbook, rendered to a text PDF (core.services.spreadsheet);
- a .docx, rendered to a text PDF the same way: paragraphs in order, tables row by row,
  one line per cell ("R3C2: ..."), so that every quote resolves to the text as the
  document holds it;
- a .zip bundle of a tender pack: each member that is one of the above is a document of
  its own; every other member is reported with the reason it was left out.

Anything else is refused with a reason a person can act on. Nothing here talks to the
database: `classify` says what the bytes are, `normalise` gives the PDF to store, and
`bundle_members` opens a zip.
"""

# python-docx and pymupdf ship no type information; their calls are the only untyped ones.
# mypy: disable-error-code="no-untyped-call"

import io
import textwrap
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

import pymupdf

from core.services.spreadsheet import SPREADSHEET_SUFFIXES, ZIP_SIGNATURE
from core.services.spreadsheet import render_pdf as render_spreadsheet_pdf

Kind = Literal["pdf", "spreadsheet", "docx", "zip"]

PDF_SIGNATURE = b"%PDF-"
# pymupdf's stubs omit the encryption constants.
ENCRYPT_NONE: int = pymupdf.PDF_ENCRYPT_NONE  # type: ignore[attr-defined]
DOCX_SUFFIXES = (".docx", ".docm")
ZIP_SUFFIXES = (".zip",)
MAX_BUNDLE_MEMBERS = 200
MAX_MEMBER_BYTES = 200 * 1024 * 1024
# The whole bundle unpacked: the sizes its members declare, checked before any is read, so
# a small archive cannot expand past the machine's memory.
MAX_BUNDLE_BYTES = 600 * 1024 * 1024
PAGE_WIDTH, PAGE_HEIGHT = 595.0, 842.0  # A4 portrait, points
MARGIN = 40.0
FONT, FONT_SIZE, LEADING = "cour", 9.0, 12.0
WRAP = 95

# Reasons, by what the file looked like, written for the person who uploaded it.
REASONS = {
    "legacy_word": "a legacy .doc file is not supported: save it as .docx or PDF and upload that",
    "legacy_excel": "a legacy .xls file is not supported: save it as .xlsx or PDF and upload that",
    "image": "an image file is not supported on its own: upload the PDF it belongs to",
    "html": "a web page is not a tender document: upload the PDF or workbook it links to",
    "password": "the PDF needs a password to open: upload a copy saved without the password",
    "empty": "the file is empty",
    "unknown": "the file is not a PDF, a .docx, an .xlsx workbook or a .zip of those",
}


class InputError(ValueError):
    """The upload cannot become a document; the message says why and what to do."""


@dataclass(frozen=True)
class Member:
    """One member of a bundle that is a document of its own."""

    name: str
    data: bytes


@dataclass(frozen=True)
class Rejected:
    name: str
    reason: str


def classify(filename: str, data: bytes) -> Kind:
    """What the bytes are, by signature first and suffix second; refuses with a reason."""
    name = filename.lower()
    if not data:
        raise InputError(REASONS["empty"])
    if data.startswith(PDF_SIGNATURE):
        return "pdf"
    if data.startswith(ZIP_SIGNATURE):
        if name.endswith(SPREADSHEET_SUFFIXES):
            return "spreadsheet"
        if name.endswith(DOCX_SUFFIXES):
            return "docx"
        if name.endswith(ZIP_SUFFIXES):
            return "zip"
        # An Office file under another name: look inside.
        inner = _zip_names(data)
        if any(n.startswith("xl/") for n in inner):
            return "spreadsheet"
        if any(n.startswith("word/") for n in inner):
            return "docx"
        return "zip"
    if data.startswith(b"\xd0\xcf\x11\xe0"):  # OLE2: .doc / .xls
        raise InputError(REASONS["legacy_excel" if name.endswith(".xls") else "legacy_word"])
    if data[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"GIF8") or data[:2] in (
        b"\xff\xd8",
        b"BM",
    ):
        raise InputError(REASONS["image"])
    head = data[:512].lstrip().lower()
    if head.startswith((b"<!doctype html", b"<html")):
        raise InputError(REASONS["html"])
    raise InputError(REASONS["unknown"])


def normalise(filename: str, data: bytes) -> tuple[Kind, bytes]:
    """The kind of the upload and the PDF bytes to store for it."""
    kind = classify(filename, data)
    if kind == "pdf":
        return kind, _open_pdf(data)
    if kind == "spreadsheet":
        return kind, render_spreadsheet_pdf(data)
    if kind == "docx":
        return kind, render_docx_pdf(data)
    raise InputError("a .zip bundle is opened member by member (bundle_members)")


def _open_pdf(data: bytes) -> bytes:
    """The PDF as both readers can open it: a protected PDF with an empty user password
    (an owner password only) is saved without encryption; one that needs a password is
    refused."""
    try:
        document: Any = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise InputError(f"the PDF cannot be opened: {exc}") from exc
    try:
        if document.needs_pass and not document.authenticate(""):
            raise InputError(REASONS["password"])
        # pymupdf opens an owner-only protected file with the empty user password by
        # itself; the encryption dictionary is still there, and pdfplumber refuses some
        # such files, so a plain copy is saved. The permission flags would stop nothing the
        # parser does anyway.
        if document.metadata.get("encryption"):
            plain: bytes = document.tobytes(encryption=ENCRYPT_NONE, garbage=0)
            return plain
        return data
    finally:
        document.close()


def _zip_names(data: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.namelist()
    except zipfile.BadZipFile:
        return []


def bundle_members(data: bytes) -> tuple[list[Member], list[Rejected]]:
    """The members of a zip that are documents (PDF, workbook, .docx, each in the form
    `normalise` accepts), and the members left out with their reasons. Directories,
    hidden files and nested zips are left out; a nested zip is reported as such."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InputError(f"the .zip cannot be opened: {exc}") from exc
    members: list[Member] = []
    rejected: list[Rejected] = []
    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > MAX_BUNDLE_MEMBERS:
            raise InputError(f"the bundle has {len(infos)} files; at most {MAX_BUNDLE_MEMBERS}")
        declared = sum(i.file_size for i in infos if i.file_size <= MAX_MEMBER_BYTES)
        if declared > MAX_BUNDLE_BYTES:
            raise InputError(
                f"the bundle unpacks to {declared // (1024 * 1024)} MB; at most "
                f"{MAX_BUNDLE_BYTES // (1024 * 1024)} MB"
            )
        for info in infos:
            base = info.filename.rsplit("/", 1)[-1]
            if base.startswith((".", "~$")) or "__MACOSX/" in info.filename:
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                rejected.append(Rejected(info.filename, "larger than 200 MB"))
                continue
            try:
                content = archive.read(info)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
                # A damaged, encrypted or mis-sized member (its size header lying).
                rejected.append(Rejected(info.filename, f"could not be unpacked: {exc}"))
                continue
            try:
                kind = classify(base, content)
            except InputError as exc:
                rejected.append(Rejected(info.filename, str(exc)))
                continue
            if kind == "zip":
                rejected.append(
                    Rejected(info.filename, "a zip inside the bundle: upload it on its own")
                )
                continue
            members.append(Member(info.filename, content))
    return members, rejected


def docx_lines(data: bytes) -> list[str]:
    """The document as lines: paragraphs in body order, each table as its rows, one line
    per cell with its row and column ("R2C3: ..."), headers and footers left out."""
    import docx
    from docx.document import Document as DocxDocument
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document: DocxDocument = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise InputError(f"the .docx cannot be opened: {exc}") from exc
    lines: list[str] = []
    table_no = 0
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = " ".join(Paragraph(child, document).text.split())
            if text:
                lines.extend(textwrap.wrap(text, WRAP) or [""])
                lines.append("")
        elif child.tag == qn("w:tbl"):
            table_no += 1
            lines.append(f"Table {table_no}")
            for r, row in enumerate(Table(child, document).rows, start=1):
                seen: set[int] = set()
                for c, cell in enumerate(row.cells, start=1):
                    if id(cell._tc) in seen:  # a merged cell repeats across its span
                        continue
                    seen.add(id(cell._tc))
                    text = " ".join(cell.text.split())
                    if not text:
                        continue
                    first, *rest = textwrap.wrap(text, WRAP - 8) or [""]
                    lines.append(f"  R{r}C{c}: {first}")
                    lines.extend(f"        {part}" for part in rest)
            lines.append("")
    return lines


def render_docx_pdf(data: bytes) -> bytes:
    """The .docx as a text PDF, the same bytes for the same file."""
    lines = docx_lines(data)
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
            "creator": "tender-engine docx rendering",
            "producer": "tender-engine docx rendering",
            "creationDate": "",
            "modDate": "",
        }
    )
    rendered: bytes = document.tobytes(deflate=True, garbage=3, no_new_id=True)
    document.close()
    return rendered
