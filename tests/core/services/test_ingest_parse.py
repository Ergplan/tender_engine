from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Document, Job, Page
from core.services.ingest import IngestError
from core.services.parse import ParseService
from tests.conftest import Pipeline
from tests.fixtures.pdfs import PAGE_2, make_pdf


def test_upload_stores_the_file_creates_a_document_and_enqueues_parse(
    pipeline: Pipeline, db: Session
) -> None:
    data = make_pdf()
    document = pipeline.upload(db, data)
    assert document.status == "uploaded" and document.tenant_id == "ergplan"
    assert document.created_by == "pytest" and document.mime == "application/pdf"
    assert len(document.sha256) == 64
    assert pipeline.storage.get(document.storage_path) == data
    [job] = db.scalars(select(Job))
    assert (job.kind, job.payload, job.status) == ("parse", {"document_id": document.id}, "queued")


def test_the_same_file_uploaded_twice_is_one_document_and_one_job(
    pipeline: Pipeline, db: Session
) -> None:
    data = make_pdf()
    first, created_first = pipeline.ingest.upload(db, filename="a.pdf", data=data, created_by="x")
    second, created_second = pipeline.ingest.upload(db, filename="b.pdf", data=data, created_by="y")
    assert (created_first, created_second) == (True, False)
    assert first.id == second.id and second.filename == "a.pdf"
    assert db.scalar(select(func.count()).select_from(Document)) == 1
    assert db.scalar(select(func.count()).select_from(Job)) == 1


def test_provenance_is_stored_and_a_later_upload_fills_only_what_is_missing(
    pipeline: Pipeline, db: Session
) -> None:
    data = make_pdf()
    first, _ = pipeline.ingest.upload(
        db,
        filename="a.pdf",
        data=data,
        created_by="x",
        source_url="https://www.seci.co.in/tender-details/Ymd_",
    )
    assert first.source_url == "https://www.seci.co.in/tender-details/Ymd_"
    assert first.retrieved_on is None
    again, created = pipeline.ingest.upload(
        db,
        filename="a.pdf",
        data=data,
        created_by="y",
        source_url="https://elsewhere.example/a.pdf",
        retrieved_on=date(2026, 10, 4),
    )
    assert created is False and again.id == first.id
    assert again.source_url == "https://www.seci.co.in/tender-details/Ymd_", "never overwritten"
    assert again.retrieved_on == date(2026, 10, 4), "filled where it was blank"
    db.expire_all()
    assert db.get(Document, first.id).retrieved_on == date(2026, 10, 4), "committed"


def test_a_file_that_is_not_a_pdf_is_refused(pipeline: Pipeline, db: Session) -> None:
    with pytest.raises(IngestError, match="not a PDF"):
        pipeline.ingest.upload(db, filename="a.txt", data=b"hello", created_by="x")
    with pytest.raises(IngestError, match="not a PDF"):
        pipeline.ingest.upload(db, filename="a.xlsx", data=b"PK\x03\x04junk"[:3], created_by="x")
    assert db.scalar(select(func.count()).select_from(Document)) == 0


def workbook(rows: list[list[object]], sheet: str = "Amendment1") -> bytes:
    import io

    import openpyxl

    book = openpyxl.Workbook()
    page = book.active
    page.title = sheet
    for row in rows:
        page.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_a_spreadsheet_is_stored_as_a_text_pdf_under_its_own_hash_and_parses(
    pipeline: Pipeline, db: Session
) -> None:
    """SECI posts amendments as workbooks: one sheet of clause, existing text, amended text.
    The workbook is rendered to a text PDF for the parser; its own sha256 and filename
    are kept, so the same workbook is one document and the freshness check matches it."""
    import hashlib

    from core.services.spreadsheet import render_pdf, workbook_lines

    rows: list[list[object]] = [
        ["SOLAR ENERGY CORPORATION OF INDIA LIMITED"],
        ["No. SECI/C&P/OP/11/0002/26-27/Amendment-01", None, "Date: 28/07/2026"],
        ["S. No.", "Clause No.", "Existing Clause", "Amended Clause"],
        [1, "9(xi)", "15 days prior to the proposed date of trial run", "7 working days prior"],
        [None, None, None, None],
        [2, 21.2, "valid for 12 years", "valid for 15 years"],
    ]
    data = workbook(rows)
    lines = workbook_lines(data)
    assert lines[:2] == ["Sheet: Amendment1", ""]
    assert "  C2: Date: 28/07/2026" in lines and "  D4: 7 working days prior" in lines
    assert "  B6: 21.2" in lines, "a number is written as the cell shows it"
    assert render_pdf(data) == render_pdf(data), "the same workbook renders to the same bytes"

    document, created = pipeline.ingest.upload(
        db, filename="Amendment-1_2.xlsx", data=data, created_by="x"
    )
    assert created and document.filename == "Amendment-1_2.xlsx"
    assert document.sha256 == hashlib.sha256(data).hexdigest(), "the workbook's own hash"
    stored = pipeline.storage.get(document.storage_path)
    assert stored.startswith(b"%PDF-"), "what is stored is a PDF"
    assert document.mime.endswith("spreadsheetml.sheet"), "what was uploaded is remembered"
    again, created_again = pipeline.ingest.upload(
        db, filename="copy.xlsx", data=data, created_by="y"
    )
    assert not created_again and again.id == document.id
    ParseService(pipeline.storage, pipeline.settings).parse(db, document.id)
    db.expire_all()
    assert db.get(Document, document.id).status == "parsed"
    text = "\n".join(db.scalars(select(Page.text).where(Page.document_id == document.id)))
    assert "D4: 7 working days prior" in text and "Date: 28/07/2026" in text


