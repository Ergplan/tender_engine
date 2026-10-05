"""Management command: ingest the tender set, extract it, and write the extraction summary.

  python -m scripts.ingest_tenders ingest  [--root /work/tenders] [--only slug,slug]
  python -m scripts.ingest_tenders extract [--only slug,slug] [--force] [--groups a,b]
  python -m scripts.ingest_tenders amendment-routing [--only slug,slug] [--mode none|missing|union]
  python -m scripts.ingest_tenders routing-report
  python -m scripts.ingest_tenders resume  [--only slug,slug]
  python -m scripts.ingest_tenders wait    [--timeout seconds]
  python -m scripts.ingest_tenders summary [--out docs/reports/EXTRACTION-SUMMARY.md]
  python -m scripts.ingest_tenders cost-plan [--only slug,slug]

`ingest` reads <root>/<type>/<slug>/manifest.yaml, creates each tender, groups its files
into versions and uploads them; the worker parses and section-maps them. `extract` queues
the extraction of every version that has none yet; the worker runs it. Both are safe to
repeat. `resume` puts failed runs back in the queue: a run continues at the first field
group it has no candidates for, so nothing already extracted is paid for twice. `wait`
blocks until the job queue is empty. `extract` goes through the batch API unless `--sync`
is given. `cost-plan` prints, without calling the model, the pages each tender's sections
ask for and the pages that are sent once sections share a window.
"""

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.models import Document, ExtractionRun, Job
from core.services import jobs
from core.services.extract import ExtractService
from core.services.ingest import IngestService
from core.services.review_state import ReviewStateService
from core.storage import make_storage
from tender.services import extraction_summary
from tender.services.amendment_map import routing_records
from tender.services.packs import Catalog, build_registry
from tender.services.tenders import JOB_KIND, OBJECT_TYPE, TenderError, TenderService
from tender.services.versioning import CHANGE_ROLES

ACTOR = "ingest_tenders"
DEFAULT_ROOT = Path("/work/tenders")
DEFAULT_SUMMARY = Path("docs/reports/EXTRACTION-SUMMARY.md")


@dataclass(frozen=True)
class ManifestFile:
    path: Path
    role: str
    issued_on: date | None
    # "latest": the file belongs to the tender's latest version, whatever its date (a
    # published notice shows the dates as they stand after every amendment).
    attach_to: str | None = None


@dataclass(frozen=True)
class PlannedVersion:
    kind: str
    issued_on: date | None
    files: list[ManifestFile]


@dataclass(frozen=True)
class Manifest:
    slug: str
    tender_type: str
    agency: str
    external_ref: str | None
    title: str
    files: list[ManifestFile]


@dataclass(frozen=True)
class Services:
    settings: Settings
    session_factory: sessionmaker[Session]
    catalog: Catalog
    ingest: IngestService
    tenders: TenderService
    review: ReviewStateService
    extract: ExtractService


def build_services(settings: Settings | None = None) -> Services:
    settings = settings or Settings()
    session_factory = make_session_factory(make_engine(settings))
    storage = make_storage(settings)
    schemas, catalog = build_registry()
    llm = LLMClient(settings, session_factory, prompt_roots=catalog.prompt_roots)
    extract = ExtractService(llm, storage, schemas, settings)
    return Services(
        settings=settings,
        session_factory=session_factory,
        catalog=catalog,
        ingest=IngestService(storage, settings.tenant_id),
        tenders=TenderService(catalog, extract, settings.tenant_id),
        review=ReviewStateService(schemas, settings.tenant_id),
        extract=extract,
    )


def read_manifests(root: Path, only: set[str] | None = None) -> list[Manifest]:
    manifests = []
    for path in sorted(root.glob("*/*/manifest.yaml")):
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        if only and raw["slug"] not in only:
            continue
        files = [
            ManifestFile(
                path=path.parent / item["file"],
                role=item["role"],
                issued_on=date.fromisoformat(item["issued_on"]) if item.get("issued_on") else None,
                attach_to=item.get("attach_to"),
            )
            for item in raw["files"]
        ]
        manifests.append(
            Manifest(
                slug=raw["slug"],
                tender_type=raw["type"],
                agency=raw["agency"],
                external_ref=raw.get("external_ref"),
                title=raw["title"],
                files=files,
            )
        )
    return manifests


