"""Derived fields of a tender, written from its decided fields by deterministic code.

The source eligibility table and the optimiser constraints are readings of the record, not
of the document: once the fields a rule names are decided (approved, edited or set aside
as not in the document), the rule in `tender/domain_packs/<pack>/derivations/` computes
the rows, and each row says which clause it rests on. The candidate is written in a run of
mode "derived": no page is read, no model is called, its evidence spans are copies of the
located spans of the decided fields it draws on, and it is validated and decided like any
other candidate (producer DERIVED in the field trace). A later decision on one of those
fields writes the table again and withdraws the decision made on the old one.

A table with no clause behind any row (an EPC contract that never speaks of a source of
supply) has nothing to inherit: it is stored as a `not_found` candidate that still carries
the all-not-addressed rows, shown with that reason and not approvable, as any candidate
without evidence.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Approval, Candidate, ExtractionRun, Job
from core.models.extraction import DERIVED_MODE, RECORD_MODES
from core.services import jobs
from core.services.approve import ApprovalError, ApprovalService
from core.services.extract import LIVE_STATUSES, ExtractService
from core.services.review_state import ReviewStateService
from tender.domain_packs.power import derivations
from tender.domain_packs.power.derivations import Decided, Inputs, Rule
from tender.models import Tender
from tender.services.packs import Catalog, CompiledType
from tender.services.review import TenderReview, tender_review
from tender.services.summary import decided_field_value, inherited_span, reviewer_evidence
from tender.services.tenders import JOB_KIND as AMENDMENT_JOB
from tender.services.tenders import OBJECT_TYPE, TenderService

log = logging.getLogger("tender.derive")
ACTOR = "derive"
JOB_KIND = "tender_derive"
PROMPT_NAME = "derive"
DECIDED = ("approved", "edited", "not_in_document")
HASH_HEADING = "Inputs sha256: "


class DerivedState(BaseModel):
    """Where the derived fields stand for the reviewer: how many of the fields they are
    written from still need a decision, whether the tables in review were written from
    the record as it stands, and whether they are being written now."""

    waiting_for: int
    current: bool
    being_written: bool
    # The derived field paths of the tender's type.
    fields: list[str]


def derived_rules(compiled: CompiledType) -> list[Rule]:
    """The rules that write this type's derived fields, in review order."""
    derived = {section.name for section in compiled.sections if section.derived}
    return [
        derivations.rule_for(field.path) for field in compiled.fields if field.section in derived
    ]


