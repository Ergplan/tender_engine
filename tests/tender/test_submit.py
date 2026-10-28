"""Submission (Stage 7, Block 6 a): a tender from a file or an official URL, an amendment
with its link check, and the `tender_extract` job that reads a version once it is parsed."""

from datetime import UTC, datetime

import httpx2
import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.models import ExtractionRun, Job
from tender.models import Tender
from tender.services.source_domains import SourceAllowlist
from tender.services.submit import Fetcher, SubmitError, SubmitService
from tests.conftest import Pipeline
from tests.fixtures.pdfs import make_pdf
from tests.fixtures.tenders import AMENDMENT_PAGES, RFS_ANSWERS, RFS_PAGES, extracted_tender


def _service(pipeline: Pipeline, transport: httpx2.BaseTransport | None = None) -> SubmitService:
    allowlist = SourceAllowlist(("acme.test",))
    return SubmitService(
        pipeline.tenders,
        pipeline.ingest,
        pipeline.settings.tenant_id,
        fetcher=Fetcher(allowlist, transport),
    )


def _due_now(db: Session) -> None:
    db.execute(update(Job).where(Job.status == "queued").values(run_after=datetime.now(UTC)))
    db.commit()


def _run_all(pipeline: Pipeline, db: Session, rounds: int = 4) -> None:
    """The worker's loop with the submit job's waits collapsed."""
    for _ in range(rounds):
        _due_now(db)
        pipeline.runner.run_until_idle()


def test_a_file_becomes_a_tender_that_is_classified_parsed_and_read(
    pipeline: Pipeline, db: Session
) -> None:
    pipeline.sdk.answers = dict(RFS_ANSWERS)
    service = _service(pipeline)
    pdf = make_pdf(RFS_PAGES)
    submission = service.submit_tender(db, filename="rfs.pdf", data=pdf, created_by="api:key1")
    tender = submission.tender
    assert submission.created and submission.version.version_no == 1
    assert (tender.tender_type, tender.type_source, tender.type_state) == (
        "ipp",
        "model",
        "unknown",
    )
    kinds = sorted(j.kind for j in db.scalars(select(Job).where(Job.status == "queued")))
    assert kinds == ["classify_type", "parse", "tender_extract"]
    _run_all(pipeline, db)
    db.refresh(tender)
    assert (tender.tender_type, tender.type_source, tender.type_state) == ("solar", "model", "set")
    runs = list(db.scalars(select(ExtractionRun).where(ExtractionRun.object_id == tender.id)))
    assert runs and all(r.status == "validated" for r in runs if r.mode != "record")
    assert not db.scalars(select(Job).where(Job.status.in_(("queued", "failed")))).all()
    # The same file again is the same tender, and nothing is queued twice.
    again = service.submit_tender(db, filename="rfs.pdf", data=pdf, created_by="k")
    assert not again.created and again.tender.id == tender.id


def test_a_named_type_skips_the_classifier_and_a_bad_type_is_refused(
    pipeline: Pipeline, db: Session
) -> None:
    service = _service(pipeline)
    with pytest.raises(SubmitError, match="unknown tender type"):
        service.submit_tender(
            db, filename="x.pdf", data=make_pdf(RFS_PAGES), tender_type="nuclear", created_by="k"
        )
    with pytest.raises(SubmitError, match="exactly one"):
        service.submit_tender(db, created_by="k")
    submission = service.submit_tender(
        db,
        filename="rfs.pdf",
        data=make_pdf(RFS_PAGES),
        tender_type="solar",
        agency="Acme",
        title="600 MW solar",
        external_ref="ACME/1",
        created_by="k",
    )
    tender = submission.tender
    assert (tender.tender_type, tender.type_source, tender.title) == (
        "solar",
        "caller",
        "600 MW solar",
    )
    assert not db.scalars(select(Job).where(Job.kind == "classify_type")).all()


