"""The management command on a synthetic tender folder, with the scripted model."""

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Document, ExtractionRun
from scripts import ingest_tenders
from scripts.ingest_tenders import Manifest, ManifestFile, Services, plan_versions
from tender.models import Tender, TenderVersion
from tender.services.worker_jobs import summary_writer
from tests.conftest import Pipeline
from tests.fixtures.llm import ScriptedSDK
from tests.fixtures.pdfs import make_pdf
from tests.fixtures.tenders import AMENDMENT_ANSWERS, AMENDMENT_PAGES, RFS_ANSWERS, RFS_PAGES

PPA_PAGES = [["DRAFT POWER PURCHASE AGREEMENT", "Article 10: the tariff is fixed for the term."]]


def services_of(pipeline: Pipeline) -> Services:
    return Services(
        settings=pipeline.settings,
        session_factory=pipeline.session_factory,
        catalog=pipeline.catalog,
        ingest=pipeline.ingest,
        tenders=pipeline.tenders,
        review=pipeline.review_state,
        extract=pipeline.extract,
        summaries=summary_writer(
            pipeline.llm,
            pipeline.catalog,
            pipeline.extract,
            pipeline.schemas,
            pipeline.settings.tenant_id,
        ),
    )


def write_folder(root: Path) -> None:
    folder = root / "solar" / "acme-solar-600"
    folder.mkdir(parents=True)
    (folder / "rfs.pdf").write_bytes(make_pdf(RFS_PAGES))
    (folder / "ppa.pdf").write_bytes(make_pdf(PPA_PAGES))
    (folder / "amendment-01.pdf").write_bytes(make_pdf(AMENDMENT_PAGES))
    manifest = {
        "slug": "acme-solar-600",
        "type": "solar",
        "agency": "Acme Renewables Agency",
        "external_ref": "ACME/RE/2026/007",
        "title": "Selection of solar power developers for 600 MW solar PV projects",
        "source": TENDER_PAGE,
        "files": [
            {"file": "rfs.pdf", "role": "rfs", "issued_on": "2026-03-01", "pages": 3},
            {"file": "amendment-01.pdf", "role": "amendment", "issued_on": "2026-03-20"},
            {
                "file": "ppa.pdf",
                "role": "ppa",
                "issued_on": None,
                "pages": 1,
                "source": PPA_URL,
                "retrieved_on": "2026-10-04",
            },
        ],
    }
    (folder / "manifest.yaml").write_text(yaml.safe_dump(manifest))


TENDER_PAGE = "https://acme.example/tender-details/600"
PPA_URL = "https://acme.example/uploads/ppa.pdf"


def test_a_file_takes_its_own_source_else_the_tender_page_and_a_local_path_is_no_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tenders"
    write_folder(root)
    copied = root / "wind" / "copied-wind"
    copied.mkdir(parents=True)
    (copied / "rfs.pdf").write_bytes(make_pdf(RFS_PAGES))
    (copied / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "slug": "copied-wind",
                "type": "wind",
                "agency": "A",
                "title": "T",
                "source": "/work/ref/somewhere/RFS.pdf (copied from a reference repo)",
                "files": [{"file": "rfs.pdf", "role": "rfs", "issued_on": "2026-03-01"}],
            }
        )
    )
    noticed = root / "wind" / "noticed-wind"
    noticed.mkdir(parents=True)
    (noticed / "nit.pdf").write_bytes(make_pdf(RFS_PAGES))
    (noticed / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "slug": "noticed-wind",
                "type": "wind",
                "agency": "A",
                "title": "T",
                "notice_url": "https://acme.example/tender-details/7",
                "files": [{"file": "nit.pdf", "role": "nit", "issued_on": None}],
            }
        )
    )
    by_slug = {m.slug: m for m in ingest_tenders.read_manifests(root)}
    acme = {f.path.name: (f.source, f.retrieved_on) for f in by_slug["acme-solar-600"].files}
    assert [f.source for f in by_slug["noticed-wind"].files] == [
        "https://acme.example/tender-details/7"
    ], "the notice page is where the files were taken from when nothing closer is recorded"
    assert acme == {
        "rfs.pdf": (TENDER_PAGE, None),
        "amendment-01.pdf": (TENDER_PAGE, None),
        "ppa.pdf": (PPA_URL, date(2026, 10, 4)),
    }
    assert [(f.source, f.retrieved_on) for f in by_slug["copied-wind"].files] == [(None, None)]