def plan_versions(manifest: Manifest) -> list[PlannedVersion]:
    """Group a tender's files into versions. The original holds every base document
    (anything that is not an amendment or clarification) that is undated or carries the
    earliest date. Each amendment or clarification after that is its own version, in date
    order; a base document issued later (a revised RfS, a revised annexure) joins the
    version issued on the same date, or becomes an amendment version of its own."""
    dated_files = [item for item in manifest.files if item.attach_to != "latest"]
    base = [item for item in dated_files if item.role not in CHANGE_ROLES]
    dated = [item.issued_on for item in base if item.issued_on is not None]
    first_date = min(dated) if dated else None
    original = [item for item in base if item.issued_on in (None, first_date)]
    if not original:
        raise ValueError(f"{manifest.slug}: no base document for the original version")
    versions = [PlannedVersion("original", first_date, original)]
    order = {id(item): index for index, item in enumerate(manifest.files)}
    later = sorted(
        (item for item in dated_files if item not in original),
        key=lambda item: (
            item.issued_on or date.max,
            item.role not in CHANGE_ROLES,
            order[id(item)],
        ),
    )
    for item in later:
        latest = versions[-1]
        if item.role in CHANGE_ROLES:
            versions.append(PlannedVersion(item.role, item.issued_on, [item]))
        elif latest.kind != "original" and latest.issued_on == item.issued_on:
            latest.files.append(item)
        else:
            versions.append(PlannedVersion("amendment", item.issued_on, [item]))
    versions[-1].files.extend(item for item in manifest.files if item.attach_to == "latest")
    return versions


def ingest(services: Services, root: Path, only: set[str] | None = None) -> list[str]:
    """Create tenders, versions and documents from the manifests. Safe to repeat."""
    lines = []
    with services.session_factory() as session:
        for manifest in read_manifests(root, only):
            tender = services.tenders.by_slug(session, manifest.slug)
            if tender is None:
                tender = services.tenders.create(
                    session,
                    tender_type=manifest.tender_type,
                    issuing_agency=manifest.agency,
                    external_ref=manifest.external_ref,
                    title=manifest.title,
                    created_by=ACTOR,
                    slug=manifest.slug,
                )
            existing = len(services.tenders.versions(session, tender))
            planned = plan_versions(manifest)
            for number, version in enumerate(planned, start=1):
                for index, item in enumerate(version.files):
                    document, _ = services.ingest.upload(
                        session,
                        filename=item.path.name,
                        data=item.path.read_bytes(),
                        created_by=ACTOR,
                    )
                    if number > existing and index == 0:
                        services.tenders.add_version(
                            session,
                            tender,
                            document,
                            version.kind,
                            version.issued_on,
                            created_by=ACTOR,
                            role=item.role,
                        )
                    elif item.role not in CHANGE_ROLES:
                        # The amendment or clarification itself came in with its version.
                        services.tenders.attach_document(
                            session, tender, number, document, item.role, created_by=ACTOR
                        )
            shape = ", ".join(f"v{n}:{len(v.files)}" for n, v in enumerate(planned, start=1))
            lines.append(
                f"{manifest.tender_type}/{manifest.slug}: {len(planned)} version(s) [{shape}]"
            )
    return lines


def extract(
    services: Services,
    only: set[str] | None = None,
    force: bool = False,
    groups: list[str] | None = None,
    run_mode: str = "batch",
) -> list[str]:
    """Queue extraction for every version that has no run yet (every version with --force).
    With `groups`, only those sections are read again, from the documents that are read
    for them. Nobody waits for these runs, so they go through the batch API unless
    `run_mode` is "sync"."""
    lines = []
    with services.session_factory() as session:
        for tender in services.tenders.all(session):
            if only and tender.slug not in only:
                continue
            for entry in services.tenders.versions(session, tender):
                number = entry.version.version_no
                has_runs = session.scalar(
                    select(func.count())
                    .select_from(ExtractionRun)
                    .where(
                        ExtractionRun.tenant_id == services.settings.tenant_id,
                        ExtractionRun.object_type == OBJECT_TYPE,
                        ExtractionRun.object_id == tender.id,
                        ExtractionRun.object_version == number,
                    )
                )
                being_mapped = session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.tenant_id == services.settings.tenant_id,
                        Job.kind == JOB_KIND,
                        Job.status.in_(("queued", "running")),
                        Job.payload["tender_id"].astext == tender.id,
                        Job.payload["version_no"].astext == str(number),
                    )
                )
                if (has_runs or being_mapped) and not force:
                    continue
                try:
                    runs = services.tenders.start_extraction(
                        session,
                        tender,
                        version_no=number,
                        created_by=ACTOR,
                        groups=groups,
                        mode=run_mode,
                    )
                except TenderError as exc:
                    lines.append(f"{tender.slug} v{number}: skipped, {exc}")
                    continue
                calls = sum(len(run.groups or []) for run in runs)
                mapped = "" if runs or entry.version.version_no == 1 else "; mapped first"
                lines.append(
                    f"{tender.slug} v{number}: {len(runs)} run(s), {calls} group call(s){mapped}"
                )
    return lines