def test_a_url_is_fetched_only_from_an_official_source(pipeline: Pipeline, db: Session) -> None:
    pdf = make_pdf(RFS_PAGES)

    def site(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/rfs.pdf"):
            return httpx2.Response(200, content=pdf, headers={"content-type": "application/pdf"})
        if request.url.path == "/moved":
            return httpx2.Response(302, headers={"location": "https://mirror.example/rfs.pdf"})
        return httpx2.Response(404)

    service = _service(pipeline, httpx2.MockTransport(site))
    with pytest.raises(SubmitError, match="not an official source"):
        service.submit_tender(db, source_url="https://mirror.example/rfs.pdf", created_by="k")
    with pytest.raises(SubmitError, match="HTTP 404"):
        service.submit_tender(db, source_url="https://acme.test/missing.pdf", created_by="k")
    with pytest.raises(SubmitError, match="redirected off"):
        service.submit_tender(db, source_url="https://acme.test/moved", created_by="k")
    submission = service.submit_tender(
        db, source_url="https://www.acme.test/tenders/rfs.pdf", tender_type="solar", created_by="k"
    )
    document = submission.document
    assert document.filename == "rfs.pdf"
    assert document.source_url == "https://www.acme.test/tenders/rfs.pdf"
    assert document.retrieved_on == datetime.now(UTC).date()


def test_an_amendment_is_read_after_its_link_check(pipeline: Pipeline, db: Session) -> None:
    tender = extracted_tender(pipeline, db)
    service = _service(pipeline)
    with pytest.raises(SubmitError, match="corrigendum, amendment or clarification"):
        service.submit_amendment(
            db,
            tender,
            kind="original",
            filename="a.pdf",
            data=make_pdf(AMENDMENT_PAGES),
            created_by="k",
        )
    amendment = make_pdf(AMENDMENT_PAGES)
    submission = service.submit_amendment(
        db, tender, kind="amendment", filename="amendment-01.pdf", data=amendment, created_by="k"
    )
    assert submission.version.version_no == 2 and submission.created
    job = db.scalars(select(Job).where(Job.kind == "tender_extract")).one()
    assert job.payload["link_check"] is True and job.payload["version_no"] == 2
    _run_all(pipeline, db)
    runs = list(
        db.scalars(
            select(ExtractionRun).where(
                ExtractionRun.object_id == tender.id, ExtractionRun.object_version == 2
            )
        )
    )
    assert runs and all(r.status == "validated" for r in runs if r.mode != "record")
    # The same amendment under another tender is refused: it is this tender's document.
    other = pipeline.tenders.create(
        db,
        tender_type="solar",
        issuing_agency="Other",
        external_ref=None,
        title="Other",
        created_by="k",
    )
    with pytest.raises(SubmitError, match="already a document of tender"):
        service.submit_amendment(
            db, other, kind="amendment", filename="amendment-01.pdf", data=amendment, created_by="k"
        )


def test_an_amendment_that_names_another_tender_is_not_read_unless_forced(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    stranger = db.scalar(select(Tender).where(Tender.id == tender.id))
    assert stranger is not None
    # A second tender whose reference the amendment prints.
    other = pipeline.tenders.create(
        db,
        tender_type="solar",
        issuing_agency="Acme Renewables Agency",
        external_ref="ACME/RE/2026/099",
        title="Another solar scheme of 300 MW",
        created_by="k",
    )
    pages = [["AMENDMENT-01 to RfS No. ACME/RE/2026/099", "The deadline is extended."]]
    wrong = make_pdf(pages)
    service = _service(pipeline)
    service.submit_amendment(
        db, tender, kind="amendment", filename="wrong.pdf", data=wrong, created_by="k"
    )
    _run_all(pipeline, db)
    failed = db.scalars(select(Job).where(Job.kind == "tender_extract")).one()
    assert failed.status == "failed" and other.id in (failed.last_error or "")
    assert not db.scalars(
        select(ExtractionRun).where(
            ExtractionRun.object_id == tender.id, ExtractionRun.object_version == 2
        )
    ).all()
    # Forced: the caller insists; the same file is already version 2, so nothing is filed twice.
    forced = service.submit_amendment(
        db, tender, kind="amendment", filename="wrong.pdf", data=wrong, created_by="k", force=True
    )
    assert not forced.created, "the document is already version 2; nothing is filed twice"