def inputs_hash(inputs: Inputs) -> str:
    """What the tables were written from: the decided values and the spans behind them."""
    payload = {
        path: {
            "value": d.value,
            "spans": [(s.document_id, s.page_no, s.char_start, s.char_end) for s in d.spans],
        }
        for path, d in sorted(inputs.items())
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class DerivedWriter:
    def __init__(
        self,
        catalog: Catalog,
        extract: ExtractService,
        tenders: TenderService,
        review_state: ReviewStateService,
        tenant_id: str,
    ) -> None:
        self._catalog = catalog
        self._extract = extract
        self._tenders = tenders
        self._review_state = review_state
        self._tenant_id = tenant_id

    # --- what the rules read -------------------------------------------------------------

    def review(self, session: Session, tender: Tender) -> TenderReview:
        return tender_review(session, self._catalog, self._tenders, self._review_state, tender)

    def inputs(self, session: Session, tender: Tender, review: TenderReview) -> Inputs:
        """The decided fields a rule may read: a field whose current entry is approved or
        edited and has located evidence. An undecided field is not read (the writer waits
        for it); one set aside as not in the document is read as absent."""
        wanted = {
            path
            for rule in derived_rules(self._catalog.get(tender.tender_type))
            for path in rule.inputs
        }
        evidence = reviewer_evidence(session, self._tenant_id, tender)
        found: Inputs = {}
        for item in review.fields:
            if item.field_path not in wanted or not item.decided:
                continue
            value = decided_field_value(item, evidence)
            if value is None:
                continue
            found[item.field_path] = Decided(
                path=item.field_path,
                label=item.label,
                value=value[0],
                spans=value[1],
                version_no=value[3],
            )
        return found

    def state(
        self, session: Session, tender: Tender, review: TenderReview | None = None
    ) -> DerivedState:
        compiled = self._catalog.get(tender.tender_type)
        rules = derived_rules(compiled)
        review = review or self.review(session, tender)
        wanted = {path for rule in rules for path in rule.inputs}
        waiting_for = sum(
            1
            for item in review.fields
            if item.field_path in wanted and item.current is not None and not item.decided
        )
        digest = inputs_hash(self.inputs(session, tender, review))
        live = self._live(session, tender)
        current = all(
            rule.field_path in live and HASH_HEADING + digest in live[rule.field_path].rationale
            for rule in rules
        )
        being_written = (
            session.scalar(
                select(Job.id)
                .where(
                    Job.tenant_id == self._tenant_id,
                    Job.kind == JOB_KIND,
                    Job.status.in_(("queued", "running")),
                    Job.payload["tender_id"].astext == tender.id,
                )
                .limit(1)
            )
            is not None
            or session.scalar(
                select(ExtractionRun.id)
                .where(
                    ExtractionRun.tenant_id == self._tenant_id,
                    ExtractionRun.object_type == OBJECT_TYPE,
                    ExtractionRun.object_id == tender.id,
                    ExtractionRun.mode == DERIVED_MODE,
                    ExtractionRun.status.in_(("running", "extracted")),
                )
                .limit(1)
            )
            is not None
        )
        return DerivedState(
            waiting_for=waiting_for,
            current=current,
            being_written=being_written,
            fields=[rule.field_path for rule in rules],
        )

    def _live(self, session: Session, tender: Tender) -> dict[str, Candidate]:
        """The derived candidate in review per derived field."""
        found: dict[str, Candidate] = {}
        for candidate in session.scalars(
            select(Candidate)
            .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
            .where(
                Candidate.tenant_id == self._tenant_id,
                ExtractionRun.tenant_id == self._tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.object_id == tender.id,
                ExtractionRun.mode == DERIVED_MODE,
                Candidate.status.in_(LIVE_STATUSES),
            )
            .order_by(Candidate.created_at.desc())
        ):
            found.setdefault(candidate.field_path, candidate)
        return found

    # --- when to write ---------------------------------------------------------------------

    def after_validation(self, session: Session, extraction_run_id: str) -> None:
        """Called by the worker when a run has been validated: once no extraction of the
        tender is under way, queue the derivation. A record or derived run queues none."""
        run = session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.id == extraction_run_id, ExtractionRun.tenant_id == self._tenant_id
            )
        )
        if run is None or run.object_type != OBJECT_TYPE or run.mode in RECORD_MODES:
            return
        self.queue_if_settled(session, run.object_id, created_by=ACTOR, is_fixture=run.is_fixture)

    def queue_if_settled(
        self, session: Session, tender_id: str, *, created_by: str, is_fixture: bool = False
    ) -> bool:
        """Queue the derivation unless an extraction or an amendment map of the tender is
        still queued or running, or a derivation of it is queued already."""
        under_way = session.scalar(
            select(ExtractionRun.id)
            .where(
                ExtractionRun.tenant_id == self._tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.object_id == tender_id,
                ExtractionRun.mode.notin_(RECORD_MODES),
                ExtractionRun.status.in_(("queued", "running", "extracted")),
            )
            .limit(1)
        )
        waiting = session.scalar(
            select(Job.id)
            .where(
                Job.tenant_id == self._tenant_id,
                Job.kind.in_((AMENDMENT_JOB, JOB_KIND)),
                Job.status.in_(("queued", "running")),
                Job.payload["tender_id"].astext == tender_id,
            )
            .limit(1)
        )
        if under_way is not None or waiting is not None:
            return False
        jobs.enqueue(
            session,
            tenant_id=self._tenant_id,
            kind=JOB_KIND,
            payload={"tender_id": tender_id, "is_fixture": is_fixture},
            created_by=created_by,
        )
        session.commit()
        return True

    # --- the pass --------------------------------------------------------------------------

    def write(
        self, session: Session, tender_id: str, *, is_fixture: bool = False, force: bool = False
    ) -> ExtractionRun | None:
        """Write every derived field of the tender from its decided fields, as the
        candidates of one new derived run on the tender's latest extracted version, and
        queue their validation. Returns None when the tender has no extracted version yet,
        or when the tables in review were written from the record as it stands (unless
        `force`)."""
        tender = self._tenders.get(session, tender_id)
        compiled = self._catalog.get(tender.tender_type)
        rules = derived_rules(compiled)
        review = self.review(session, tender)
        if not rules or not review.versions:
            return None
        versions = [
            e.version_no for f in review.fields for e in f.entries if f.section != "derived"
        ]
        if not versions:
            return None
        # Written from decisions: while a field a rule reads is still undecided, nothing is
        # written (a table computed from half the decisions would be stale at once).
        wanted = {path for rule in rules for path in rule.inputs}
        if any(
            f.field_path in wanted and f.current is not None and not f.decided
            for f in review.fields
        ):
            return None
        inputs = self.inputs(session, tender, review)
        digest = inputs_hash(inputs)
        live = self._live(session, tender)
        if not force and all(
            rule.field_path in live and HASH_HEADING + digest in live[rule.field_path].rationale
            for rule in rules
        ):
            return None

        run = ExtractionRun(
            tenant_id=self._tenant_id,
            created_by=ACTOR,
            document_id=review.versions[0].documents[0].document_id,
            object_type=OBJECT_TYPE,
            object_id=tender.id,
            object_version=max(versions),
            schema_name=compiled.schema.name,
            schema_version=compiled.schema.version,
            prompt_version="v1",
            groups=sorted({compiled.schema.field(rule.field_path).group for rule in rules}),
            model="none (deterministic derivation)",
            status="running",
            is_fixture=is_fixture,
            mode=DERIVED_MODE,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        for rule in rules:
            derivation = rule.derive(inputs)
            used = list(dict.fromkeys(path for row in derivation.rows for path in row.inputs))
            spans: list[dict[str, Any]] = []
            for path in used:
                for span in inputs[path].spans:
                    spans.append(inherited_span(span, len(spans) + 1))
            labels = ", ".join(inputs[path].label for path in used) or "no decided field"
            rationale = (
                f"Derived by {rule.module.rsplit('.', 1)[-1]} {rule.version}: {derivation.note}."
                f"\n\nFrom: {labels}; each row names the field and the clause it rests on."
                f"\n\n{HASH_HEADING}{digest}"
            )
            value = [row.value for row in derivation.rows]
            if spans:
                candidate = self._extract.record_candidate(
                    session,
                    run,
                    rule.field_path,
                    value=value,
                    confidence=1.0,
                    rationale=rationale,
                    spans=spans,
                    call_log_id=None,
                    prompt_name=PROMPT_NAME,
                    prompt_version=rule.version,
                )
            else:
                candidate = self._extract.unsupported_candidate(
                    session,
                    run,
                    rule.field_path,
                    value=value,
                    rationale=rationale,
                    prompt_name=PROMPT_NAME,
                    prompt_version=rule.version,
                )
            for earlier in live.values():
                if earlier.field_path == rule.field_path and earlier.id != candidate.id:
                    self._extract.supersede(session, earlier, run)
        run.status = "extracted"
        run.finished_at = datetime.now(UTC)
        jobs.enqueue(
            session,
            tenant_id=self._tenant_id,
            kind="validate",
            payload={"extraction_run_id": run.id},
            created_by=ACTOR,
        )
        session.commit()
        return run


class DerivedGuard:
    """The rule on decisions for the derived fields: they are readings of the decided
    fields, so

    - a derived field cannot be approved, edited or set aside while a field its rule reads
      is undecided;
    - it cannot be approved while it is not the reading of the record as it stands;
    - a decision on a field a rule reads withdraws a decision already made on the derived
      field (flagged, with the reason) and writes it again."""

    def __init__(self, writer: DerivedWriter, tenders: TenderService, catalog: Catalog) -> None:
        self._writer = writer
        self._tenders = tenders
        self._catalog = catalog

    def _rules(self, tender: Tender) -> list[Rule]:
        return derived_rules(self._catalog.get(tender.tender_type))

    def before(
        self, session: Session, candidate: Candidate, run: ExtractionRun, decision: str
    ) -> None:
        if run.object_type != OBJECT_TYPE or decision not in DECIDED:
            return
        tender = self._tenders.get(session, run.object_id)
        if candidate.field_path not in {rule.field_path for rule in self._rules(tender)}:
            return
        state = self._writer.state(session, tender)
        if state.waiting_for:
            raise ApprovalError(
                f"decide the fields it is derived from first ({state.waiting_for} to go)"
            )
        if decision == "approved" and not state.current:
            raise ApprovalError(
                "the table is being written again from your decisions; it will be ready in a moment"
            )

    def after(
        self, session: Session, service: ApprovalService, approval: Approval, run: ExtractionRun
    ) -> None:
        if run.object_type != OBJECT_TYPE:
            return
        tender = self._tenders.get(session, run.object_id)
        rules = self._rules(tender)
        derived_paths = {rule.field_path for rule in rules}
        if approval.field_path in derived_paths:
            return
        if approval.field_path not in {path for rule in rules for path in rule.inputs}:
            return
        review = self._writer.review(session, tender)
        state = self._writer.state(session, tender, review)
        if state.current:
            return
        for item in review.fields:
            if item.field_path not in derived_paths or item.current is None:
                continue
            entry = item.entries[item.current]
            decided = entry.state.approval
            if entry.state.candidate and decided and decided.decision != "flagged":
                service.approve(
                    session,
                    candidate_id=entry.state.candidate.id,
                    decision="flagged",
                    reviewer=approval.reviewer,
                    note=f"{approval.field_path} was decided after this table was derived; it "
                    "is written again and needs a new decision",
                )
        if state.waiting_for == 0:
            self._writer.queue_if_settled(session, tender.id, created_by=approval.reviewer)


def job_handlers(writer: DerivedWriter) -> dict[str, Callable[[Session, dict[str, Any]], None]]:
    def tender_derive(session: Session, payload: dict[str, Any]) -> None:
        writer.write(
            session,
            payload["tender_id"],
            is_fixture=payload.get("is_fixture", False),
            force=payload.get("force", False),
        )

    return {JOB_KIND: tender_derive}