def test_provenance_fills_documents_ingested_before_it_was_recorded(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    root = tmp_path / "tenders"
    write_folder(root)
    services = services_of(pipeline)
    # The RfS was uploaded before manifests carried a source; the PPA by hand with one.
    earlier, _ = pipeline.ingest.upload(
        db,
        filename="rfs.pdf",
        data=(root / "solar/acme-solar-600/rfs.pdf").read_bytes(),
        created_by="x",
    )
    by_hand, _ = pipeline.ingest.upload(
        db,
        filename="ppa.pdf",
        data=(root / "solar/acme-solar-600/ppa.pdf").read_bytes(),
        created_by="x",
        source_url="https://acme.example/by-hand.pdf",
    )
    assert earlier.source_url is None

    assert ingest_tenders.provenance(services, root) == [
        "solar/acme-solar-600: 2 filled, 0 without a source"
    ]
    db.expire_all()
    assert (earlier.source_url, earlier.retrieved_on) == (TENDER_PAGE, None)
    assert (by_hand.source_url, by_hand.retrieved_on) == (
        "https://acme.example/by-hand.pdf",
        date(2026, 10, 4),
    ), "the source set by hand stands; the date it lacked is filled"
    assert ingest_tenders.provenance(services, root) == [
        "solar/acme-solar-600: 0 filled, 0 without a source"
    ], "repeating the command changes nothing"
    assert db.scalar(select(func.count()).select_from(Tender)) == 0, "no tender was created"

    ingest_tenders.ingest(services, root)
    db.expire_all()
    amendment = db.scalars(select(Document).where(Document.filename == "amendment-01.pdf")).one()
    assert amendment.source_url == TENDER_PAGE, "ingest records the source as it uploads"


def files(*items: tuple[str, str, str | None]) -> Manifest:
    return Manifest(
        slug="x",
        tender_type="fdre",
        agency="A",
        external_ref=None,
        title="T",
        files=[
            ManifestFile(Path(name), role, date.fromisoformat(day) if day else None)
            for name, role, day in items
        ],
    )


def shape(manifest: Manifest) -> list[tuple[str, list[str]]]:
    return [(v.kind, [f.path.name for f in v.files]) for v in plan_versions(manifest)]


def test_undated_agreements_belong_to_the_original_and_each_change_is_a_version() -> None:
    manifest = files(
        ("rfs", "rfs", "2026-03-10"),
        ("a1", "amendment", "2026-04-02"),
        ("a2", "amendment", "2026-04-27"),
        ("a3", "amendment", "2026-06-25"),
        ("c1", "clarification", "2026-04-27"),
        ("ppa", "ppa", None),
        ("psa", "psa", None),
    )
    assert shape(manifest) == [
        ("original", ["rfs", "ppa", "psa"]),
        ("amendment", ["a1"]),
        ("amendment", ["a2"]),
        ("clarification", ["c1"]),
        ("amendment", ["a3"]),
    ]


def test_a_revised_base_document_is_its_own_version_and_annexures_join_their_amendment() -> None:
    revised = files(
        ("rfs", "rfs", "2026-04-19"),
        ("revised-rfs", "rfs", "2026-07-15"),
        ("a1", "amendment", "2026-07-17"),
        ("cfda", "cfda", None),
    )
    assert shape(revised) == [
        ("original", ["rfs", "cfda"]),
        ("amendment", ["revised-rfs"]),
        ("amendment", ["a1"]),
    ]
    annexures = files(
        ("contract", "contractual", "2026-06-24"),
        ("technical", "technical", "2026-06-24"),
        ("a2", "amendment", "2026-08-28"),
        ("a3", "amendment", "2026-09-15"),
        ("sld", "technical", "2026-09-15"),
        ("layout", "technical", "2026-09-15"),
    )
    assert shape(annexures) == [
        ("original", ["contract", "technical"]),
        ("amendment", ["a2"]),
        ("amendment", ["a3", "sld", "layout"]),
    ]
    undated_change = files(("rfs", "rfs", "2026-09-03"), ("note", "clarification", None))
    assert shape(undated_change) == [("original", ["rfs"]), ("clarification", ["note"])]


def test_ingest_extract_and_summary_on_a_tender_folder(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    root = tmp_path / "tenders"
    write_folder(root)
    services = services_of(pipeline)

    lines = ingest_tenders.ingest(services, root)
    assert lines == ["solar/acme-solar-600: 2 version(s) [v1:2, v2:1]"]
    assert ingest_tenders.ingest(services, root) == lines, "repeating the command changes nothing"
    assert db.scalar(select(func.count()).select_from(Tender)) == 1
    assert db.scalar(select(func.count()).select_from(TenderVersion)) == 2
    assert db.scalar(select(func.count()).select_from(Document)) == 3
    tender = db.scalars(select(Tender)).one()
    assert (tender.slug, tender.tender_type) == ("acme-solar-600", "solar")
    roles = [
        (entry.version.version_no, entry.version.kind, [link.role for link, _ in entry.documents])
        for entry in pipeline.tenders.versions(db, tender)
    ]
    assert roles == [(1, "original", ["rfs", "ppa"]), (2, "amendment", ["amendment"])]

    not_ready = ingest_tenders.extract(services)
    assert all("skipped" in line and "not parsed yet" in line for line in not_ready)
    assert ingest_tenders.pending_jobs(services) == {"queued": 3}
    pipeline.runner.run_until_idle()
    assert ingest_tenders.wait(services, timeout=1, poll=0.01) is True

    pipeline.sdk.answers = {**RFS_ANSWERS, **AMENDMENT_ANSWERS}
    started = ingest_tenders.extract(services)
    assert started == [
        "acme-solar-600 v1: 2 run(s), 14 group call(s)",
        "acme-solar-600 v2: 0 run(s), 0 group call(s); mapped first",
    ]
    assert ingest_tenders.extract(services) == [], "versions with runs or a map queued are left"
    assert ingest_tenders.extract(services, only={"another"}, force=True) == []
    pipeline.runner.run_until_idle()
    assert set(db.scalars(select(ExtractionRun.status))) == {"validated"}

    out = tmp_path / "EXTRACTION-SUMMARY.md"
    text = ingest_tenders.summary(services, out)
    assert out.read_text() == text
    # Extracted fields: the derived tables are written from decisions, not read, and are
    # not rated.
    fields = len([f for f in pipeline.catalog.get("solar").fields if f.section != "derived"])
    row = next(line for line in text.splitlines() if line.startswith("| solar | acme-solar-600"))
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    # type, tender, versions, documents, pages, fields, with a value, located, rates...
    assert cells[2:6] == ["2", "3", "5", str(fields)]
    answered = int(cells[6])
    # The scripted model repeats the RfS answers for the amendment, so version 2 returns a
    # pre-bid date whose quote is not in the amendment: a value without located evidence.
    assert answered == 10 and cells[7] == "9"
    assert cells[8] == "90%" and cells[9] == f"{100 * answered / fields:.0f}%"
    assert "## Per tender type" in text and "## Per section, all tenders" in text
    assert "| solar | `core.key_dates.pre_bid_meeting_date` | 1 | 0 | 0% | acme-solar-600 |" in text
    db.refresh(tender)
    assert tender.status == "extracted"


def test_resume_continues_a_failed_run_without_repeating_finished_groups(
    make_pipeline: Callable[..., Pipeline], db: Session, tmp_path: Path
) -> None:
    """The model account runs dry part-way: the run fails at once. After `resume` the run
    finishes, and the groups it had already extracted are not called again."""
    root = tmp_path / "tenders"
    write_folder(root)
    budget = {"calls": 4}

    def out_of_credit(number: int, request: dict[str, Any]) -> None:
        if request["output_format"].__name__.startswith(("Extract_", "SharedAnswer")):
            budget["calls"] -= 1
            if budget["calls"] < 0:
                raise anthropic.BadRequestError(
                    "Your credit balance is too low",
                    response=httpx2.Response(400, request=httpx2.Request("POST", "http://x")),
                    body=None,
                )

    pipeline = make_pipeline(ScriptedSDK(dict(RFS_ANSWERS), before_call=out_of_credit))
    services = services_of(pipeline)
    ingest_tenders.ingest(services, root, only={"acme-solar-600"})
    pipeline.runner.run_until_idle()
    ingest_tenders.extract(services, run_mode="sync")
    pipeline.runner.run_until_idle()
    statuses = sorted(db.scalars(select(ExtractionRun.status)))
    assert statuses == ["failed", "failed", "failed"]
    assert ingest_tenders.pending_jobs(services).get("failed") == 3
    done_before = len(pipeline.sdk.extract_calls())
    assert done_before == 7, "four calls answered, three refused"
    assert ingest_tenders.resume(services, only={"another"}) == []

    budget["calls"] = 1000
    lines = ingest_tenders.resume(services)
    assert len(lines) == 3 and all("queued again" in line for line in lines)
    assert ingest_tenders.resume(services) == [], "nothing is left to resume"
    pipeline.runner.run_until_idle()
    db.expire_all()
    assert set(db.scalars(select(ExtractionRun.status))) == {"validated"}
    assert set(db.scalars(select(ExtractionRun.error))) == {None}
    # 12 + 1 group calls, plus supply_sources on both documents (v3); the four that
    # succeeded before are not repeated.
    assert len(pipeline.sdk.extract_calls()) - done_before == 15 - 4


def test_groups_narrow_a_re_extraction_to_those_sections_of_each_document(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    root = tmp_path / "tenders"
    write_folder(root)
    services = services_of(pipeline)
    pipeline.sdk.answers = dict(RFS_ANSWERS)
    ingest_tenders.ingest(services, root)
    pipeline.runner.run_until_idle()
    ingest_tenders.extract(services, run_mode="sync")
    pipeline.runner.run_until_idle()
    calls = len(pipeline.sdk.extract_calls())

    again = ingest_tenders.extract(
        services, force=True, groups=["key_dates", "eligibility"], run_mode="sync"
    )
    assert again == [
        "acme-solar-600 v1: 1 run(s), 2 group call(s)",
        "acme-solar-600 v2: 1 run(s), 1 group call(s)",
    ], "the PPA is not read for these sections; the amendment only for the one it touches"
    pipeline.runner.run_until_idle()
    assert len(pipeline.sdk.extract_calls()) - calls == 3
    narrowed = db.scalars(
        select(ExtractionRun).order_by(ExtractionRun.created_at.desc(), ExtractionRun.id).limit(2)
    ).all()
    assert sorted(tuple(run.groups or []) for run in narrowed) == [
        ("eligibility", "key_dates"),
        ("key_dates",),
    ]


def test_amendment_routing_records_the_comparison_for_every_amending_document(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    root = tmp_path / "tenders"
    write_folder(root)
    services = services_of(pipeline)
    pipeline.sdk.answers = dict(RFS_ANSWERS)
    ingest_tenders.ingest(services, root)
    pipeline.runner.run_until_idle()
    ingest_tenders.extract(services)
    pipeline.runner.run_until_idle()
    runs_before = db.scalar(select(func.count()).select_from(ExtractionRun))

    pipeline.sdk.amendment_changes = [
        {"clause": "BIS", "section": "key_dates", "summary": "deadline", "page_no": 1},
        {"clause": "16", "section": "guarantees", "summary": "EMD", "page_no": 1},
    ]
    assert ingest_tenders.amendment_routing(services) == ["acme-solar-600 v2: amendment-01.pdf"]
    pipeline.runner.run_until_idle()
    assert db.scalar(select(func.count()).select_from(ExtractionRun)) == runs_before
    first, line = ingest_tenders.routing_report(services)
    assert first.startswith("DISAGREE | amendment-01.pdf (1 p) | keywords only: ['key_dates']")
    assert line == (
        "DISAGREE | amendment-01.pdf (1 p) | keywords only: [] | map only: ['guarantees'] | "
        "both: ['key_dates']"
    )
    ingest_tenders.amendment_routing(services, mode="missing")
    pipeline.runner.run_until_idle()
    newest = db.scalars(
        select(ExtractionRun)
        .where(ExtractionRun.mode != "record")
        .order_by(ExtractionRun.created_at.desc(), ExtractionRun.id)
        .limit(1)
    ).one()
    assert newest.groups == ["guarantees"] and newest.object_version == 2


def test_resume_puts_a_failed_amendment_map_back_in_the_queue(
    make_pipeline: Callable[..., Pipeline], db: Session, tmp_path: Path
) -> None:
    from core.models import Job

    root = tmp_path / "tenders"
    write_folder(root)
    refuse = {"on": True}

    def no_maps(number: int, request: dict[str, Any]) -> None:
        if refuse["on"] and "AmendmentMapOutput" in str(request["output_format"]):
            raise anthropic.BadRequestError(
                "Your credit balance is too low",
                response=httpx2.Response(400, request=httpx2.Request("POST", "http://x")),
                body=None,
            )

    pipeline = make_pipeline(ScriptedSDK(dict(RFS_ANSWERS), before_call=no_maps))
    services = services_of(pipeline)
    ingest_tenders.ingest(services, root)
    pipeline.runner.run_until_idle()
    ingest_tenders.extract(services)
    pipeline.runner.run_until_idle()
    failed = db.scalars(select(Job).where(Job.status == "failed")).one()
    assert failed.kind == "amendment_plan"
    assert (
        db.scalar(
            select(func.count()).select_from(ExtractionRun).where(ExtractionRun.object_version == 2)
        )
        == 0
    )
    refuse["on"] = False
    assert ingest_tenders.resume(services) == ["acme-solar-600 v2: amendment map queued again"]
    pipeline.runner.run_until_idle()
    db.expire_all()
    (run,) = db.scalars(select(ExtractionRun).where(ExtractionRun.object_version == 2))
    assert run.status == "validated" and run.groups == ["key_dates"]


def test_cost_plan_prices_the_pages_without_calling_the_model(
    pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    root = tmp_path / "tenders"
    write_folder(root)
    services = services_of(pipeline)
    pipeline.sdk.answers = dict(RFS_ANSWERS)
    ingest_tenders.ingest(services, root, only={"acme-solar-600"})
    pipeline.runner.run_until_idle()
    ingest_tenders.extract(services)
    pipeline.runner.run_until_idle()
    calls = len(pipeline.sdk.calls)

    header, _, row, total = ingest_tenders.cost_plan(services)

    assert len(pipeline.sdk.calls) == calls
    assert header.startswith("| Tender | Calls before | Pages before |")
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[0] == "acme-solar-600"
    numbers = [float(cell.replace(",", "")) for cell in cells[1:]]
    calls_before, pages_before, calls_now, written, read, plain, direct, batch = numbers
    assert calls_before >= calls_now > 0
    # Every page a section asked for is still sent to it, shared or not.
    assert written + read + plain >= pages_before
    assert direct <= pages_before and batch <= direct
    assert total.startswith("| **all** |")