def test_parse_stores_text_aligned_boxes_and_a_render_per_page(
    pipeline: Pipeline, db: Session
) -> None:
    document = pipeline.upload(db)
    ParseService(pipeline.storage, pipeline.settings).parse(db, document.id)
    db.refresh(document)
    assert (document.status, document.page_count) == ("parsed", 3)
    pages = list(db.scalars(select(Page).order_by(Page.page_no)))
    assert [page.page_no for page in pages] == [1, 2, 3]
    second = pages[1]
    assert all(line in second.text for line in PAGE_2)
    assert (second.width, second.height) == (595.0, 842.0)
    assert second.has_text_layer is True
    assert second.tenant_id == "ergplan" and second.created_by == "worker"
    assert len(second.char_boxes) == len(second.text)
    index = second.text.index("12.03.2026")
    box = second.char_boxes[index]
    assert box is not None and 72 < box[0] < 595 and 0 < box[1] < box[3] < 842 and box[0] < box[2]
    assert second.char_boxes[second.text.index("\n")] is None
    png = pipeline.storage.get(second.render_path)
    assert png.startswith(b"\x89PNG") and second.render_path.endswith("/2.png")
    kinds = [job.kind for job in db.scalars(select(Job).order_by(Job.created_at))]
    assert kinds == ["parse", "section_map"]


def test_render_resolution_follows_the_setting(pipeline: Pipeline, db: Session) -> None:
    import pymupdf

    document = pipeline.upload(db)
    ParseService(pipeline.storage, pipeline.settings).parse(db, document.id)
    render = db.scalar(select(Page.render_path).where(Page.page_no == 1))
    assert render is not None
    pixmap = pymupdf.Pixmap(pipeline.storage.get(render))
    assert pipeline.settings.render_dpi == 150
    assert abs(pixmap.width - 595 * 150 / 72) <= 1


def test_a_scanned_page_is_flagged_as_having_no_text_layer(pipeline: Pipeline, db: Session) -> None:
    document = pipeline.upload(db, make_pdf(scanned_last_page=True))
    ParseService(pipeline.storage, pipeline.settings).parse(db, document.id)
    pages = list(db.scalars(select(Page).order_by(Page.page_no)))
    assert [page.has_text_layer for page in pages] == [True, True, True, False]
    assert pipeline.storage.get(pages[3].render_path).startswith(b"\x89PNG")


def test_parsing_again_replaces_the_pages(pipeline: Pipeline, db: Session) -> None:
    document = pipeline.upload(db)
    service = ParseService(pipeline.storage, pipeline.settings)
    service.parse(db, document.id)
    service.parse(db, document.id)
    assert db.scalar(select(func.count()).select_from(Page)) == 3


def test_an_unreadable_pdf_is_refused_at_upload_and_a_corrupt_stored_file_fails_the_parse(
    pipeline: Pipeline, db: Session
) -> None:
    with pytest.raises(IngestError, match="cannot be opened"):
        pipeline.upload(db, b"%PDF-1.7\nthis is not really a pdf")
    document = pipeline.upload(db)
    pipeline.storage.put(document.storage_path, b"%PDF-1.7\nthis is not really a pdf")
    with pytest.raises(Exception):  # noqa: B017 - the reader's own error type
        ParseService(pipeline.storage, pipeline.settings).parse(db, document.id)
    db.refresh(document)
    assert document.status == "failed" and document.error
    assert db.scalar(select(func.count()).select_from(Page)) == 0


def test_parse_of_an_unknown_document_is_a_lookup_error(pipeline: Pipeline, db: Session) -> None:
    with pytest.raises(LookupError):
        ParseService(pipeline.storage, pipeline.settings).parse(db, "0" * 32)


