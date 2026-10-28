"""Extraction status of a tender for any caller (Stage 7, Block 6 a): per version, its
documents and where each stands (uploaded, parsed, failed), its runs (queued, running,
validated, failed), the jobs still pending for it, and the tender's review and publication
state. Read only."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import ExtractionRun, Job
from core.models.extraction import RECORD_MODES
from tender.models import Tender
from tender.services.packs import Catalog
from tender.services.publication import publication_state
from tender.services.tenders import OBJECT_TYPE, TenderService

Stage = Literal["submitted", "parsing", "mapping", "extracting", "validated", "failed"]
MAPPING_JOBS = {"section_map", "amendment_plan", "classify_type"}
READING_JOBS = {"tender_extract", "extract", "validate", "tender_summary", "tender_derive"}


class DocumentStatus(BaseModel):
    document_id: str
    filename: str
    role: str
    status: str
    pages: int | None
    error: str | None = None


class RunStatus(BaseModel):
    run_id: str
    document_id: str
    mode: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None = None


class VersionStatus(BaseModel):
    version_no: int
    kind: str
    issued_on: date | None
    stage: Stage
    documents: list[DocumentStatus]
    runs: list[RunStatus]
    pending_jobs: list[str]


class TenderStatus(BaseModel):
    tender_id: str
    slug: str | None
    status: str
    tender_type: str
    type_state: str
    type_confidence: float | None
    current_version: int | None
    reviewed_version: int | None
    publication: str
    versions: list[VersionStatus]
    extraction_done: bool


def tender_status(
    session: Session, catalog: Catalog, tenders: TenderService, tender: Tender
) -> TenderStatus:
    tenders.refresh_status(session, tender)
    entries = tenders.versions(session, tender)
    runs = list(
        session.scalars(
            select(ExtractionRun).where(
                ExtractionRun.tenant_id == tender.tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.object_id == tender.id,
            )
        )
    )
    run_ids = {r.id for r in runs}
    document_ids = {d.id for e in entries for _, d in e.documents}
    pending = [
        job
        for job in session.scalars(
            select(Job).where(
                Job.tenant_id == tender.tenant_id, Job.status.in_(("queued", "running"))
            )
        )
        if _concerns(job.payload, tender.id, document_ids, run_ids)
    ]
    versions: list[VersionStatus] = []
    for entry in entries:
        number = entry.version.version_no
        docs = [
            DocumentStatus(
                document_id=d.id,
                filename=d.filename,
                role=link.role,
                status=d.status,
                pages=d.page_count,
                error=d.error,
            )
            for link, d in entry.documents
        ]
        own_runs = [r for r in runs if r.object_version == number and r.mode not in RECORD_MODES]
        own_ids = {d.document_id for d in docs}
        own_jobs = [
            j
            for j in pending
            if j.payload.get("document_id") in own_ids
            or str(j.payload.get("version_no")) == str(number)
            or any(r.id == j.payload.get("extraction_run_id") for r in own_runs)
        ]
        versions.append(
            VersionStatus(
                version_no=number,
                kind=entry.version.kind,
                issued_on=entry.version.issued_on,
                stage=stage_of(
                    [d.status for d in docs],
                    [r.status for r in own_runs],
                    {j.kind for j in own_jobs},
                ),
                documents=docs,
                runs=[
                    RunStatus(
                        run_id=r.id,
                        document_id=r.document_id,
                        mode=r.mode,
                        status=r.status,
                        started_at=r.started_at,
                        finished_at=r.finished_at,
                        error=r.error,
                    )
                    for r in own_runs
                ],
                pending_jobs=sorted({j.kind for j in own_jobs}),
            )
        )
    publication = publication_state(session, catalog, tender)
    return TenderStatus(
        tender_id=tender.id,
        slug=tender.slug,
        status=tender.status,
        tender_type=tender.tender_type,
        type_state=tender.type_state,
        type_confidence=tender.type_confidence,
        current_version=publication.current_version,
        reviewed_version=publication.reviewed_version,
        publication=publication.state,
        versions=versions,
        extraction_done=bool(versions) and all(v.stage == "validated" for v in versions),
    )


def _concerns(
    payload: dict[str, Any], tender_id: str, document_ids: set[str], run_ids: set[str]
) -> bool:
    return (
        payload.get("tender_id") == tender_id
        or payload.get("document_id") in document_ids
        or payload.get("extraction_run_id") in run_ids
    )


def stage_of(document_statuses: list[str], run_statuses: list[str], job_kinds: set[str]) -> Stage:
    """Where a version stands, from its documents, its runs and the jobs pending on it."""
    if "failed" in document_statuses or "failed" in run_statuses:
        return "failed"
    if any(status != "parsed" for status in document_statuses):
        return "parsing"
    if job_kinds & MAPPING_JOBS:
        return "mapping"
    if (
        run_statuses
        and all(s == "validated" for s in run_statuses)
        and not job_kinds & READING_JOBS
    ):
        return "validated"
    if run_statuses or job_kinds & READING_JOBS:
        return "extracting"
    return "submitted"
