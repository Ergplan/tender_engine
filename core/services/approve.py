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

from core.evidence import PageText, locate
from core.models import (
    Approval,
    Candidate,
    CanonicalFact,
    EvidenceSpan,
    ExtractionRun,
    Feedback,
    Page,
)
from core.models.truth import DECISIONS
from core.schemas import FieldDef, SchemaRegistry
from core.services import audit

DECIDABLE_STATUSES = ("validated", "needs_review", "not_found")
FACT_DECISIONS = ("approved", "edited", "not_in_document")


class ApprovalError(ValueError):
    """The decision cannot be recorded as asked. The message is safe to show a reviewer."""


class StaleDecisionError(ApprovalError):
    """The field was decided by someone else, or again, since the caller last read it."""


# Passed as `previous_approval_id` by a caller that does not check for a stale write.
UNCHECKED = "unchecked"


@dataclass(frozen=True)
class ApprovalOutcome:
    approval: Approval
    canonical_fact: CanonicalFact | None
    feedback: Feedback | None
    created: bool


class ApprovalService:
    def __init__(
        self, schemas: SchemaRegistry, tenant_id: str, evidence_match_threshold: float = 85.0
    ) -> None:
        self._schemas = schemas
        self._tenant_id = tenant_id
        self._threshold = evidence_match_threshold

    def approve(
        self,
        session: Session,
        *,
        candidate_id: str,
        decision: str,
        final_value: Any = None,
        reviewer: str,
        note: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
        previous_approval_id: str | None = UNCHECKED,
        object_scope: tuple[str, str] | None = None,
    ) -> ApprovalOutcome:
        """Record a human decision. Idempotent: an identical repeat writes nothing.

        `previous_approval_id` is the active decision on the field as the caller last saw
        it (None: undecided). When it is given and the field's active decision is another
        one, the write is refused as stale. `object_scope` (object_type, object_id) limits
        the call to candidates of that object; any other candidate is not found.

        `evidence` is the reviewer's own evidence for an edited value: a list of
        {page_no, quote}. It is required when the candidate has none (the model found no
        value), so that no canonical value exists without a located quote. Each quote must
        be found on its page."""
        if decision not in DECISIONS:
            raise ApprovalError(f"unknown decision {decision!r}")
        if not reviewer.strip():
            raise ApprovalError("a reviewer name is required")
        row = session.execute(
            select(Candidate, ExtractionRun)
            .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
            .where(
                Candidate.id == candidate_id,
                Candidate.tenant_id == self._tenant_id,
                ExtractionRun.tenant_id == self._tenant_id,
            )
            .with_for_update(of=Candidate)
            # The row lock is only useful if the locked values are read from the database,
            # not from objects this session loaded earlier.
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None:
            raise LookupError(f"candidate {candidate_id} not found")
        candidate, run = row
        if object_scope is not None and (run.object_type, run.object_id) != object_scope:
            raise LookupError(f"candidate {candidate_id} not found")
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
            if not self._has_located_evidence(session, candidate):
                # No canonical value without located evidence: the reviewer must find it.
                raise ApprovalError(
                    "the evidence for this value was not located in the document; use decision "
                    "'edited' and give the page and the quoted text that state the value"
                )
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
        reviewer_spans: list[dict[str, Any]] = []
        if decision == "edited":
            reviewer_spans = self._reviewer_spans(session, run, evidence or [])
            if not reviewer_spans and not self._has_located_evidence(session, candidate):
                raise ApprovalError(
                    "this field has no located evidence from the document; give the page and "
                    "the quoted text that state the value"
                )
        elif evidence:
            raise ApprovalError(f"decision {decision!r} does not take evidence")

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
        if previous_approval_id != UNCHECKED and previous_approval_id != (
            current.id if current else None
        ):
            session.rollback()
            raise StaleDecisionError(
                "this field was decided again since it was loaded; it has been reloaded"
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
                evidence=self._evidence(
                    session, candidate, decision, reviewer, note, reviewer_spans
                ),
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
        # The database retires a fact only after its approval is no longer active.
        session.flush()
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

    def _has_located_evidence(self, session: Session, candidate: Candidate) -> bool:
        return (
            session.scalar(
                select(EvidenceSpan.id)
                .where(
                    EvidenceSpan.candidate_id == candidate.id,
                    EvidenceSpan.tenant_id == self._tenant_id,
                    EvidenceSpan.char_start.is_not(None),
                )
                .limit(1)
            )
            is not None
        )

    def _reviewer_spans(
        self, session: Session, run: ExtractionRun, evidence: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Locate each quote the reviewer gave on the page they named, or refuse."""
        spans = []
        for item in evidence:
            page_no, quote = item.get("page_no"), str(item.get("quote") or "").strip()
            if not isinstance(page_no, int) or not quote:
                raise ApprovalError("each piece of evidence needs a page number and a quote")
            row = session.execute(
                select(Page.text, Page.char_boxes, Page.has_text_layer).where(
                    Page.document_id == run.document_id,
                    Page.tenant_id == self._tenant_id,
                    Page.page_no == page_no,
                )
            ).one_or_none()
            found = (
                None
                if row is None
                else locate(quote, PageText(page_no, row[0], row[1], row[2]), self._threshold)
            )
            if found is None:
                raise ApprovalError(f"the quote was not found on page {page_no}")
            spans.append(
                {
                    "kind": "reviewer_span",
                    "document_id": run.document_id,
                    "page_no": page_no,
                    "bbox": found.bbox,
                    "char_start": found.char_start,
                    "char_end": found.char_end,
                    "quote": quote,
                }
            )
        return spans

    def _evidence(
        self,
        session: Session,
        candidate: Candidate,
        decision: str,
        reviewer: str,
        note: str | None,
        reviewer_spans: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Evidence copied from the candidate, plus the reviewer's own evidence and decision
        when it was not a plain approval."""
        evidence: list[dict[str, Any]] = [
            {
                "kind": "span",
                "evidence_span_id": span.id,
                "ordinal": span.ordinal,
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
                .order_by(EvidenceSpan.ordinal.nulls_last(), EvidenceSpan.page_no, EvidenceSpan.id)
            )
        ]
        evidence.extend(reviewer_spans)
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
    if decision == "flagged":
        return None
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