class FakeDocling:
    """Stands in for docling-serve: reads the sub-PDF it is sent and answers with one text
    item per page, placed where the page's words are."""

    def __init__(self, text: str = "This page is an image and has no text layer.") -> None:
        self.text = text
        self.calls: list[dict[str, object]] = []
        self.fail = False

    def convert(self, pdf: bytes, *, filename: str = "pages.pdf", force_ocr: bool = False):  # type: ignore[no-untyped-def]
        from core.parsing.docling import DoclingResult, DoclingUnavailable
        from core.parsing.layers import LayerPage, TextItem

        self.calls.append({"filename": filename, "force_ocr": force_ocr, "bytes": len(pdf)})
        if self.fail:
            raise DoclingUnavailable("docling: ConnectError: refused")
        import pymupdf

        count = pymupdf.open(stream=pdf, filetype="pdf").page_count
        return DoclingResult(
            pages={
                n: LayerPage(
                    page_no=n,
                    width=595.0,
                    height=842.0,
                    items=[TextItem(self.text, [72.0, 90.0, 400.0, 104.0], "text")],
                    detail={"items": {"text": 1}},
                )
                for n in range(1, count + 1)
            },
            seconds=1.5,
            detail={"status": "success"},
        )


def test_a_scanned_page_is_read_by_docling_and_says_so(pipeline: Pipeline, db: Session) -> None:
    from core.evidence.resolver import PageText, resolve

    docling = FakeDocling()
    service = ParseService(pipeline.storage, pipeline.settings, docling=docling)
    document = pipeline.upload(db, make_pdf(scanned_last_page=True))
    service.parse(db, document.id, map_sections=False)
    pages = db.scalars(
        select(Page).where(Page.document_id == document.id).order_by(Page.page_no)
    ).all()
    assert [p.parser_layer for p in pages] == ["pdfplumber"] * 3 + ["docling"]
    assert pages[0].has_text_layer
    assert sorted(pages[0].layer_detail) == ["chars", "image_coverage", "tables"]
    scanned = pages[3]
    assert scanned.has_text_layer, "the OCR text is a text layer now"
    assert scanned.text == "This page is an image and has no text layer."
    assert scanned.layer_detail["ocr"] is True and scanned.layer_detail["pages_in_batch"] == 1
    assert docling.calls == [
        {
            "filename": f"{document.sha256[:12]}-scanned.pdf",
            "force_ocr": True,
            "bytes": docling.calls[0]["bytes"],
        }
    ]
    match = resolve("has no text layer", PageText(4, scanned.text, scanned.char_boxes, True))
    assert match.__class__.__name__ == "Match" and match.bbox is not None  # type: ignore[union-attr]


def test_without_docling_a_scanned_page_keeps_no_text_and_the_parse_succeeds(
    pipeline: Pipeline, db: Session
) -> None:
    service = ParseService(pipeline.storage, pipeline.settings)  # no docling_url in tests
    document = pipeline.upload(db, make_pdf(scanned_last_page=True))
    service.parse(db, document.id, map_sections=False)
    scanned = db.scalar(select(Page).where(Page.document_id == document.id, Page.page_no == 4))
    assert scanned is not None and not scanned.has_text_layer
    assert scanned.parser_layer == "pdfplumber"
    assert scanned.layer_detail["docling"] == "not configured"
    down = FakeDocling()
    down.fail = True
    service = ParseService(pipeline.storage, pipeline.settings, docling=down)
    service.parse(db, document.id, map_sections=False)
    db.expire_all()
    scanned = db.scalar(select(Page).where(Page.document_id == document.id, Page.page_no == 4))
    assert scanned is not None and not scanned.has_text_layer
    assert scanned.layer_detail["docling"].startswith("unavailable: docling: ConnectError")
    assert db.get(Document, document.id).status == "parsed"


def test_a_few_native_characters_are_a_text_layer_but_a_picture_page_is_not() -> None:
    from core.services.parse import has_text_layer

    assert has_text_layer(8, 0.0), "a divider page saying NOT USED"
    assert has_text_layer(8, 0.3), "a short page with a logo"
    assert not has_text_layer(8, 0.95), "a scan with a printed header"
    assert not has_text_layer(0, 0.0), "a blank page has nothing to resolve"
    assert has_text_layer(500, 1.0), "a full text layer over a background image"


def test_a_short_native_page_keeps_its_text_layer_and_a_scan_does_not(
    pipeline: Pipeline, db: Session
) -> None:
    service = ParseService(pipeline.storage, pipeline.settings)
    document = pipeline.upload(db, make_pdf([["NOT USED"], PAGE_2], scanned_last_page=True))
    service.parse(db, document.id, map_sections=False)
    pages = db.scalars(
        select(Page).where(Page.document_id == document.id).order_by(Page.page_no)
    ).all()
    assert [p.has_text_layer for p in pages] == [True, True, False]
    assert pages[0].layer_detail["chars"] == 7 and pages[0].layer_detail["image_coverage"] == 0
    assert pages[2].layer_detail["image_coverage"] >= 0.5


