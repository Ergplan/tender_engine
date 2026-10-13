"""The freshness check: a tender's source page read again, its documents hashed and compared
with what is held; new, changed and unchanged told apart by content; nothing ingested;
recorded in the audit log; queued again for next week."""

import hashlib
from datetime import date, timedelta
from pathlib import Path

import httpx2
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import AuditLog, Document, Job
from core.services import jobs
from tender.models import Tender
from tender.services import freshness
from tender.services.freshness import FreshnessChecker, SourceCheck
from tests.conftest import Pipeline
from tests.fixtures.pdfs import make_pdf

PAGE = "https://agency.example/tender-details/abc"
RFS = make_pdf([["RfS for 600 MW solar", "Bid deadline 30.03.2026"]])
AMENDMENT_1 = make_pdf([["Amendment-01", "Deadline extended"]])
AMENDMENT_2 = make_pdf([["Amendment-02", "EMD restated"]])
RFS_REVISED = make_pdf([["Revised RfS for 600 MW solar", "Bid deadline 30.04.2026"]])


def page_html(links: list[str]) -> str:
    items = "".join(f'<li><a href="{href}">{href.rsplit("/", 1)[-1]}</a></li>' for href in links)
    return (
        "<html><body><h1>Tender</h1>"
        '<a href="/tender-details/abc">this page</a>'
        '<a href="mailto:x@agency.example">write</a>'
        f"<ul>{items}</ul></body></html>"
    )