def resume(services: Services, only: set[str] | None = None) -> list[str]:
    """Queue every failed tender run again. Extraction commits per field group and skips
    the groups a run already has candidates for, so a resumed run only does what is left."""
    lines = []
    tenant_id = services.settings.tenant_id
    with services.session_factory() as session:
        slugs = {tender.id: tender.slug for tender in services.tenders.all(session)}
        failed = session.scalars(
            select(ExtractionRun)
            .where(
                ExtractionRun.tenant_id == tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.status == "failed",
            )
            .order_by(ExtractionRun.created_at, ExtractionRun.id)
        )
        for run in failed:
            slug = slugs.get(run.object_id)
            if only and slug not in only:
                continue
            run.status = "queued"
            run.error = None
            run.finished_at = None
            jobs.enqueue(
                session,
                tenant_id=tenant_id,
                kind="extract",
                payload={"extraction_run_id": run.id},
                created_by=ACTOR,
            )
            lines.append(f"{slug} v{run.object_version}: run {run.id} queued again")
        # An amendment whose map failed has no run yet: its job is put back instead.
        for job in session.scalars(
            select(Job).where(
                Job.tenant_id == tenant_id, Job.kind == JOB_KIND, Job.status == "failed"
            )
        ):
            slug = slugs.get(job.payload.get("tender_id"))
            if only and slug not in only:
                continue
            job.status = "queued"
            job.attempts = 0
            job.run_after = datetime.now(UTC)
            job.finished_at = None
            lines.append(f"{slug} v{job.payload.get('version_no')}: amendment map queued again")
        session.commit()
    return lines


def amendment_routing(
    services: Services, only: set[str] | None = None, mode: str = "none"
) -> list[str]:
    """Queue the full map of every amending document, to compare it with the keyword
    routing. mode: none (record the comparison only), missing (also read the sections only
    the map found) or union."""
    lines = []
    with services.session_factory() as session:
        for tender in services.tenders.all(session):
            if only and tender.slug not in only:
                continue
            for entry in services.tenders.versions(session, tender):
                for link, document in entry.documents:
                    if link.role not in CHANGE_ROLES or entry.version.version_no == 1:
                        continue
                    jobs.enqueue(
                        session,
                        tenant_id=services.settings.tenant_id,
                        kind=JOB_KIND,
                        payload={
                            "tender_id": tender.id,
                            "version_no": entry.version.version_no,
                            "document_id": document.id,
                            "created_by": ACTOR,
                            "start_runs": mode,
                        },
                        created_by=ACTOR,
                    )
                    lines.append(f"{tender.slug} v{entry.version.version_no}: {document.filename}")
        session.commit()
    return lines


def routing_report(services: Services) -> list[str]:
    """One line per recorded comparison of keyword routing with the full map."""
    lines = []
    with services.session_factory() as session:
        for _, record in routing_records(session, services.settings.tenant_id):
            verdict = "agree" if record["agree"] else "DISAGREE"
            lines.append(
                f"{verdict} | {record['filename']} ({record['pages']} p) | "
                f"keywords only: {record['only_keywords']} | map only: {record['only_map']} | "
                f"both: {[g for g in record['by_keywords'] if g in record['by_map']]}"
            )
    return lines