def ruled_table_pdf() -> bytes:
    """One page: a paragraph, then a ruled 2x2 table whose second cell wraps."""
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "TYPE OF BIDDING SYSTEM is given in the table below.", fontsize=11)
    x0, y0, w, h = 72.0, 120.0, 200.0, 40.0
    for r in range(2):
        for c in range(2):
            page.draw_rect(pymupdf.Rect(x0 + c * w, y0 + r * h, x0 + (c + 1) * w, y0 + (r + 1) * h))
    page.insert_text((80, 136), "SINGLE BID", fontsize=10)
    page.insert_text((80, 150), "SYSTEM", fontsize=10)
    page.insert_text((280, 143), "No", fontsize=10)
    page.insert_text((80, 176), "TWO BID", fontsize=10)
    page.insert_text((80, 190), "SYSTEM", fontsize=10)
    page.insert_text((280, 183), "Yes", fontsize=10)
    data: bytes = document.tobytes()
    document.close()
    return data


class FakeDoclingTables(FakeDocling):
    def convert(self, pdf: bytes, *, filename: str = "pages.pdf", force_ocr: bool = False):  # type: ignore[no-untyped-def]
        from core.parsing.docling import DoclingResult
        from core.parsing.layers import LayerPage, TextItem

        self.calls.append({"filename": filename, "force_ocr": force_ocr, "bytes": len(pdf)})
        cells = [
            TextItem("SINGLE BID SYSTEM", [72.0, 120.0, 272.0, 160.0], "table_cell"),
            TextItem("No", [272.0, 120.0, 472.0, 160.0], "table_cell"),
            TextItem("TWO BID SYSTEM", [72.0, 160.0, 272.0, 200.0], "table_cell"),
            TextItem("Yes", [272.0, 160.0, 472.0, 200.0], "table_cell"),
        ]
        page = LayerPage(1, 595.0, 842.0, [TextItem("TYPE OF BIDDING SYSTEM", None), *cells])
        return DoclingResult(pages={1: page}, seconds=2.0, detail={"status": "success"})


def test_table_pages_get_docling_s_cells_appended_and_keep_pdfplumber_s_text(
    pipeline: Pipeline, db: Session
) -> None:
    from core.evidence.resolver import PageText, resolve

    docling = FakeDoclingTables()
    service = ParseService(pipeline.storage, pipeline.settings, docling=docling)
    document = pipeline.upload(db, ruled_table_pdf())
    service.parse(db, document.id, map_sections=False)
    page = db.scalar(select(Page).where(Page.document_id == document.id))
    assert page is not None and page.layer_detail["tables"] == 1
    assert page.parser_layer == "pdfplumber+docling"
    assert page.layer_detail["docling_tables"]["cells"] == 4
    [call] = docling.calls
    assert (call["force_ocr"], call["filename"]) == (False, f"{document.sha256[:12]}-tables.pdf")
    assert page.text.startswith("TYPE OF BIDDING SYSTEM is given"), "pdfplumber's text first"
    assert page.text.endswith("SINGLE BID SYSTEM\nNo\nTWO BID SYSTEM\nYes")
    assert len(page.char_boxes) == len(page.text)
    located = resolve("TWO BID SYSTEM", PageText(1, page.text, page.char_boxes, True))
    assert located.__class__.__name__ == "Match"
    assert located.bbox == [72.0, 160.0, 272.0, 200.0], "the cell's box"  # type: ignore[union-attr]
    # the paragraph still resolves on pdfplumber's character boxes
    para = resolve("is given in the table below", PageText(1, page.text, page.char_boxes, True))
    assert para.__class__.__name__ == "Match" and para.bbox[3] < 120  # type: ignore[union-attr,index]


def test_table_pages_are_left_alone_without_a_service_or_when_turned_off(
    pipeline: Pipeline, db: Session
) -> None:
    document = pipeline.upload(db, ruled_table_pdf())
    ParseService(pipeline.storage, pipeline.settings).parse(db, document.id, map_sections=False)
    page = db.scalar(select(Page).where(Page.document_id == document.id))
    assert page is not None and page.parser_layer == "pdfplumber"
    assert page.layer_detail["tables"] == 1 and "docling_tables" not in page.layer_detail
    settings = pipeline.settings.model_copy(update={"docling_tables": False})
    docling = FakeDoclingTables()
    ParseService(pipeline.storage, settings, docling=docling).parse(
        db, document.id, map_sections=False
    )
    assert docling.calls == []
