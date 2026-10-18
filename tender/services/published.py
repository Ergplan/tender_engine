"""The published view of a tender (Stage 5C): canonical facts only, each with the version
that set it, its evidence pages, the review date and the reviewer's role. Never a
candidate. A field without a fact is a marked gap with its reason and the likely page,
never a blank. The tender document is the authoritative source; this is a reviewed
reading of it, and every response says so.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Approval, AppUser, Candidate, Document, EvidenceSpan, ExtractionRun
from core.models.extraction import REVIEWABLE_STATUSES
from evals.runner import RESULTS_ROOT
from tender.models import Tender, TenderVersion
from tender.services.current_view import current_view
from tender.services.packs import Catalog
from tender.services.publication import PublicationState, publication_state
from tender.services.review import latest_snapshot
from tender.services.summary import SUMMARY_FIELD
from tender.services.tenders import OBJECT_TYPE

AUTHORITY_NOTE = (
    "The tender document is the authoritative source; this is jouleWise's reviewed reading of it."
)
FieldStatus = Literal["reviewed", "not_reviewed", "possibly_superseded"]
DEFAULT_ROLE = "reviewer"


class Evidence(BaseModel):
    document_id: str
    filename: str | None
    page_no: int
    quote: str


class Gap(BaseModel):
    """The designed empty state: why there is no value, and where it likely is."""

    reason: str
    document_id: str | None = None
    likely_page: int | None = None


class PublishedField(BaseModel):
    path: str
    section: str
    label: str
    value_type: str
    unit: str | None
    value: Any = None
    version_no: int | None = None
    # The kind of the version that set the value (original, amendment, ...).
    set_by: str | None = None
    evidence: list[Evidence] = []
    reviewed_at: datetime | None = None
    reviewer_role: str | None = None
    withdrawn: bool = False
    withdrawn_from_version: int | None = None
    status: FieldStatus
    gap: Gap | None = None


class PublishedSection(BaseModel):
    name: str
    label: str
    fields: list[PublishedField]


class Reliability(BaseModel):
    tender_type: str
    value_accuracy: float | None
    evidence_accuracy: float | None
    n_fields: int
    as_of: str | None


class Suspension(BaseModel):
    fields: list[str]
    document_ids: list[str]
    version_no: int
    kind: str
    issued_on: str | None


class PublishedTender(BaseModel):
    tender_id: str
    slug: str | None
    title: str
    issuing_agency: str
    tender_type: str
    external_ref: str | None
    publication: PublicationState
    banner: str | None
    reviewed_at: datetime | None
    reviewer_role: str | None
    reviewed_version: int | None
    current_version: int | None
    sections: list[PublishedSection]
    suspension: Suspension | None
    reliability: Reliability | None
    authority_note: str = AUTHORITY_NOTE


def reviewer_roles(session: Session, tenant_id: str, reviewers: set[str]) -> dict[str, str]:
    """The role of each reviewer who is a user of the tenant; others are `reviewer`."""
    if not reviewers:
        return {}
    rows = session.execute(
        select(AppUser.email, AppUser.role).where(
            AppUser.tenant_id == tenant_id,
            func.lower(AppUser.email).in_([r.lower() for r in reviewers]),
        )
    )
    by_email = {email.lower(): role for email, role in rows}
    return {r: by_email.get(r.lower(), DEFAULT_ROLE) for r in reviewers}


def reliability_of(
    tenant_id: str, tender_type: str, results_root: Path | None = None
) -> Reliability | None:
    """The type's figures from the latest plain evaluation (`make eval`), or None."""
    root = results_root or RESULTS_ROOT
    latest: dict[str, Any] | None = None
    for path in sorted(root.glob("*-latest*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("tenant_id") == tenant_id and not data.get("prompt"):
            latest = data
    if latest is None:
        return None
    by_type = (latest.get("summary") or {}).get("by_type") or {}
    figures = by_type.get(tender_type)
    if not figures:
        return Reliability(
            tender_type=tender_type,
            value_accuracy=None,
            evidence_accuracy=None,
            n_fields=0,
            as_of=latest.get("made_at"),
        )
    return Reliability(
        tender_type=tender_type,
        value_accuracy=figures.get("accuracy"),
        evidence_accuracy=figures.get("evidence_accuracy"),
        n_fields=int(figures.get("n") or 0),
        as_of=latest.get("made_at"),
    )


def _likely_pages(session: Session, tender: Tender) -> dict[str, tuple[str, int]]:
    """Per field without a fact, the page a live reading cites: the gap's pointer. Only
    the page and the document, never the reading's value."""
    rows = session.execute(
        select(Candidate.field_path, EvidenceSpan.document_id, EvidenceSpan.page_no)
        .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
        .join(EvidenceSpan, EvidenceSpan.candidate_id == Candidate.id)
        .where(
            Candidate.tenant_id == tender.tenant_id,
            ExtractionRun.tenant_id == tender.tenant_id,
            ExtractionRun.object_type == OBJECT_TYPE,
            ExtractionRun.object_id == tender.id,
            Candidate.status.in_(REVIEWABLE_STATUSES),
            EvidenceSpan.char_start.is_not(None),
        )
        .order_by(ExtractionRun.object_version.desc(), EvidenceSpan.ordinal)
    )
    found: dict[str, tuple[str, int]] = {}
    for path, document_id, page_no in rows:
        found.setdefault(path, (document_id, page_no))
    return found


def published_tender(
    session: Session,
    catalog: Catalog,
    tender: Tender,
    *,
    results_root: Path | None = None,
) -> PublishedTender:
    compiled = catalog.get(tender.tender_type)
    state = publication_state(session, catalog, tender)
    snapshot = latest_snapshot(session, tender)
    reviewed_at = snapshot.created_at if snapshot else None
    roles = reviewer_roles(session, tender.tenant_id, {snapshot.reviewer} if snapshot else set())
    banner = _banner(state)
    reliability = reliability_of(tender.tenant_id, tender.tender_type, results_root)
    common = dict(
        tender_id=tender.id,
        slug=tender.slug,
        title=tender.title,
        issuing_agency=tender.issuing_agency,
        tender_type=tender.tender_type,
        external_ref=tender.external_ref,
        publication=state,
        banner=banner,
        reviewed_at=reviewed_at,
        reviewer_role=roles.get(snapshot.reviewer) if snapshot else None,
        reviewed_version=state.reviewed_version,
        current_version=state.current_version,
        reliability=reliability,
    )
    if state.state == "publication_suspended":
        assert state.unreviewed_version is not None
        return PublishedTender(
            **common,
            sections=[],
            suspension=Suspension(
                fields=state.suspended_by,
                document_ids=state.unreviewed_version.document_ids,
                version_no=state.unreviewed_version.version_no,
                kind=state.unreviewed_version.kind,
                issued_on=(
                    state.unreviewed_version.issued_on.isoformat()
                    if state.unreviewed_version.issued_on
                    else None
                ),
            ),
        )
    if state.state == "not_published":
        return PublishedTender(**common, sections=[], suspension=None)

    view = current_view(session, catalog, tender)
    kinds = {
        version_no: kind
        for version_no, kind in session.execute(
            select(TenderVersion.version_no, TenderVersion.kind).where(
                TenderVersion.tender_id == tender.id, TenderVersion.tenant_id == tender.tenant_id
            )
        )
    }
    approvals = {
        row.id: row
        for row in session.scalars(
            select(Approval).where(
                Approval.tenant_id == tender.tenant_id,
                Approval.id.in_([f.approval_id for f in view.fields if f.approval_id]),
            )
        )
    }
    roles = reviewer_roles(
        session,
        tender.tenant_id,
        {a.reviewer for a in approvals.values()} | ({snapshot.reviewer} if snapshot else set()),
    )
    filenames = {
        document_id: filename
        for document_id, filename in session.execute(
            select(Document.id, Document.filename).where(Document.tenant_id == tender.tenant_id)
        )
    }
    likely = _likely_pages(session, tender)
    superseded = set(state.possibly_superseded)
    derived = {section.name for section in compiled.sections if section.derived}
    by_section: dict[str, list[PublishedField]] = {}
    for field in view.fields:
        if field.field_path == SUMMARY_FIELD or field.section in derived:
            continue
        approval = approvals.get(field.approval_id) if field.approval_id else None
        if not field.decided:
            pointer = likely.get(field.field_path)
            published = PublishedField(
                path=field.field_path,
                section=field.section,
                label=field.label,
                value_type=field.value_type,
                unit=field.unit,
                status="not_reviewed",
                gap=Gap(
                    reason="not reviewed: no decision on this field yet",
                    document_id=pointer[0] if pointer else None,
                    likely_page=pointer[1] if pointer else None,
                ),
            )
        else:
            gap = None
            if field.withdrawn:
                gap = Gap(reason=f"withdrawn by version {field.version_no}")
            elif field.value is None:
                gap = Gap(reason="reviewed: the document does not state it")
            published = PublishedField(
                path=field.field_path,
                section=field.section,
                label=field.label,
                value_type=field.value_type,
                unit=field.unit,
                value=field.value,
                version_no=field.version_no,
                set_by=kinds.get(field.version_no) if field.version_no else None,
                evidence=[
                    Evidence(
                        document_id=str(item.get("document_id")),
                        filename=filenames.get(str(item.get("document_id"))),
                        page_no=int(item.get("page_no") or 0),
                        quote=str(item.get("quote") or ""),
                    )
                    for item in field.evidence
                    if item.get("document_id") and item.get("page_no")
                ],
                reviewed_at=approval.decided_at if approval else field.effective_at,
                reviewer_role=roles.get(approval.reviewer, DEFAULT_ROLE) if approval else None,
                withdrawn=field.withdrawn,
                withdrawn_from_version=field.withdrawn_from_version,
                status="possibly_superseded" if field.field_path in superseded else "reviewed",
                gap=gap,
            )
        by_section.setdefault(field.section, []).append(published)
    sections = [
        PublishedSection(name=section.name, label=section.label, fields=by_section[section.name])
        for section in compiled.sections
        if section.name in by_section
    ]
    return PublishedTender(**common, sections=sections, suspension=None)


def _banner(state: PublicationState) -> str | None:
    unreviewed = state.unreviewed_version
    if state.state == "not_published":
        return "Not published: this tender has no completed review."
    if unreviewed is None:
        return None
    issued = f", issued {unreviewed.issued_on.isoformat()}" if unreviewed.issued_on else ""
    if state.state == "update_pending":
        return (
            f"Update pending: version {unreviewed.version_no} ({unreviewed.kind}{issued}) is not "
            f"yet reviewed; the fields it may touch are marked possibly superseded."
        )
    return (
        f"Publication suspended: version {unreviewed.version_no} ({unreviewed.kind}{issued}) is "
        f"not yet reviewed and touches {', '.join(state.suspended_by)}; see the amending document."
    )