def cost_plan(services: Services, only: set[str] | None = None) -> list[str]:
    """Per tender, for the sections its documents were last read for: the pages each
    section asks for on its own (what Stage 2 sent), and what is sent when sections share
    a window: pages written to the cache once, pages read from it, pages sent uncached.
    The last column prices the input in uncached pages at the configured factors, for
    direct calls and for a batch run."""
    settings = services.settings
    lines = [
        "| Tender | Calls before | Pages before | Calls | Written | Read from cache | Uncached "
        "| Input, direct | Input, batch |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    totals = [0.0] * 8
    per_call = settings.extract_max_pages_per_call
    with services.session_factory() as session:
        for tender in services.tenders.all(session):
            if only and tender.slug not in only:
                continue
            compiled = services.catalog.get(tender.tender_type)
            row = [0.0] * 8
            runs = session.scalars(
                select(ExtractionRun).where(
                    ExtractionRun.tenant_id == settings.tenant_id,
                    ExtractionRun.object_type == OBJECT_TYPE,
                    ExtractionRun.object_id == tender.id,
                )
            )
            read_for: dict[str, set[str]] = {}
            for run in runs:
                names = run.groups or [group.name for group in compiled.schema.groups]
                read_for.setdefault(run.document_id, set()).update(names)
            for document_id, names in sorted(read_for.items()):
                document = session.scalar(
                    select(Document).where(
                        Document.id == document_id, Document.tenant_id == settings.tenant_id
                    )
                )
                if document is None:
                    continue
                for batch in (False, True):
                    windows, plan = services.extract.plan_windows(
                        session, document, compiled.schema, sorted(names), batch=batch
                    )
                    written = sum(len(w.pages) for w in plan if w.shared)
                    read = sum(len(w.pages) * (len(w.groups) - 1) for w in plan if w.shared)
                    plain = sum(len(w.pages) for w in plan if not w.shared)
                    write_factor = (
                        settings.llm_cache_write_1h_factor
                        if batch
                        else settings.llm_cache_write_factor
                    )
                    priced = (
                        plain + written * write_factor + read * settings.llm_cache_read_factor
                    ) * (settings.llm_batch_factor if batch else 1.0)
                    if batch:
                        row[7] += priced
                        continue
                    row[0] += sum(-(-len(pages) // per_call) for pages in windows.values())
                    row[1] += sum(len(pages) for pages in windows.values())
                    row[2] += sum(-(-len(w.pages) // per_call) * len(w.groups) for w in plan)
                    row[3] += written
                    row[4] += read
                    row[5] += plain
                    row[6] += priced
            totals = [a + b for a, b in zip(totals, row, strict=True)]
            lines.append(_plan_row(tender.slug or tender.title[:40], row))
    lines.append(_plan_row("**all**", totals))
    return lines


def _plan_row(name: str, row: list[float]) -> str:
    cells = [f"{value:,.0f}" for value in row]
    return f"| {name} | " + " | ".join(cells) + " |"


def pending_jobs(services: Services) -> dict[str, int]:
    with services.session_factory() as session:
        rows = session.execute(
            select(Job.status, func.count())
            .where(Job.tenant_id == services.settings.tenant_id)
            .group_by(Job.status)
        ).all()
    return {status: count for status, count in rows}


def wait(services: Services, timeout: float, poll: float = 15.0) -> bool:
    """Block until no job is queued or running. Returns False on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        counts = pending_jobs(services)
        print(f"jobs: {counts}", flush=True)
        if not counts.get("queued") and not counts.get("running"):
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(poll)


def summary(services: Services, out: Path) -> str:
    with services.session_factory() as session:
        for tender in services.tenders.all(session):
            services.tenders.refresh_status(session, tender)
        text = extraction_summary.build(
            session, services.catalog, services.tenders, services.review, services.settings
        ).markdown
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return text


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ingest_tenders", description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "ingest",
            "extract",
            "resume",
            "wait",
            "summary",
            "amendment-routing",
            "routing-report",
            "cost-plan",
        ),
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--only", default="", help="comma-separated tender slugs")
    parser.add_argument("--force", action="store_true", help="extract versions that have runs")
    parser.add_argument("--groups", default="", help="comma-separated sections to read again")
    parser.add_argument("--mode", default="none", choices=("none", "missing", "union"))
    parser.add_argument(
        "--sync", action="store_true", help="extract with direct calls, not the batch API"
    )
    parser.add_argument("--timeout", type=float, default=6 * 3600)
    parser.add_argument("--out", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args(argv[1:])
    only = {slug.strip() for slug in args.only.split(",") if slug.strip()} or None
    services = build_services()
    if args.command == "ingest":
        print("\n".join(ingest(services, args.root, only)))
    elif args.command == "extract":
        groups = [name.strip() for name in args.groups.split(",") if name.strip()] or None
        run_mode = "sync" if args.sync else "batch"
        print("\n".join(extract(services, only, args.force, groups, run_mode)))
    elif args.command == "amendment-routing":
        print("\n".join(amendment_routing(services, only, args.mode)))
    elif args.command == "routing-report":
        print("\n".join(routing_report(services)))
    elif args.command == "cost-plan":
        print("\n".join(cost_plan(services, only)))
    elif args.command == "resume":
        print("\n".join(resume(services, only)))
    elif args.command == "wait":
        return 0 if wait(services, args.timeout) else 1
    else:
        summary(services, args.out)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
