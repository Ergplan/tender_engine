"""The derivation pass on a real pipeline: written once the fields a rule reads are
decided, from the reviewer's values with their evidence inherited, as a derived run that
makes no model call; written again, and the old decision withdrawn, when one of those
fields is decided again."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Candidate, EvidenceSpan, ExtractionRun, Job
from core.services.approve import ApprovalError, ApprovalService
from tender.domain_packs.power.derivations import optimizer_constraints, source_eligibility
from tender.models import Tender
from tender.services.derive import DerivedGuard, DerivedWriter, derived_rules
from tender.services.worker_jobs import derived_writer
from tests.conftest import Pipeline
from tests.fixtures.tenders import extracted_tender

CAPACITY = "sector.power.common.total_capacity_mw"
OPTIMIZER = optimizer_constraints.FIELD
SOURCES = source_eligibility.FIELD


def writer_of(pipeline: Pipeline) -> DerivedWriter:
    return derived_writer(
        pipeline.catalog, pipeline.extract, pipeline.schemas, pipeline.settings.tenant_id
    )


def guarded_of(pipeline: Pipeline, writer: DerivedWriter) -> ApprovalService:
    return ApprovalService(
        pipeline.schemas,
        pipeline.settings.tenant_id,
        guards=[DerivedGuard(writer, pipeline.tenders, pipeline.catalog)],
    )


def live(db: Session, tender_id: str, path: str) -> Candidate:
    return db.execute(
        select(Candidate)
        .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
        .where(
            ExtractionRun.object_id == tender_id,
            ExtractionRun.mode == "derived",
            Candidate.field_path == path,
            Candidate.status.in_(("validated", "needs_review", "not_found")),
        )
    ).scalar_one()


def decide_inputs(
    pipeline: Pipeline,
    db: Session,
    writer: DerivedWriter,
    tender: Tender,
    approvals: ApprovalService,
) -> list[str]:
    """Decide every field a rule reads that has a candidate: approve the located values,
    set the rest aside as not in the document. Returns the paths decided."""
    wanted = {
        path
        for rule in derived_rules(pipeline.catalog.get(tender.tender_type))
        for path in rule.inputs
    }
    decided = []
    for item in writer.review(db, tender).fields:
        if item.field_path not in wanted or item.current is None or item.decided:
            continue
        candidate = item.entries[item.current].state.candidate
        if candidate is None:
            continue
        located = any(span.char_start is not None for span in candidate.evidence)
        decision = "approved" if candidate.value is not None and located else "not_in_document"
        approvals.approve(db, candidate_id=candidate.id, decision=decision, reviewer="Asha")
        decided.append(item.field_path)
    return decided


def test_the_tables_wait_for_the_fields_they_read_then_are_written_with_their_evidence(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    writer = writer_of(pipeline)
    state = writer.state(db, tender)
    assert state.fields == [SOURCES, OPTIMIZER]
    assert state.waiting_for >= 1, "the total capacity, at least, has a candidate and no decision"
    assert state.current is False and state.being_written is False
    assert writer.write(db, tender.id, is_fixture=True) is None, "nothing until they are decided"
    assert db.scalar(select(ExtractionRun).where(ExtractionRun.mode == "derived")) is None

    decided = decide_inputs(pipeline, db, writer, tender, pipeline.approvals)
    assert CAPACITY in decided
    assert writer.state(db, tender).waiting_for == 0
    assert writer.queue_if_settled(db, tender.id, created_by="Asha") is True
    assert writer.queue_if_settled(db, tender.id, created_by="Asha") is False, "queued once"
    pipeline.runner.run_until_idle()

    run = db.scalars(select(ExtractionRun).where(ExtractionRun.mode == "derived")).one()
    assert (run.status, run.model, run.groups, run.prompt_version) == (
        "validated",
        "none (deterministic derivation)",
        ["derived"],
        "v1",
    )
    assert run.token_in == 0 and run.cost_usd == 0 and run.document_id
    # The optimiser table rests on the one decided field with a value; its evidence is
    # that field's.
    optimizer = live(db, tender.id, OPTIMIZER)
    assert (optimizer.status, optimizer.confidence) == ("validated", 1.0)
    assert (optimizer.prompt_name, optimizer.prompt_version) == ("derive", "v1")
    assert optimizer.llm_call_log_id is None and optimizer.window_pages == []
    (row,) = optimizer.value
    assert (row["kind"], row["subject"], row["comparator"], row["value"], row["unit"]) == (
        "quantity",
        "contracted_capacity",
        "==",
        600,
        "mw",
    )
    assert row["derived_from"] == CAPACITY and row["basis"] == "stated"
    assert row["clause"].startswith("p.1:")
    capacity = db.scalars(select(Candidate).where(Candidate.field_path == CAPACITY)).one()
    source = db.scalars(select(EvidenceSpan).where(EvidenceSpan.candidate_id == capacity.id)).one()
    (copy,) = db.scalars(select(EvidenceSpan).where(EvidenceSpan.candidate_id == optimizer.id))
    assert (copy.document_id, copy.page_no, copy.char_start, copy.char_end, copy.quote) == (
        source.document_id,
        source.page_no,
        source.char_start,
        source.char_end,
        source.quote,
    )
    assert "Derived by optimizer_constraints v1" in optimizer.rationale
    assert "Inputs sha256: " in optimizer.rationale
    # Nothing decided speaks of a source: the table is there, every row not addressed,
    # with no evidence to inherit, so it is not approvable.
    sources = live(db, tender.id, SOURCES)
    assert (sources.status, sources.confidence) == ("not_found", 0.0)
    assert [r["status"] for r in sources.value] == ["not_addressed"] * 9
    assert db.scalar(select(EvidenceSpan).where(EvidenceSpan.candidate_id == sources.id)) is None
    state = writer.state(db, tender)
    assert (state.waiting_for, state.current, state.being_written) == (0, True, False)
    assert writer.write(db, tender.id, is_fixture=True) is None, "not written twice"


def test_a_new_decision_on_an_input_withdraws_the_tables_decision_and_writes_them_again(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    writer = writer_of(pipeline)
    guarded = guarded_of(pipeline, writer)
    decide_inputs(pipeline, db, writer, tender, guarded)
    # The guard queued the derivation once the last input was decided.
    assert db.scalar(select(Job).where(Job.kind == "tender_derive")) is not None
    pipeline.runner.run_until_idle()
    first = live(db, tender.id, OPTIMIZER)
    guarded.approve(db, candidate_id=first.id, decision="approved", reviewer="Asha")

    # The reviewer corrects the capacity: the approved table is no longer the reading of
    # the record. It is flagged, with the reason, and written again.
    capacity = db.scalars(select(Candidate).where(Candidate.field_path == CAPACITY)).one()
    guarded.approve(
        db, candidate_id=capacity.id, decision="edited", final_value=650, reviewer="Asha"
    )
    db.expire_all()
    state = pipeline.review_state.for_object(db, "tender", tender.id)
    table = next(f for f in state.fields if f.field_path == OPTIMIZER)
    assert table.approval is not None and table.approval.decision == "flagged"
    assert "decided after this table was derived" in (table.approval.note or "")
    derived = writer.state(db, tender)
    assert derived.current is False and derived.being_written is True
    with pytest.raises(ApprovalError, match="written again"):
        guarded.approve(db, candidate_id=first.id, decision="approved", reviewer="Asha")
    pipeline.runner.run_until_idle()
    db.expire_all()
    second = live(db, tender.id, OPTIMIZER)
    assert second.id != first.id and second.value[0]["value"] == 650
    assert db.get(Candidate, first.id).status == "superseded"
    assert writer.state(db, tender).current is True


def test_the_table_cannot_be_decided_while_a_field_it_reads_is_undecided(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    writer = writer_of(pipeline)
    guarded = guarded_of(pipeline, writer)
    decide_inputs(pipeline, db, writer, tender, pipeline.approvals)
    assert writer.write(db, tender.id, is_fixture=True) is not None
    pipeline.runner.run_until_idle()
    # A decision is withdrawn: the capacity is undecided again.
    capacity = db.scalars(select(Candidate).where(Candidate.field_path == CAPACITY)).one()
    pipeline.approvals.approve(db, candidate_id=capacity.id, decision="cleared", reviewer="A")
    assert writer.state(db, tender).waiting_for == 1
    table = live(db, tender.id, OPTIMIZER)
    with pytest.raises(ApprovalError, match="derived from first"):
        guarded.approve(db, candidate_id=table.id, decision="approved", reviewer="Asha")
    with pytest.raises(ApprovalError, match="derived from first"):
        guarded.approve(db, candidate_id=table.id, decision="not_in_document", reviewer="Asha")
