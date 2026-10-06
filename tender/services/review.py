"""The review of a tender as the reviewer sees it: one list of fields over all versions.

Core's review state is per object version. A tender is reviewed as a whole: every field
has one entry per version that says something about it (the original always; a later
version only when it gives a value). The entry to decide is the latest one the reviewer
has not set aside as "not in document", so the value under review is the tender's current
one, tagged with the version it comes from.

Completing a review stores the current view as a snapshot; nothing here writes a
canonical fact.
"""

from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.schemas import KeyDef
from core.services import audit
from core.services.review_state import FieldState, ReviewStateService
from tender.models import ReviewToken, Tender, TenderReviewSnapshot
from tender.services.current_view import current_view
from tender.services.packs import Catalog
from tender.services.tenders import OBJECT_TYPE, TenderError, TenderService

VALUE_DECISIONS = ("approved", "edited")


class ReviewDocument(BaseModel):
    document_id: str
    role: str
    filename: str
    page_count: int | None


class ReviewVersion(BaseModel):
    version_no: int
    kind: str
    issued_on: date | None
    documents: list[ReviewDocument]


class ReviewSection(BaseModel):
    name: str
    label: str
    order: int


class ReviewEntry(BaseModel):
    """What one version says about a field: core's field state for that version."""

    version_no: int
    version_kind: str
    state: FieldState


class ReviewField(BaseModel):
    field_path: str
    label: str
    section: str
    value_type: str
    unit: str | None
    required: bool
    help_text: str
    enum_values: list[str] | None
    # The typed keys of a structured field (a record or a list of records).
    keys: list[KeyDef] | None = None
    review_order: int
    entries: list[ReviewEntry]
    # Index in `entries` of the entry to decide; None when no version has a candidate.
    current: int | None
    decided: bool
    flagged: bool


class TenderReview(BaseModel):
    tender_id: str
    tender_type: str
    title: str
    issuing_agency: str
    status: str
    versions: list[ReviewVersion]
    sections: list[ReviewSection]
    fields: list[ReviewField]
    decided: int
    total: int
    required_undecided: int
    can_complete: bool
    # Where the summary stands (tender.services.summary.SummaryState); set by the route.
    summary: dict[str, Any] | None = None


def tender_review(
    session: Session,
    catalog: Catalog,
    tenders: TenderService,
    review_state: ReviewStateService,
    tender: Tender,
) -> TenderReview:
    compiled = catalog.get(tender.tender_type)
    entries: dict[str, list[ReviewEntry]] = {field.path: [] for field in compiled.fields}
    versions: list[ReviewVersion] = []
    for entry in tenders.versions(session, tender):
        version = entry.version
        versions.append(
            ReviewVersion(
                version_no=version.version_no,
                kind=version.kind,
                issued_on=version.issued_on,
                documents=[
                    ReviewDocument(
                        document_id=document.id,
                        role=link.role,
                        filename=document.filename,
                        page_count=document.page_count,
                    )
                    for link, document in entry.documents
                ],
            )
        )
        state = review_state.for_object(session, OBJECT_TYPE, tender.id, version.version_no)
        for state_field in state.fields:
            if state_field.field_path not in entries:
                continue
            candidate = state_field.candidate
            takes_part = (
                candidate is not None
                if version.version_no == 1
                # A later version takes part only where it gives a value, or was decided.
                else (candidate is not None and candidate.value is not None)
                or state_field.approval is not None
            )
            if takes_part:
                entries[state_field.field_path].append(
                    ReviewEntry(
                        version_no=version.version_no,
                        version_kind=version.kind,
                        state=state_field,
                    )
                )
    fields = []
    for field in compiled.fields:
        own = entries[field.path]
        current = _current(own)
        approval = own[current].state.approval if current is not None else None
        fields.append(
            ReviewField(
                field_path=field.path,
                label=field.label,
                section=field.section,
                value_type=field.value_type,
                unit=field.unit,
                required=field.required,
                help_text=field.help_text,
                enum_values=field.enum_values,
                keys=field.keys,
                review_order=field.review_order,
                entries=own,
                current=current,
                decided=approval is not None
                and approval.decision in (*VALUE_DECISIONS, "not_in_document"),
                flagged=approval is not None and approval.decision == "flagged",
            )
        )
    # A required field no version has a candidate for cannot be decided and does not
    # hold the review back (docs/KNOWN-GAPS.md).
    required_undecided = sum(
        1 for f in fields if f.required and not f.decided and f.current is not None
    )
    return TenderReview(
        tender_id=tender.id,
        tender_type=tender.tender_type,
        title=tender.title,
        issuing_agency=tender.issuing_agency,
        status=tender.status,
        versions=versions,
        sections=[
            ReviewSection(name=section.name, label=section.label, order=section.order)
            for section in sorted(compiled.sections, key=lambda s: s.order)
        ],
        fields=fields,
        decided=sum(1 for f in fields if f.decided),
        total=len(fields),
        required_undecided=required_undecided,
        can_complete=required_undecided == 0 and any(f.decided for f in fields),
    )


