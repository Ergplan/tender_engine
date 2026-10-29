"""Every input kind of Block 2: what is accepted, how it becomes a PDF, and why the rest
is refused."""

# pymupdf and python-docx ship no type information.
# mypy: disable-error-code="no-untyped-call"

import io
import zipfile

import pymupdf
import pytest

from core.services import inputs
from core.services.inputs import InputError, bundle_members, classify, docx_lines, normalise
from tests.fixtures.pdfs import make_pdf


def docx_bytes(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    import docx

    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table:
        t = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, text in enumerate(row):
                t.cell(r, c).text = text
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def workbook_bytes() -> bytes:
    import openpyxl

    book = openpyxl.Workbook()
    book.active.append(["Clause", "Existing", "Amended"])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def zip_bytes(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return out.getvalue()


def protected_pdf(user_password: str) -> bytes:
    document = pymupdf.open(stream=make_pdf(), filetype="pdf")
    data: bytes = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-secret", user_pw=user_password
    )
    document.close()
    return data


def page_texts(pdf: bytes) -> list[str]:
    document = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        return [page.get_text() for page in document]
    finally:
        document.close()


def test_classification_goes_by_signature_then_suffix() -> None:
    assert classify("a.pdf", make_pdf()) == "pdf"
    assert classify("renamed.bin", make_pdf()) == "pdf", "a PDF under any name"
    assert classify("Amendment.xlsx", workbook_bytes()) == "spreadsheet"
    assert classify("RfS.docx", docx_bytes(["x"])) == "docx"
    assert classify("pack.zip", zip_bytes({"a.pdf": make_pdf()})) == "zip"
    # Office files under the wrong suffix are told apart by what is inside the zip.
    assert classify("mystery.dat", workbook_bytes()) == "spreadsheet"
    assert classify("mystery.dat", docx_bytes(["x"])) == "docx"


@pytest.mark.parametrize(
    ("filename", "data", "fragment"),
    [
        ("old.doc", b"\xd0\xcf\x11\xe0" + b"\0" * 64, "legacy .doc"),
        ("old.xls", b"\xd0\xcf\x11\xe0" + b"\0" * 64, "legacy .xls"),
        ("scan.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 32, "image file"),
        ("scan.jpg", b"\xff\xd8\xff\xe0" + b"\0" * 32, "image file"),
        ("page.html", b"<!DOCTYPE html><html><body>tender</body></html>", "web page"),
        ("notes.txt", b"hello", "not a PDF, a .docx"),
        ("empty.pdf", b"", "empty"),
    ],
)
def test_everything_else_is_refused_with_a_reason(
    filename: str, data: bytes, fragment: str
) -> None:
    with pytest.raises(InputError, match=fragment):
        classify(filename, data)


def test_a_docx_becomes_a_text_pdf_with_its_tables_cell_by_cell() -> None:
    data = docx_bytes(
        ["REQUEST FOR SELECTION", "The bid submission deadline is 30 March 2026 at 15:00 hrs."],
        [["Clause", "Existing provision", "Amended provision"], ["4.1", "25 years", "20 years"]],
    )
    lines = docx_lines(data)
    assert lines[0] == "REQUEST FOR SELECTION"
    assert "The bid submission deadline is 30 March 2026 at 15:00 hrs." in lines
    assert "Table 1" in lines and "  R2C1: 4.1" in lines and "  R2C3: 20 years" in lines
    kind, pdf = normalise("rfs.docx", data)
    assert kind == "docx" and pdf.startswith(b"%PDF-")
    text = "\n".join(page_texts(pdf))
    assert "bid submission deadline is 30 March 2026" in text and "R2C3: 20 years" in text
    assert normalise("rfs.docx", data)[1] == pdf, "the same bytes every time"


def test_a_workbook_still_renders_through_the_spreadsheet_path() -> None:
    kind, pdf = normalise("Amendment1.xlsx", workbook_bytes())
    assert kind == "spreadsheet" and "A1: Clause" in page_texts(pdf)[0]


def test_a_native_pdf_is_stored_as_received() -> None:
    data = make_pdf()
    assert normalise("a.pdf", data) == ("pdf", data)


def test_an_owner_protected_pdf_is_saved_plain_and_one_needing_a_password_is_refused() -> None:
    owner_only = protected_pdf(user_password="")
    assert pymupdf.open(stream=owner_only, filetype="pdf").metadata["encryption"]
    kind, plain = normalise("protected.pdf", owner_only)
    assert kind == "pdf" and plain != owner_only
    opened = pymupdf.open(stream=plain, filetype="pdf")
    assert not opened.metadata["encryption"]
    assert "MASTER SUPPLY AGREEMENT" in opened[0].get_text()
    with pytest.raises(InputError, match="needs a password"):
        normalise("locked.pdf", protected_pdf(user_password="s3cret"))


def test_a_bundle_yields_its_documents_and_names_what_it_left_out() -> None:
    bundle = zip_bytes(
        {
            "pack/RfS.pdf": make_pdf(),
            "pack/Amendment-1.xlsx": workbook_bytes(),
            "pack/PPA.docx": docx_bytes(["POWER PURCHASE AGREEMENT"]),
            "pack/old-format.doc": b"\xd0\xcf\x11\xe0" + b"\0" * 64,
            "pack/scan.jpg": b"\xff\xd8\xff\xe0" + b"\0" * 32,
            "pack/inner.zip": zip_bytes({"x.pdf": make_pdf()}),
            "pack/.DS_Store": b"junk",
            "__MACOSX/pack/._RfS.pdf": b"junk",
        }
    )
    members, rejected = bundle_members(bundle)
    assert [m.name for m in members] == ["pack/RfS.pdf", "pack/Amendment-1.xlsx", "pack/PPA.docx"]
    assert {r.name: r.reason for r in rejected} == {
        "pack/old-format.doc": inputs.REASONS["legacy_word"],
        "pack/scan.jpg": inputs.REASONS["image"],
        "pack/inner.zip": "a zip inside the bundle: upload it on its own",
    }
    for member in members:
        normalise(member.name, member.data)  # every member is storable
    with pytest.raises(InputError, match="opened member by member"):
        normalise("pack.zip", bundle)
    with pytest.raises(InputError, match="cannot be opened"):
        bundle_members(b"PK\x03\x04not really a zip")


def test_a_bundle_that_unpacks_past_the_cap_is_refused_before_any_member_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = zip_bytes({"a.pdf": make_pdf(), "b.pdf": make_pdf()})
    one = len(make_pdf())
    monkeypatch.setattr(inputs, "MAX_BUNDLE_BYTES", one + 10)
    with pytest.raises(InputError, match="unpacks to"):
        bundle_members(bundle)


def test_a_member_whose_size_header_lies_is_named_not_raised() -> None:
    bundle = bytearray(zip_bytes({"RfS.pdf": make_pdf(), "liar.pdf": make_pdf() + b"%% other"}))
    # Corrupt the stored CRC of the second member in the central directory and the local
    # header, so reading it fails the integrity check.
    with zipfile.ZipFile(io.BytesIO(bytes(bundle))) as archive:
        info = archive.getinfo("liar.pdf")
    crc = info.CRC.to_bytes(4, "little")
    bad = (info.CRC ^ 0xFFFFFFFF).to_bytes(4, "little")
    data = bytes(bundle).replace(crc, bad)
    members, rejected = bundle_members(data)
    assert [m.name for m in members] == ["RfS.pdf"]
    assert [r.name for r in rejected] == ["liar.pdf"]
    assert rejected[0].reason.startswith("could not be unpacked")
