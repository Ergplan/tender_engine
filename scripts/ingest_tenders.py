"""Management command: ingest the tender set, extract it, and write the extraction summary.

  python -m scripts.ingest_tenders ingest  [--root /work/tenders] [--only slug,slug]
  python -m scripts.ingest_tenders extract [--only slug,slug] [--force]
  python -m scripts.ingest_tenders resume  [--only slug,slug]
  python -m scripts.ingest_tenders wait    [--timeout seconds]
  python -m scripts.ingest_tenders summary [--out docs/reports/EXTRACTION-SUMMARY.md]

`ingest` reads <root>/<type>/<slug>/manifest.yaml, creates each tender, groups its files
into versions and uploads them; the worker parses and section-maps them. `extract` queues
the extraction of every version that has none yet; the worker runs it. Both are safe to
repeat. `resume` puts failed runs back in the queue: a run continues at the first field
group it has no candidates for, so nothing already extracted is paid for twice. `wait`
blocks until the job queue is empty.
"""

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.models import ExtractionRun, Job
from core.services import jobs
from core.services.extract import ExtractService
from core.services.ingest import IngestService
from core.services.review_state import ReviewStateService
from core.storage import make_storage
from tender.services import extraction_summary
from tender.services.packs import Catalog, build_registry
from tender.services.tenders import OBJECT_TYPE, TenderError, TenderService
from tender.services.versioning import CHANGE_ROLES

ACTOR = "ingest_tenders"
DEFAULT_ROOT = Path("/work/tenders")
DEFAULT_SUMMARY = Path("docs/reports/EXTRACTION-SUMMARY.md")


@dataclass(frozen=True)
class ManifestFile:
    path: Path
    role: str
    issued_on: date | None


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
    base = [item for item in manifest.files if item.role not in CHANGE_ROLES]
    dated = [item.issued_on for item in base if item.issued_on is not None]
    first_date = min(dated) if dated else None
    original = [item for item in base if item.issued_on in (None, first_date)]
    if not original:
        raise ValueError(f"{manifest.slug}: no base document for the original version")
    versions = [PlannedVersion("original", first_date, original)]
    order = {id(item): index for index, item in enumerate(manifest.files)}
    later = sorted(
        (item for item in manifest.files if item not in original),
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


def extract(services: Services, only: set[str] | None = None, force: bool = False) -> list[str]:
    """Queue extraction for every version that has no run yet (every version with --force)."""
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
                if has_runs and not force:
                    continue
                try:
                    runs = services.tenders.start_extraction(
                        session, tender, version_no=number, created_by=ACTOR
                    )
                except TenderError as exc:
                    lines.append(f"{tender.slug} v{number}: skipped, {exc}")
                    continue
                groups = sum(len(run.groups or []) for run in runs)
                lines.append(f"{tender.slug} v{number}: {len(runs)} run(s), {groups} group call(s)")
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
        session.commit()
    return lines


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
    parser.add_argument("command", choices=("ingest", "extract", "resume", "wait", "summary"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--only", default="", help="comma-separated tender slugs")
    parser.add_argument("--force", action="store_true", help="extract versions that have runs")
    parser.add_argument("--timeout", type=float, default=6 * 3600)
    parser.add_argument("--out", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args(argv[1:])
    only = {slug.strip() for slug in args.only.split(",") if slug.strip()} or None
    services = build_services()
    if args.command == "ingest":
        print("\n".join(ingest(services, args.root, only)))
    elif args.command == "extract":
        print("\n".join(extract(services, only, args.force)))
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