def _current(entries: list[ReviewEntry]) -> int | None:
    """The entry to decide: the latest one not set aside as "not in document". When every
    entry is set aside, the original, whose decision then stands for the field."""
    if not entries:
        return None
    for index in range(len(entries) - 1, -1, -1):
        approval = entries[index].state.approval
        if approval is None or approval.decision != "not_in_document":
            return index
    return 0


def complete_review(
    session: Session,
    catalog: Catalog,
    tenders: TenderService,
    review_state: ReviewStateService,
    tender: Tender,
    token: ReviewToken,
    *,
    summary_being_written: bool = False,
    summary_waiting_for: int = 0,
) -> TenderReviewSnapshot:
    """Close the review: refuse while a required field is undecided or the summary is
    being written again; then mark the token completed and the tender reviewed, and store
    the current view for the gold set."""
    if token.tender_id != tender.id:
        raise LookupError("the review token belongs to another tender")
    if token.completed_at is not None:
        raise TenderError("this review has already been completed")
    if summary_being_written:
        # Between the new text being stored and being validated the summary field has no
        # entry in review, so it would not count as an undecided required field.
        raise TenderError(
            "the summary is being written again from your decisions; complete the review "
            "once it is ready and decided"
        )
    review = tender_review(session, catalog, tenders, review_state, tender)
    if not review.can_complete:
        raise TenderError(
            f"{review.required_undecided} required field(s) have no decision yet"
            if review.required_undecided
            else "no field has been decided yet"
        )
    if summary_waiting_for:
        # The summary is written from every field: a review is complete only when every
        # field that has a candidate is decided, optional ones too (a decision cleared after
        # the summary was approved reopens the field without changing the record).
        raise TenderError(
            f"{summary_waiting_for} field(s) the summary is written from have no decision yet"
        )
    now = datetime.now(UTC)
    view = current_view(session, catalog, tender)
    snapshot: dict[str, Any] = {
        "tender_id": tender.id,
        "tender_type": tender.tender_type,
        "title": tender.title,
        "issuing_agency": tender.issuing_agency,
        "reviewer": token.reviewer_name,
        "completed_at": now.isoformat(),
        "decided": review.decided,
        "total": review.total,
        "flagged": [f.field_path for f in review.fields if f.flagged],
        "view": view.model_dump(mode="json"),
    }
    row = TenderReviewSnapshot(
        tenant_id=tender.tenant_id,
        created_by=token.reviewer_name,
        tender_id=tender.id,
        review_token_id=token.id,
        reviewer=token.reviewer_name,
        snapshot=snapshot,
    )
    session.add(row)
    token.completed_at = now
    before = tender.status
    tender.status = "reviewed"
    session.flush()
    audit.record(
        session,
        tenant_id=tender.tenant_id,
        actor=token.reviewer_name,
        action="complete_review",
        table_name="tender",
        row_id=tender.id,
        before={"status": before},
        after={"status": "reviewed", "snapshot_id": row.id, "review_token_id": token.id},
    )
    session.commit()
    return row


def latest_snapshot(session: Session, tender: Tender) -> TenderReviewSnapshot | None:
    return session.scalars(
        select(TenderReviewSnapshot)
        .where(
            TenderReviewSnapshot.tenant_id == tender.tenant_id,
            TenderReviewSnapshot.tender_id == tender.id,
        )
        .order_by(TenderReviewSnapshot.created_at.desc())
        .limit(1)
    ).first()
