"""The published view as a PDF with its page-reference appendix."""

import pymupdf
from sqlalchemy.orm import Session

from tender.services.changelog import changelog
from tender.services.published import published_tender
from tender.services.published_pdf import render_pdf
from tests.conftest import Pipeline
from tests.fixtures.tenders import amended_tender
from tests.tender.test_rounds import reviewed_tender


def test_the_pdf_carries_the_facts_the_changelog_and_the_page_references(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, _ = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    view = published_tender(db, pipeline.catalog, tender)
    data = render_pdf(view, changelog(db, pipeline.catalog, tender))
    assert data.startswith(b"%PDF")
    with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        assert doc.page_count >= 2
        text = "\n".join(page.get_text() for page in doc)
    assert tender.title in text and "Publication: published" in text
    assert "Appendix: page references" in text
    assert "[1] rfs.pdf, page" in text
    assert "The last date of bid submission is 30.03.2026" in text
    assert "Changelog across versions" in text and "Version 1" in text
    assert "The tender document is the authoritative source" in text
    # The same view gives the same document (the file identifier alone differs per save).
    with pymupdf.open(
        stream=render_pdf(view, changelog(db, pipeline.catalog, tender)), filetype="pdf"
    ) as again:  # type: ignore[no-untyped-call]
        assert "\n".join(page.get_text() for page in again) == text


def test_a_suspended_view_renders_the_suspension_and_no_values(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, _ = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    amended_tender(pipeline, db, tender)
    # The route hands the renderer the real changelog; a suspended tender keeps its old and
    # new values out of the PDF as it keeps them out of the view.
    data = render_pdf(
        published_tender(db, pipeline.catalog, tender), changelog(db, pipeline.catalog, tender)
    )
    with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        text = "\n".join(page.get_text() for page in doc)
    assert "Publication suspended" in text and "No evidence pages" in text
    assert "Changelog" not in text and "→" not in text
    assert "30.03.2026" not in text and "15.04.2026" not in text
    assert "2026-03-30" not in text and "2026-04-15" not in text
