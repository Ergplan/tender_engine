"""ApprovalService: the only code path that writes canonical_fact.

A reviewer's decision on a candidate creates an approval row; the candidate itself is
never changed. The difference between candidate and final value is stored as feedback.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models import Approval, Candidate, CanonicalFact, EvidenceSpan, ExtractionRun, Feedback
from core.models.truth import DECISIONS
from core.schemas import FieldDef, SchemaRegistry
from core.services import audit

DECIDABLE_STATUSES = ("validated", "needs_review", "not_found")
FACT_DECISIONS = ("approved", "edited", "not_in_document")


class ApprovalError(ValueError):
    """The decision cannot be recorded as asked. The message is safe to show a reviewer."""


@dataclass(frozen=True)
class ApprovalOutcome:
    approval: Approval
    canonical_fact: CanonicalFact | None
    feedback: Feedback | None
    created: bool


class ApprovalService:
    def __init__(self, schemas: SchemaRegistry, tenant_id: str) -> None:
        self._schemas = schemas
        self._tenant_id = tenant_id

    def approve(
        self,
        session: Session,
        *,
        candidate_id: str,
        decision: str,
        final_value: Any = None,
        reviewer: str,
        note: str | None = None,
    ) -> ApprovalOutcome:
        """Record a human decision. Idempotent: an identical repeat writes nothing."""
        if decision not in DECISIONS:
            raise ApprovalError(f"unknown decision {decision!r}")
        if not reviewer.strip():
            raise ApprovalError("a reviewer name is required")
        row = session.execute(
            select(Candidate, ExtractionRun)
            .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
            .where(Candidate.id == candidate_id, Candidate.tenant_id == self._tenant_id)
            .with_for_update(of=Candidate)
            # The row lock is only useful if the locked values are read from the database,
            # not from objects this session loaded earlier.
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None:
            raise LookupError(f"candidate {candidate_id} not found")
        candidate, run = row
        if candidate.status not in DECIDABLE_STATUSES:
            raise ApprovalError(f"a {candidate.status} candidate cannot be decided")
        field = self._schemas.get(run.schema_name, run.schema_version).field(candidate.field_path)

        candidate_value: Any = None
        if candidate.value is not None:
            try:
                candidate_value = self._schemas.value_types.coerce(candidate.value, field)
            except ValueError:
                candidate_value = None
        if decision == "approved":
            if candidate.value is None:
                raise ApprovalError("there is no value to approve; edit it or mark it not found")
            if candidate_value is None:
                raise ApprovalError(
                    f"the value is not a valid {field.value_type}; edit it before approving"
                )
            if final_value is not None and self._coerced(final_value, field) != candidate_value:
                raise ApprovalError("an approval cannot change the value; use decision 'edited'")
            final: Any = candidate_value
        elif decision == "edited":
            if final_value is None:
                raise ApprovalError("an edit needs a value")
            try:
                final = self._schemas.value_types.coerce(final_value, field)
            except ValueError as exc:
                raise ApprovalError(f"not a valid {field.value_type}: {exc}") from exc
        else:
            if final_value is not None:
                raise ApprovalError(f"decision {decision!r} does not take a value")
            final = None
        note = note.strip() if note and note.strip() else None

        current = session.scalar(
            select(Approval)
            .where(
                Approval.tenant_id == self._tenant_id,
                Approval.object_type == run.object_type,
                Approval.object_id == run.object_id,
                Approval.object_version == run.object_version,
                Approval.field_path == candidate.field_path,
                Approval.status == "active",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current is not None and (
            current.candidate_id,
            current.decision,
            current.final_value,
            current.reviewer,
            current.note,
        ) == (candidate.id, decision, final, reviewer, note):
            existing_fact = session.scalar(
                select(CanonicalFact).where(
                    CanonicalFact.approval_id == current.id,
                    CanonicalFact.tenant_id == self._tenant_id,
                )
            )
            session.rollback()
            return ApprovalOutcome(current, existing_fact, None, created=False)

        now = datetime.now(UTC)
        if current is not None:
            self._supersede(session, current, reviewer, now)

        approval = Approval(
            tenant_id=self._tenant_id,
            created_by=reviewer,
            candidate_id=candidate.id,
            object_type=run.object_type,
            object_id=run.object_id,
            object_version=run.object_version,
            field_path=candidate.field_path,
            final_value=final,
            decision=decision,
            reviewer=reviewer,
            note=note,
            decided_at=now,
            status="active",
            supersedes_approval_id=current.id if current else None,
        )
        session.add(approval)
        try:
            session.flush()
        except IntegrityError as exc:
            # Two first decisions on one field at the same moment: the unique index lets
            # one through. Nothing of this request has been written.
            session.rollback()
            raise ApprovalError(
                "another decision on this field was recorded at the same moment; reload"
            ) from exc
        self._audit(session, reviewer, "insert", "approval", approval.id, after=_dump(approval))

        fact: CanonicalFact | None = None
        if decision in FACT_DECISIONS:
            fact = CanonicalFact(
                tenant_id=self._tenant_id,
                created_by=reviewer,
                object_type=run.object_type,
                object_id=run.object_id,
                object_version=run.object_version,
                field_path=candidate.field_path,
                value=final,
                value_type=field.value_type,
                approval_id=approval.id,
                evidence=self._evidence(session, candidate, decision, reviewer, note),
                effective_at=now,
                is_current=True,
            )
            session.add(fact)
            session.flush()
            self._audit(
                session,
                reviewer,
                "insert",
                "canonical_fact",
                fact.id,
                after={
                    "field_path": fact.field_path,
                    "value": fact.value,
                    "approval_id": approval.id,
                    "object": [fact.object_type, fact.object_id, fact.object_version],
                },
            )

        feedback: Feedback | None = None
        delta = classify_delta(decision, candidate.value, candidate_value, final)
        if delta is not None:
            feedback = Feedback(
                tenant_id=self._tenant_id,
                created_by=reviewer,
                approval_id=approval.id,
                field_path=candidate.field_path,
                candidate_value=candidate.value,
                final_value=final,
                delta_kind=delta,
                reviewer=reviewer,
                prompt_version=candidate.prompt_version,
            )
            session.add(feedback)
            session.flush()
            self._audit(
                session,
                reviewer,
                "insert",
                "feedback",
                feedback.id,
                after={"field_path": feedback.field_path, "delta_kind": delta},
            )
        session.commit()
        return ApprovalOutcome(approval, fact, feedback, created=True)

    def _supersede(self, session: Session, current: Approval, reviewer: str, now: datetime) -> None:
        current.status = "superseded"
        self._audit(
            session,
            reviewer,
            "supersede",
            "approval",
            current.id,
            before={"status": "active"},
            after={"status": "superseded"},
        )
        for fact in session.scalars(
            select(CanonicalFact).where(
                CanonicalFact.approval_id == current.id,
                CanonicalFact.tenant_id == self._tenant_id,
                CanonicalFact.is_current.is_(True),
            )
        ):
            fact.is_current = False
            fact.superseded_at = now
            self._audit(
                session,
                reviewer,
                "supersede",
                "canonical_fact",
                fact.id,
                before={"is_current": True},
                after={"is_current": False},
            )
        # The earlier decision must be closed in the database before the new one is
        # inserted, or the one-active-per-field index would refuse the insert.
        session.flush()

    def _evidence(
        self, session: Session, candidate: Candidate, decision: str, reviewer: str, note: str | None
    ) -> list[dict[str, Any]]:
        """Evidence copied from the candidate, plus the reviewer's edit if there was one."""
        evidence: list[dict[str, Any]] = [
            {
                "kind": "span",
                "evidence_span_id": span.id,
                "document_id": span.document_id,
                "page_no": span.page_no,
                "bbox": span.bbox,
                "char_start": span.char_start,
                "char_end": span.char_end,
                "quote": span.quote,
            }
            for span in session.scalars(
                select(EvidenceSpan)
                .where(
                    EvidenceSpan.candidate_id == candidate.id,
                    EvidenceSpan.tenant_id == self._tenant_id,
                )
                .order_by(EvidenceSpan.page_no, EvidenceSpan.id)
            )
        ]
        if decision != "approved":
            evidence.append(
                {
                    "kind": "reviewer_decision",
                    "decision": decision,
                    "reviewer": reviewer,
                    "note": note,
                }
            )
        return evidence

    def _coerced(self, value: Any, field: FieldDef) -> Any:
        """The value in the field's type, or the value itself when it is not of that type."""
        try:
            return self._schemas.value_types.coerce(value, field)
        except ValueError:
            return value

    def _audit(
        self,
        session: Session,
        actor: str,
        action: str,
        table_name: str,
        row_id: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        audit.record(
            session,
            tenant_id=self._tenant_id,
            actor=actor,
            action=action,
            table_name=table_name,
            row_id=row_id,
            before=before,
            after=after,
        )


def classify_delta(decision: str, raw_candidate: Any, candidate: Any, final: Any) -> str | None:
    """How the reviewer's final value differs from the candidate, or None when it does not.

    missing: the model had no value and the reviewer supplied one.
    extra: the model had a value and the reviewer says the document has none.
    format: same value, different form. wrong_value: a different value, or a rejection.
    """
    if decision == "rejected":
        return "wrong_value"
    if raw_candidate is None:
        return None if final is None else "missing"
    if final is None:
        return "extra"
    if candidate is not None and candidate == final:
        return None
    if _loose(raw_candidate) == _loose(final) or _loose(candidate) == _loose(final):
        return "format"
    return "wrong_value"


def _loose(value: Any) -> str:
    """Case, whitespace and punctuation removed; numbers compared by value."""
    if isinstance(value, bool) or value is None:
        return repr(value)
    if isinstance(value, int | float):
        return repr(float(value))
    if isinstance(value, list):
        return "|".join(_loose(item) for item in value)
    text = str(value)
    stripped = text.replace(",", "").strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
        return repr(float(stripped))
    return re.sub(r"[\W_]+", "", text.casefold())


def _dump(approval: Approval) -> dict[str, Any]:
    return {
        "candidate_id": approval.candidate_id,
        "field_path": approval.field_path,
        "decision": approval.decision,
        "final_value": approval.final_value,
        "reviewer": approval.reviewer,
        "note": approval.note,
        "object": [approval.object_type, approval.object_id, approval.object_version],
        "supersedes_approval_id": approval.supersedes_approval_id,
    }