def site(files: dict[str, bytes], page: str) -> httpx2.MockTransport:
    """The agency's site: the tender page and the files it links."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == PAGE:
            return httpx2.Response(200, text=page)
        name = request.url.path.rsplit("/", 1)[-1]
        if name in files:
            return httpx2.Response(200, content=files[name])
        return httpx2.Response(404, text="no such file")

    return httpx2.MockTransport(handle)


def tender_with_documents(pipeline: Pipeline, db: Session, root: Path) -> Tender:
    """A tender holding the RfS and Amendment-01, with a manifest naming its page."""
    tender = pipeline.tenders.create(
        db,
        tender_type="solar",
        issuing_agency="Agency",
        external_ref="A/1",
        title="600 MW solar",
        created_by="pytest",
        slug="acme-solar-600",
    )
    rfs = pipeline.upload(db, RFS, "rfs.pdf")
    pipeline.tenders.add_version(db, tender, rfs, "original", date(2026, 3, 1), created_by="t")
    amendment = pipeline.upload(db, AMENDMENT_1, "amendment-01.pdf")
    pipeline.tenders.add_version(
        db, tender, amendment, "amendment", date(2026, 3, 20), created_by="t"
    )
    notice = pipeline.upload(db, make_pdf([["Tender notice page"]]), "Tender_notice_page.pdf")
    pipeline.tenders.attach_document(db, tender, 2, notice, "nit", created_by="t")
    db.commit()
    folder = root / "solar" / "acme-solar-600"
    folder.mkdir(parents=True)
    (folder / "manifest.yaml").write_text(
        yaml.safe_dump({"slug": "acme-solar-600", "type": "solar", "notice_url": PAGE, "files": []})
    )
    return tender


def test_source_pages_come_from_the_manifests(tmp_path: Path) -> None:
    folder = tmp_path / "wind" / "w-1"
    folder.mkdir(parents=True)
    (folder / "manifest.yaml").write_text(yaml.safe_dump({"slug": "w-1", "source": "/local/copy"}))
    folder = tmp_path / "wind" / "w-2"
    folder.mkdir(parents=True)
    (folder / "manifest.yaml").write_text(
        yaml.safe_dump({"slug": "w-2", "source": "https://a.example/t/2"})
    )
    folder = tmp_path / "solar" / "s-1"
    folder.mkdir(parents=True)
    (folder / "manifest.yaml").write_text(yaml.safe_dump({"slug": "s-1", "notice_url": PAGE}))
    assert freshness.source_pages(tmp_path) == {"w-2": "https://a.example/t/2", "s-1": PAGE}, (
        "a local path is where a copy came from, not the agency's page"
    )


def test_listed_documents_are_the_document_links_of_the_page_each_once() -> None:
    body = page_html(
        [
            "/uploads/rfs.pdf",
            "https://agency.example/uploads/Amendment%2001.pdf",
            "/uploads/rfs.pdf?download=1",
            "/uploads/sheet.xlsx",
            "/uploads/image.png",
        ]
    )
    assert freshness.listed_documents(PAGE, body) == [
        ("https://agency.example/uploads/rfs.pdf", "rfs.pdf"),
        ("https://agency.example/uploads/Amendment%2001.pdf", "Amendment 01.pdf"),
        ("https://agency.example/uploads/rfs.pdf?download=1", "rfs.pdf"),
        ("https://agency.example/uploads/sheet.xlsx", "sheet.xlsx"),
    ]


def test_new_changed_and_unchanged_files_are_told_apart_by_content_and_nothing_is_ingested(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    tender = tender_with_documents(pipeline, db, tmp_path)
    documents_before = db.scalar(select(func.count()).select_from(Document))
    # The page now lists: the RfS under a new name (same bytes), Amendment-01 re-posted
    # with other content under its old name, a new Amendment-02, and a broken link.
    page = page_html(
        [
            "/uploads/RfS_600MW_final.pdf",
            "/uploads/amendment-01.pdf",
            "/uploads/Amendment-02.pdf",
            "/uploads/missing.pdf",
        ]
    )
    files = {
        "RfS_600MW_final.pdf": RFS,
        "amendment-01.pdf": RFS_REVISED,
        "Amendment-02.pdf": AMENDMENT_2,
    }
    checker = FreshnessChecker(
        pipeline.settings.tenant_id, tenders_root=tmp_path, transport=site(files, page)
    )
    (check,) = checker.check_all(db)
    assert (check.slug, check.page_url, check.reachable, check.error) == (
        "acme-solar-600",
        PAGE,
        True,
        None,
    )
    assert (check.listed, check.held) == (4, 2), "the notice page captured by hand is not held"
    assert check.unchanged == 1, "the RfS under its new name is the same bytes"
    assert [c.filename for c in check.changed] == ["amendment-01.pdf"]
    assert check.changed[0].held_as == "amendment-01.pdf"
    assert check.changed[0].sha256 == hashlib.sha256(RFS_REVISED).hexdigest()
    assert [c.filename for c in check.new] == ["Amendment-02.pdf"]
    assert check.new[0].size == len(AMENDMENT_2)
    assert [c.filename for c in check.unreadable] == ["missing.pdf"]
    assert "404" in (check.unreadable[0].error or "")
    assert check.not_listed == ["amendment-01.pdf"], (
        "its content is no longer served under any name"
    )
    assert check.stale
    # Nothing was ingested; the comparison is in the audit log and is what `latest` reads.
    assert db.scalar(select(func.count()).select_from(Document)) == documents_before
    row = db.scalars(
        select(AuditLog).where(AuditLog.action == freshness.ACTION, AuditLog.row_id == tender.id)
    ).one()
    assert row.actor == freshness.ACTOR and row.after is not None
    assert SourceCheck.model_validate(row.after) == check
    assert freshness.latest(db, pipeline.settings.tenant_id) == [check]


def test_site_wide_files_zip_members_and_a_documents_own_url_are_told_apart(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    """A brochure linked from two tenders' pages is the agency's, not either tender's; a zip
    whose members the corpus holds is unchanged; a held document with a URL of its own is
    fetched from there even when the page does not link it."""
    import io
    import zipfile

    solar = tender_with_documents(pipeline, db, tmp_path)
    wind = pipeline.tenders.create(
        db,
        tender_type="wind",
        issuing_agency="Agency",
        external_ref=None,
        title="Wind",
        created_by="pytest",
        slug="acme-wind-1",
    )
    wind_bytes = make_pdf([["Wind RfS"]])
    wind_rfs, _ = pipeline.ingest.upload(
        db,
        filename="wind-rfs.pdf",
        data=wind_bytes,
        created_by="t",
        source_url="https://agency.example/files/wind-rfs.pdf",
    )
    pipeline.tenders.add_version(db, wind, wind_rfs, "original", date(2026, 5, 1), created_by="t")
    db.commit()
    folder = tmp_path / "wind" / "acme-wind-1"
    folder.mkdir(parents=True)
    wind_page = "https://agency.example/tender-details/wind"
    (folder / "manifest.yaml").write_text(
        yaml.safe_dump({"slug": "acme-wind-1", "notice_url": wind_page})
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("rfs.pdf", RFS)
        zipped.writestr("amendment-01.pdf", AMENDMENT_1)
    brochure = make_pdf([["About the agency"]])
    solar_page = page_html(["/uploads/brochure.pdf", "/uploads/Package.zip"])
    wind_html = page_html(["/uploads/brochure.pdf"])
    files = {
        "brochure.pdf": brochure,
        "Package.zip": archive.getvalue(),
        "wind-rfs.pdf": wind_bytes,
    }

    def handle(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == PAGE:
            return httpx2.Response(200, text=solar_page)
        if str(request.url) == wind_page:
            return httpx2.Response(200, text=wind_html)
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx2.Response(200, content=files[name]) if name in files else httpx2.Response(404)

    checker = FreshnessChecker(
        pipeline.settings.tenant_id, tenders_root=tmp_path, transport=httpx2.MockTransport(handle)
    )
    first, second = checker.check_all(db)
    assert (first.slug, second.slug) == ("acme-solar-600", "acme-wind-1")
    assert [i.filename for i in first.site_wide] == ["brochure.pdf"] and first.new == []
    assert [i.filename for i in second.site_wide] == ["brochure.pdf"] and second.new == []
    assert first.unchanged == 1 and first.not_listed == [], "the zip holds both held files"
    assert first.listed == 2
    # The wind page links nothing of the tender's; the RfS is re-read at its own URL.
    assert second.listed == 2 and second.unchanged == 1 and second.not_listed == []
    assert not first.stale and not second.stale
    assert first.tender_id == solar.id


def test_an_unreachable_page_and_a_tender_without_a_page_are_reported_not_failed(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    tender_with_documents(pipeline, db, tmp_path)
    pipeline.tenders.create(
        db,
        tender_type="wind",
        issuing_agency="Agency",
        external_ref=None,
        title="Wind",
        created_by="pytest",
        slug="no-manifest",
    )
    db.commit()

    def down(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, text="maintenance")

    checker = FreshnessChecker(
        pipeline.settings.tenant_id, tenders_root=tmp_path, transport=httpx2.MockTransport(down)
    )
    solar, wind = checker.check_all(db)
    assert solar.slug == "acme-solar-600" and not solar.reachable and "503" in (solar.error or "")
    assert solar.held == 2 and not solar.stale
    assert (wind.page_url, wind.reachable, wind.error) == (
        None,
        False,
        "no source page in the tender's manifest",
    )
    text = freshness.report_text([solar, wind], solar.checked_at)
    assert "| acme-solar-600 |" in text and "unreachable" in text
    assert "no source page in the tender's manifest" in text
    assert "Tenders checked: 2; with new or changed files: 0; unreachable: 2." in text


def test_the_job_checks_every_tender_then_queues_itself_for_next_week(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    tender_with_documents(pipeline, db, tmp_path)
    page = page_html(["/uploads/rfs.pdf", "/uploads/amendment-01.pdf"])
    files = {"rfs.pdf": RFS, "amendment-01.pdf": AMENDMENT_1}
    checker = FreshnessChecker(
        pipeline.settings.tenant_id, tenders_root=tmp_path, transport=site(files, page)
    )
    tenant = pipeline.settings.tenant_id
    handlers = freshness.job_handlers(checker, tenant, interval_days=7)
    assert freshness.ensure_scheduled(db, tenant) is True
    assert freshness.ensure_scheduled(db, tenant) is False, "one pending check at a time"
    first = db.scalars(select(Job).where(Job.kind == freshness.JOB_KIND)).one()
    assert first.run_after <= first.created_at, "due now"

    handlers[freshness.JOB_KIND](db, dict(first.payload))
    (check,) = freshness.latest(db, tenant)
    assert (check.unchanged, check.new, check.changed, check.not_listed) == (2, [], [], [])
    queued = [
        job
        for job in db.scalars(select(Job).where(Job.kind == freshness.JOB_KIND))
        if job.id != first.id
    ]
    assert len(queued) == 1
    a_week = queued[0].run_after - queued[0].created_at
    assert timedelta(days=6, hours=23) < a_week <= timedelta(days=7)
    assert freshness.ensure_scheduled(db, tenant) is False, "next week's is already queued"

    # A check asked for on demand does not add another weekly one.
    jobs.enqueue(
        db, tenant_id=tenant, kind=freshness.JOB_KIND, payload={"repeat": False}, created_by="x"
    )
    db.commit()
    handlers[freshness.JOB_KIND](db, {"repeat": False, "created_by": "venture"})
    assert (
        db.scalar(select(func.count()).select_from(Job).where(Job.kind == freshness.JOB_KIND)) == 3
    )
    rows = db.scalars(select(AuditLog).where(AuditLog.action == freshness.ACTION)).all()
    assert [row.actor for row in rows] == [freshness.ACTOR, "venture"]
    # With the interval off, the job does not queue itself.
    once = freshness.job_handlers(checker, tenant, interval_days=0)
    once[freshness.JOB_KIND](db, {})
    assert (
        db.scalar(select(func.count()).select_from(Job).where(Job.kind == freshness.JOB_KIND)) == 3
    )
