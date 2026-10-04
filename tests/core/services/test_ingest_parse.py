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


def test_a_file_that_is_not_a_pdf_is_refused(pipeline: Pipeline, db: Session) -> None:
    with pytest.raises(IngestError, match="not a PDF"):
        pipeline.ingest.upload(db, filename="a.txt", data=b"hello", created_by="x")
    assert db.scalar(select(func.count()).select_from(Document)) == 0


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


def test_an_unreadable_pdf_marks_the_document_failed(pipeline: Pipeline, db: Session) -> None:
    document = pipeline.upload(db, b"%PDF-1.7\nthis is not really a pdf")
    with pytest.raises(Exception):  # noqa: B017 - the reader's own error type
        ParseService(pipeline.storage, pipeline.settings).parse(db, document.id)
    db.refresh(document)
    assert document.status == "failed" and document.error
    assert db.scalar(select(func.count()).select_from(Page)) == 0


def test_parse_of_an_unknown_document_is_a_lookup_error(pipeline: Pipeline, db: Session) -> None:
    with pytest.raises(LookupError):
        ParseService(pipeline.storage, pipeline.settings).parse(db, "0" * 32)
