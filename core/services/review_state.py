"""ReviewStateService: the one read model the reviewer UI uses.

For an object, every schema field with its best candidate, that candidate's evidence and
validation results, and the active approval if there is one.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import (
    Approval,
    Candidate,
    CanonicalFact,
    EvidenceSpan,
    ExtractionRun,
    ValidationResult,
)
from core.models.extraction import REVIEWABLE_STATUSES
from core.schemas import SchemaRegistry

DECIDED = ("approved", "edited", "not_in_document")


class EvidenceView(BaseModel):
    id: str
    document_id: str
    page_no: int
    bbox: list[float] | None
    char_start: int | None
    char_end: int | None
    quote: str
    resolution: str
    match_score: float | None


class ValidationView(BaseModel):
    rule_name: str
    passed: bool
    message: str


class CandidateView(BaseModel):
    id: str
    value: Any
    confidence: float
    rationale: str
    status: str
    prompt_name: str
    prompt_version: str
    evidence: list[EvidenceView]
    validation: list[ValidationView]


class ApprovalView(BaseModel):
    id: str
    candidate_id: str
    decision: str
    final_value: Any
    reviewer: str
    note: str | None
    decided_at: datetime


class FieldState(BaseModel):
    field_path: str
    label: str
    group: str
    value_type: str
    unit: str | None
    required: bool
    help_text: str
    enum_values: list[str] | None
    review_order: int
    candidate: CandidateView | None
    alternative_candidates: int
    approval: ApprovalView | None


class RunView(BaseModel):
    id: str
    document_id: str
    schema_name: str
    schema_version: str
    prompt_version: str
    model: str
    status: str


class ReviewState(BaseModel):
    object_type: str
    object_id: str
    object_version: int
    run: RunView | None
    fields: list[FieldState]
    decided: int
    total: int
    required_undecided: int


class CanonicalFactView(BaseModel):
    id: str
    object_type: str
    object_id: str
    object_version: int
    field_path: str
    value: Any
    value_type: str
    approval_id: str
    evidence: list[dict[str, Any]]
    effective_at: datetime
    created_by: str


class ReviewStateService:
    def __init__(self, schemas: SchemaRegistry, tenant_id: str) -> None:
        self._schemas = schemas
        self._tenant_id = tenant_id

    def for_object(
        self, session: Session, object_type: str, object_id: str, version: int | None = None
    ) -> ReviewState:
        """State from the latest extraction run of the object (latest version by default)."""
        query = select(ExtractionRun).where(
            ExtractionRun.tenant_id == self._tenant_id,
            ExtractionRun.object_type == object_type,
            ExtractionRun.object_id == object_id,
        )
        if version is not None:
            query = query.where(ExtractionRun.object_version == version)
        run = session.scalar(
            query.order_by(
                ExtractionRun.object_version.desc(),
                ExtractionRun.created_at.desc(),
                ExtractionRun.id.desc(),
            ).limit(1)
        )
        if run is None:
            return ReviewState(
                object_type=object_type,
                object_id=object_id,
                object_version=version or 1,
                run=None,
                fields=[],
                decided=0,
                total=0,
                required_undecided=0,
            )
        schema = self._schemas.get(run.schema_name, run.schema_version)
        candidates = list(
            session.scalars(
                select(Candidate).where(
                    Candidate.tenant_id == self._tenant_id, Candidate.extraction_run_id == run.id
                )
            )
        )
        ids = [candidate.id for candidate in candidates]
        evidence: dict[str, list[EvidenceView]] = {cid: [] for cid in ids}
        for span in session.scalars(
            select(EvidenceSpan)
            .where(EvidenceSpan.tenant_id == self._tenant_id, EvidenceSpan.candidate_id.in_(ids))
            .order_by(EvidenceSpan.page_no, EvidenceSpan.id)
        ):
            evidence[span.candidate_id].append(
                EvidenceView.model_validate(span, from_attributes=True)
            )
        validation: dict[str, list[ValidationView]] = {cid: [] for cid in ids}
        for result in session.scalars(
            select(ValidationResult)
            .where(
                ValidationResult.tenant_id == self._tenant_id,
                ValidationResult.candidate_id.in_(ids),
            )
            .order_by(ValidationResult.rule_name)
        ):
            validation[result.candidate_id].append(
                ValidationView.model_validate(result, from_attributes=True)
            )
        approvals = {
            approval.field_path: approval
            for approval in session.scalars(
                select(Approval).where(
                    Approval.tenant_id == self._tenant_id,
                    Approval.object_type == run.object_type,
                    Approval.object_id == run.object_id,
                    Approval.object_version == run.object_version,
                    Approval.status == "active",
                )
            )
        }

        fields: list[FieldState] = []
        for field in sorted(schema.fields, key=lambda f: (f.review_order, f.path)):
            own = [c for c in candidates if c.field_path == field.path]
            reviewable = [c for c in own if c.status in REVIEWABLE_STATUSES]
            best = _best(reviewable, evidence) or next(
                (c for c in own if c.status == "not_found"), None
            )
            approval = approvals.get(field.path)
            fields.append(
                FieldState(
                    field_path=field.path,
                    label=field.label,
                    group=field.group,
                    value_type=field.value_type,
                    unit=field.unit,
                    required=field.required,
                    help_text=field.help_text,
                    enum_values=field.enum_values,
                    review_order=field.review_order,
                    candidate=None
                    if best is None
                    else CandidateView(
                        id=best.id,
                        value=best.value,
                        confidence=best.confidence,
                        rationale=best.rationale,
                        status=best.status,
                        prompt_name=best.prompt_name,
                        prompt_version=best.prompt_version,
                        evidence=evidence[best.id],
                        validation=validation[best.id],
                    ),
                    alternative_candidates=max(len(reviewable) - 1, 0),
                    approval=None
                    if approval is None
                    else ApprovalView.model_validate(approval, from_attributes=True),
                )
            )
        decided = sum(1 for f in fields if f.approval and f.approval.decision in DECIDED)
        return ReviewState(
            object_type=run.object_type,
            object_id=run.object_id,
            object_version=run.object_version,
            run=RunView.model_validate(run, from_attributes=True),
            fields=fields,
            decided=decided,
            total=len(fields),
            required_undecided=sum(
                1
                for f in fields
                if f.required and not (f.approval and f.approval.decision in DECIDED)
            ),
        )

    def canonical(
        self, session: Session, object_type: str, object_id: str, version: int | None = None
    ) -> list[CanonicalFactView]:
        """Current canonical facts of an object, optionally for one version."""
        query = select(CanonicalFact).where(
            CanonicalFact.tenant_id == self._tenant_id,
            CanonicalFact.object_type == object_type,
            CanonicalFact.object_id == object_id,
            CanonicalFact.is_current.is_(True),
        )
        if version is not None:
            query = query.where(CanonicalFact.object_version == version)
        return [
            CanonicalFactView.model_validate(fact, from_attributes=True)
            for fact in session.scalars(
                query.order_by(CanonicalFact.object_version, CanonicalFact.field_path)
            )
        ]


def _best(candidates: list[Candidate], evidence: dict[str, list[EvidenceView]]) -> Candidate | None:
    """Prefer a candidate that passed validation, then located evidence, then confidence."""
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda c: (
            c.status == "validated",
            any(span.char_start is not None for span in evidence[c.id]),
            c.confidence,
            c.id,
        ),
    )
