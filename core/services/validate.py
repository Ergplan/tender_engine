"""ValidationService: type coercion, required fields, range and regex rules, cross-field
rules and run rules.

Deterministic: no model call. A failed rule marks the candidate needs_review with the rule
name; it never hides the candidate.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.models import (
    Candidate,
    CanonicalFact,
    EvidenceSpan,
    ExtractionRun,
    ValidationResult,
)
from core.schemas import ExtractionSchema, SchemaRegistry
from core.services import audit
from core.validation.rules import FIELD_RULES

ACTOR = "validation"


class ValidationService:
    def __init__(self, schemas: SchemaRegistry, tenant_id: str) -> None:
        self._schemas = schemas
        self._tenant_id = tenant_id

    def validate(self, session: Session, extraction_run_id: str) -> ExtractionRun:
        run = session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.id == extraction_run_id, ExtractionRun.tenant_id == self._tenant_id
            )
        )
        if run is None:
            raise LookupError(f"extraction run {extraction_run_id} not found")
        schema = self._schemas.get(run.schema_name, run.schema_version)
        candidates = list(
            session.scalars(
                select(Candidate)
                .where(Candidate.extraction_run_id == run.id, Candidate.tenant_id == run.tenant_id)
                .order_by(Candidate.created_at, Candidate.id)
            )
        )
        ids = [candidate.id for candidate in candidates]
        session.execute(
            delete(ValidationResult).where(
                ValidationResult.candidate_id.in_(ids), ValidationResult.tenant_id == run.tenant_id
            )
        )
        spans: dict[str, list[bool]] = {cid: [] for cid in ids}
        unlocated_pages: dict[str, set[int]] = {cid: set() for cid in ids}
        for candidate_id, char_start, page_no in session.execute(
            select(EvidenceSpan.candidate_id, EvidenceSpan.char_start, EvidenceSpan.page_no).where(
                EvidenceSpan.candidate_id.in_(ids), EvidenceSpan.tenant_id == run.tenant_id
            )
        ):
            spans[candidate_id].append(char_start is not None)
            if char_start is None:
                unlocated_pages[candidate_id].add(page_no)

        results: dict[str, list[tuple[str, bool, str]]] = {cid: [] for cid in ids}
        # Rule names whose failure is a warning for that candidate, not an error.
        warned: dict[str, set[str]] = {cid: set() for cid in ids}
        coerced: dict[str, Any] = {}
        for candidate in candidates:
            field = schema.field(candidate.field_path)
            if candidate.value is None and candidate.status in ("not_found", "needs_review"):
                if field.required:
                    # The object is required to have the value, not every document and
                    # version of it: a corrigendum need not restate the bid deadline.
                    if self._stated_elsewhere(session, run, candidate):
                        message = "stated by another document or an earlier version of the object"
                        results[candidate.id].append(("required_present", True, message))
                    else:
                        message = "required field: the model returned no value"
                        results[candidate.id].append(("required_present", False, message))
                continue
            if candidate.status == "rejected":
                message = "a value came without evidence; it is not shown for review"
                results[candidate.id].append(("evidence_required", False, message))
                continue
            if candidate.status not in ("raw", "validated", "needs_review"):
                continue
            checks = results[candidate.id]
            found = spans[candidate.id]
            pages = ", ".join(f"p.{page_no}" for page_no in sorted(unlocated_pages[candidate.id]))
            if found and all(found):
                checks.append(("evidence_located", True, "quote found on the page"))
            elif any(found):
                missing = len(found) - sum(found)
                message = f"{missing} of {len(found)} quotes not located (stated on {pages})"
                checks.append(("evidence_not_located", False, message))
            else:
                checks.append(("evidence_not_located", False, f"evidence not located on {pages}"))
            try:
                value = self._schemas.value_types.coerce(candidate.value, field)
            except ValueError as exc:
                checks.append(("type", False, f"not a valid {field.value_type}: {exc}"))
                continue
            checks.append(("type", True, f"valid {field.value_type}"))
            coerced[candidate.id] = value
            for rule in FIELD_RULES:
                outcome = rule(field, value)
                if outcome is not None:
                    checks.append(outcome)

        best = _best_per_field(candidates, coerced)
        self._cross_field(schema, best, candidates, coerced, results, warned)
        valued = [candidate for candidate in candidates if candidate.id in coerced]
        for rule_name in schema.run_rules:
            for verdict in self._schemas.run_rule(rule_name)(session, run, valued):
                if verdict.candidate_id in coerced:
                    results[verdict.candidate_id].append(
                        (rule_name, verdict.passed, verdict.message)
                    )

        for candidate in candidates:
            for rule_name, passed, message in results[candidate.id]:
                warning = not passed and rule_name in warned[candidate.id]
                session.add(
                    ValidationResult(
                        tenant_id=run.tenant_id,
                        created_by=ACTOR,
                        candidate_id=candidate.id,
                        rule_name=rule_name,
                        passed=passed,
                        message=message,
                        severity="warning" if warning else "error",
                    )
                )
            failed = any(
                not passed and rule_name not in warned[candidate.id]
                for rule_name, passed, _ in results[candidate.id]
            )
            if candidate.value is None and candidate.status in ("not_found", "needs_review"):
                # No value: a required field needs review, an optional one stays not_found.
                self._set_status(session, candidate, "needs_review" if failed else "not_found")
            elif candidate.status in ("raw", "validated", "needs_review"):
                self._set_status(session, candidate, "needs_review" if failed else "validated")
        run.status = "validated"
        run.finished_at = datetime.now(UTC)
        session.commit()
        return run

    def _cross_field(
        self,
        schema: ExtractionSchema,
        best: dict[str, Candidate],
        candidates: list[Candidate],
        coerced: dict[str, Any],
        results: dict[str, list[tuple[str, bool, str]]],
        warned: dict[str, set[str]],
    ) -> None:
        """Rules run on the best value of each field. The outcome is written on every
        typed candidate of the fields concerned, so a failure cannot be hidden behind an
        alternative candidate that the rule never saw."""
        values = {path: coerced[candidate.id] for path, candidate in best.items()}
        for rule_name in schema.cross_field_rules:
            for outcome in self._schemas.rule(rule_name)(values):
                for candidate in candidates:
                    if candidate.id in coerced and candidate.field_path in outcome.field_paths:
                        results[candidate.id].append((rule_name, outcome.passed, outcome.message))
                        if outcome.warning:
                            warned[candidate.id].add(rule_name)

    def _stated_elsewhere(self, session: Session, run: ExtractionRun, candidate: Candidate) -> bool:
        """Whether the object already has a value for the field: a live candidate with a
        value from another run of this version or of an earlier one, or a current
        canonical fact with a value up to this version."""
        other = session.scalar(
            select(Candidate.id)
            .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
            .where(
                Candidate.tenant_id == run.tenant_id,
                ExtractionRun.tenant_id == run.tenant_id,
                ExtractionRun.object_type == run.object_type,
                ExtractionRun.object_id == run.object_id,
                ExtractionRun.object_version <= run.object_version,
                ExtractionRun.id != run.id,
                Candidate.field_path == candidate.field_path,
                Candidate.value.is_not(None),
                Candidate.status.in_(("raw", "validated", "needs_review")),
            )
            .limit(1)
        )
        if other is not None:
            return True
        fact = session.scalar(
            select(CanonicalFact.id)
            .where(
                CanonicalFact.tenant_id == run.tenant_id,
                CanonicalFact.object_type == run.object_type,
                CanonicalFact.object_id == run.object_id,
                CanonicalFact.object_version <= run.object_version,
                CanonicalFact.field_path == candidate.field_path,
                CanonicalFact.is_current.is_(True),
                CanonicalFact.value.is_not(None),
            )
            .limit(1)
        )
        return fact is not None

    def _set_status(self, session: Session, candidate: Candidate, status: str) -> None:
        if candidate.status == status:
            return
        before = candidate.status
        candidate.status = status
        audit.record(
            session,
            tenant_id=candidate.tenant_id,
            actor=ACTOR,
            action="status_change",
            table_name="candidate",
            row_id=candidate.id,
            before={"status": before},
            after={"status": status},
        )


def _best_per_field(candidates: list[Candidate], coerced: dict[str, Any]) -> dict[str, Candidate]:
    """For each field, the highest-confidence candidate whose value has the right type."""
    best: dict[str, Candidate] = {}
    for candidate in candidates:
        if candidate.id not in coerced:
            continue
        current = best.get(candidate.field_path)
        if current is None or candidate.confidence > current.confidence:
            best[candidate.field_path] = candidate
    return best
