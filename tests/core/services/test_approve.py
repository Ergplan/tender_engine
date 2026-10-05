from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models import Approval, AuditLog, Candidate, CanonicalFact, ExtractionRun, Feedback
from core.services.approve import ApprovalError
from tests.conftest import Pipeline
from tests.fixtures.llm import GOOD_ANSWERS, ScriptedSDK

MakePipeline = Callable[..., Pipeline]


def candidate(db: Session, run: ExtractionRun, path: str) -> Candidate:
    row = db.scalar(
        select(Candidate).where(Candidate.extraction_run_id == run.id, Candidate.field_path == path)
    )
    assert row is not None
    return row


def count(db: Session, model: Any, *where: Any) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def truth_audits(db: Session) -> list[tuple[str, str]]:
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.table_name.in_(["approval", "canonical_fact", "feedback"]))
        .order_by(AuditLog.at, AuditLog.id)
    )
    return sorted((row.table_name, row.action) for row in rows)


def test_approval_writes_exactly_one_canonical_fact_and_one_audit_row_per_write(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    target = candidate(db, run, "dates.pre_bid_date")
    outcome = pipeline.approvals.approve(
        db, candidate_id=target.id, decision="approved", reviewer="Asha"
    )

    assert outcome.created is True and outcome.feedback is None
    assert count(db, CanonicalFact) == 1 and count(db, Approval) == 1 and count(db, Feedback) == 0
    fact = db.scalars(select(CanonicalFact)).one()
    assert fact.value == "2026-03-12", "the coerced value is stored, not the raw '12.03.2026'"
    assert (fact.object_type, fact.object_id, fact.object_version) == (
        "document",
        run.document_id,
        1,
    )
    assert (fact.field_path, fact.value_type, fact.is_current) == (
        "dates.pre_bid_date",
        "date",
        True,
    )
    assert fact.approval_id == outcome.approval.id
    assert fact.tenant_id == "ergplan" and fact.created_by == "Asha"
    approval = outcome.approval
    assert (approval.decision, approval.reviewer, approval.status) == ("approved", "Asha", "active")
    assert approval.final_value == "2026-03-12" and approval.candidate_id == target.id
    assert truth_audits(db) == [("approval", "insert"), ("canonical_fact", "insert")]
    audit = db.scalars(select(AuditLog).where(AuditLog.table_name == "canonical_fact")).one()
    assert (
        audit.actor == "Asha" and audit.row_id == fact.id and audit.after["value"] == "2026-03-12"
    )


def test_a_second_identical_approval_writes_nothing(pipeline: Pipeline, db: Session) -> None:
    run = pipeline.extracted_run(db)
    target = candidate(db, run, "security.emd_per_mw")
    first = pipeline.approvals.approve(
        db, candidate_id=target.id, decision="approved", reviewer="Asha"
    )
    audits = count(db, AuditLog)
    second = pipeline.approvals.approve(
        db, candidate_id=target.id, decision="approved", reviewer="Asha"
    )
    assert second.created is False and second.approval.id == first.approval.id
    assert second.canonical_fact is not None and second.canonical_fact.id == first.canonical_fact.id  # type: ignore[union-attr]
    assert count(db, Approval) == 1 and count(db, CanonicalFact) == 1
    assert count(db, AuditLog) == audits


def test_canonical_fact_inherits_the_candidates_evidence(pipeline: Pipeline, db: Session) -> None:
    run = pipeline.extracted_run(db)
    target = candidate(db, run, "security.emd_per_mw")
    fact = pipeline.approvals.approve(
        db, candidate_id=target.id, decision="approved", reviewer="Asha"
    ).canonical_fact
    assert fact is not None
    [evidence] = fact.evidence
    assert evidence["kind"] == "span" and evidence["page_no"] == 3
    assert evidence["document_id"] == run.document_id and evidence["bbox"] is not None
    assert evidence["quote"] == "The Earnest Money Deposit shall be INR 928000 per MW"


def test_an_edit_keeps_the_candidate_unchanged_and_records_feedback(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    target = candidate(db, run, "security.emd_per_mw")
    outcome = pipeline.approvals.approve(
        db,
        candidate_id=target.id,
        decision="edited",
        final_value="9,30,000",
        reviewer="Asha",
        note=" typo in RfS ",
    )
    db.refresh(target)
    assert target.value == 928000 and target.status == "validated"
    assert outcome.approval.final_value == 930000 and outcome.approval.note == "typo in RfS"
    assert outcome.canonical_fact is not None and outcome.canonical_fact.value == 930000
    feedback = outcome.feedback
    assert feedback is not None
    assert (feedback.candidate_value, feedback.final_value, feedback.delta_kind) == (
        928000,
        930000,
        "wrong_value",
    )
    assert (feedback.reviewer, feedback.prompt_version, feedback.approval_id) == (
        "Asha",
        "v1",
        outcome.approval.id,
    )
    kinds = [item["kind"] for item in outcome.canonical_fact.evidence]
    assert kinds == ["span", "reviewer_decision"]
    assert outcome.canonical_fact.evidence[1]["note"] == "typo in RfS"
    assert truth_audits(db) == [
        ("approval", "insert"),
        ("canonical_fact", "insert"),
        ("feedback", "insert"),
    ]


def test_an_edit_that_only_changes_form_is_format_feedback(pipeline: Pipeline, db: Session) -> None:
    run = pipeline.extracted_run(db)
    target = candidate(db, run, "identity.issuer")
    outcome = pipeline.approvals.approve(
        db,
        candidate_id=target.id,
        decision="edited",
        final_value="ACME POWER LIMITED",
        reviewer="Asha",
    )
    assert outcome.feedback is not None and outcome.feedback.delta_kind == "format"


def test_not_in_document_on_a_valued_candidate_is_a_null_fact_and_extra_feedback(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    target = candidate(db, run, "security.tenure_years")
    outcome = pipeline.approvals.approve(
        db, candidate_id=target.id, decision="not_in_document", reviewer="Asha"
    )
    assert outcome.canonical_fact is not None and outcome.canonical_fact.value is None
    assert outcome.feedback is not None and outcome.feedback.delta_kind == "extra"


def test_a_not_found_field_can_be_confirmed_absent_or_supplied_by_the_reviewer(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(
        {k: v for k, v in GOOD_ANSWERS.items() if k not in ("issuer", "tenure_years")}
    )
    pipeline = make_pipeline(sdk)
    run = pipeline.extracted_run(db)
    absent = pipeline.approvals.approve(
        db,
        candidate_id=candidate(db, run, "identity.issuer").id,
        decision="not_in_document",
        reviewer="Asha",
    )
    assert absent.canonical_fact is not None and absent.canonical_fact.value is None
    assert absent.feedback is None
    tenure = candidate(db, run, "security.tenure_years").id
    with pytest.raises(ApprovalError, match="no located evidence"):
        pipeline.approvals.approve(
            db, candidate_id=tenure, decision="edited", final_value=25, reviewer="Asha"
        )
    with pytest.raises(ApprovalError, match="not found on page 2"):
        pipeline.approvals.approve(
            db,
            candidate_id=tenure,
            decision="edited",
            final_value=25,
            reviewer="Asha",
            evidence=[{"page_no": 2, "quote": "for a tenure of 25 years"}],
        )
    assert count(db, CanonicalFact) == 1, "a value without located evidence is not written"
    supplied = pipeline.approvals.approve(
        db,
        candidate_id=tenure,
        decision="edited",
        final_value=25,
        reviewer="Asha",
        evidence=[{"page_no": 3, "quote": "for a tenure of 25 years"}],
    )
    assert supplied.canonical_fact is not None and supplied.canonical_fact.value == 25
    assert supplied.feedback is not None and supplied.feedback.delta_kind == "missing"
    span, decision = supplied.canonical_fact.evidence
    assert (span["kind"], span["page_no"], span["quote"]) == (
        "reviewer_span",
        3,
        "for a tenure of 25 years",
    )
    assert span["bbox"] and span["char_start"] is not None and span["document_id"]
    assert decision == {
        "kind": "reviewer_decision",
        "decision": "edited",
        "reviewer": "Asha",
        "note": None,
    }
    with pytest.raises(ApprovalError, match="no value to approve"):
        pipeline.approvals.approve(
            db,
            candidate_id=candidate(db, run, "identity.issuer").id,
            decision="approved",
            reviewer="Asha",
        )


def test_a_rejection_records_the_decision_and_feedback_but_no_canonical_fact(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    outcome = pipeline.approvals.approve(
        db,
        candidate_id=candidate(db, run, "identity.issuer").id,
        decision="rejected",
        reviewer="Asha",
    )
    assert outcome.canonical_fact is None and count(db, CanonicalFact) == 0
    assert outcome.feedback is not None and outcome.feedback.delta_kind == "wrong_value"
    assert truth_audits(db) == [("approval", "insert"), ("feedback", "insert")]


def test_a_later_decision_supersedes_the_earlier_one_and_its_fact(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    target = candidate(db, run, "security.capacity_mw")
    first = pipeline.approvals.approve(
        db, candidate_id=target.id, decision="approved", reviewer="Asha"
    )
    second = pipeline.approvals.approve(
        db, candidate_id=target.id, decision="edited", final_value=650, reviewer="Ravi"
    )
    db.expire_all()
    old_approval = db.get_one(Approval, first.approval.id)
    assert old_approval.status == "superseded"
    assert (
        second.approval.supersedes_approval_id == old_approval.id
        and second.approval.status == "active"
    )
    facts = {fact.value: fact for fact in db.scalars(select(CanonicalFact))}
    assert facts[600].is_current is False and facts[600].superseded_at is not None
    assert facts[650].is_current is True and facts[650].created_by == "Ravi"
    assert count(db, CanonicalFact, CanonicalFact.is_current.is_(True)) == 1
    assert truth_audits(db) == [
        ("approval", "insert"),
        ("approval", "insert"),
        ("approval", "supersede"),
        ("canonical_fact", "insert"),
        ("canonical_fact", "insert"),
        ("canonical_fact", "supersede"),
        ("feedback", "insert"),
    ]
    current = pipeline.review_state.canonical(db, "document", run.document_id)
    assert [(f.field_path, f.value) for f in current] == [("security.capacity_mw", 650)]


def test_invalid_decisions_are_refused_and_write_nothing(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(
        {
            **GOOD_ANSWERS,
            "bid_deadline": {**GOOD_ANSWERS["bid_deadline"], "value": "end of March"},
            "issuer": {"value": "Acme", "confidence": 0.9, "rationale": "r", "evidence": []},
        }
    )
    pipeline = make_pipeline(sdk)
    run = pipeline.extracted_run(db)
    approve = pipeline.approvals.approve
    emd = candidate(db, run, "security.emd_per_mw").id
    cases: list[tuple[dict[str, Any], str]] = [
        ({"candidate_id": emd, "decision": "blessed", "reviewer": "A"}, "unknown decision"),
        (
            {"candidate_id": emd, "decision": "approved", "reviewer": "  "},
            "reviewer name is required",
        ),
        (
            {"candidate_id": emd, "decision": "approved", "final_value": 5, "reviewer": "A"},
            "cannot change the value",
        ),
        ({"candidate_id": emd, "decision": "edited", "reviewer": "A"}, "an edit needs a value"),
        (
            {"candidate_id": emd, "decision": "edited", "final_value": "lots", "reviewer": "A"},
            "not a valid decimal",
        ),
        (
            {"candidate_id": emd, "decision": "not_in_document", "final_value": 1, "reviewer": "A"},
            "does not take a value",
        ),
        (
            {
                "candidate_id": candidate(db, run, "dates.bid_deadline").id,
                "decision": "approved",
                "reviewer": "A",
            },
            "not a valid date; edit it before approving",
        ),
        (
            {
                "candidate_id": candidate(db, run, "identity.issuer").id,
                "decision": "approved",
                "reviewer": "A",
            },
            "a rejected candidate cannot be decided",
        ),
    ]
    for kwargs, message in cases:
        with pytest.raises(ApprovalError, match=message):
            approve(db, **kwargs)
        db.rollback()
    with pytest.raises(LookupError):
        approve(db, candidate_id="0" * 32, decision="approved", reviewer="A")
    assert count(db, Approval) == 0 and count(db, CanonicalFact) == 0 and count(db, Feedback) == 0


def test_a_superseded_candidate_cannot_be_decided(pipeline: Pipeline, db: Session) -> None:
    from core.models import Document

    first = pipeline.extracted_run(db)
    old = candidate(db, first, "security.emd_per_mw")
    pipeline.start_run(db, db.get_one(Document, first.document_id))
    pipeline.runner.run_until_idle()
    with pytest.raises(ApprovalError, match="a superseded candidate cannot be decided"):
        pipeline.approvals.approve(db, candidate_id=old.id, decision="approved", reviewer="Asha")


def test_the_database_refuses_a_second_active_approval_or_current_fact_for_one_field(
    pipeline: Pipeline, db: Session
) -> None:
    """Two first decisions arriving together cannot both stay active: unique indexes."""
    run = pipeline.extracted_run(db)
    target = candidate(db, run, "dates.pre_bid_date")
    first = pipeline.approvals.approve(
        db, candidate_id=target.id, decision="approved", reviewer="Asha"
    ).approval
    same_field = {
        "tenant_id": first.tenant_id,
        "created_by": "Ravi",
        "object_type": first.object_type,
        "object_id": first.object_id,
        "object_version": first.object_version,
        "field_path": first.field_path,
    }
    db.add(
        Approval(
            **same_field,
            candidate_id=target.id,
            final_value="2026-03-13",
            decision="edited",
            reviewer="Ravi",
            status="active",
        )
    )
    with pytest.raises(IntegrityError, match="uq_approval_one_active_per_field"):
        db.flush()
    db.rollback()
    db.add(
        CanonicalFact(
            **same_field,
            value="2026-03-13",
            value_type="date",
            approval_id=first.id,
            evidence=[],
            is_current=True,
        )
    )
    with pytest.raises(IntegrityError, match="uq_canonical_fact_one_current_per_field"):
        db.flush()
    db.rollback()
    assert count(db, Approval) == 1 and count(db, CanonicalFact) == 1


def test_an_approval_may_repeat_the_value_in_the_form_the_document_uses(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    target = candidate(db, run, "dates.pre_bid_date")
    assert target.value == "12.03.2026"
    outcome = pipeline.approvals.approve(
        db, candidate_id=target.id, decision="approved", final_value="12.03.2026", reviewer="Asha"
    )
    assert outcome.created and outcome.approval.final_value == "2026-03-12"
    assert outcome.feedback is None


def test_a_value_whose_evidence_was_not_located_cannot_simply_be_approved(
    make_pipeline: MakePipeline, db: Session
) -> None:
    """No canonical value without located evidence: the reviewer has to point to the text."""
    sdk = ScriptedSDK(
        {
            **GOOD_ANSWERS,
            "issuer": {
                **GOOD_ANSWERS["issuer"],
                "evidence": [{"page_no": 1, "quote": "words that are not on the page at all"}],
            },
        }
    )
    pipeline = make_pipeline(sdk)
    run = pipeline.extracted_run(db)
    issuer = candidate(db, run, "identity.issuer")
    assert issuer.status == "needs_review"
    with pytest.raises(ApprovalError, match="was not located"):
        pipeline.approvals.approve(db, candidate_id=issuer.id, decision="approved", reviewer="Asha")
    assert count(db, CanonicalFact) == 0
    outcome = pipeline.approvals.approve(
        db,
        candidate_id=issuer.id,
        decision="edited",
        final_value="Acme Power Limited",
        reviewer="Asha",
        evidence=[{"page_no": 1, "quote": "Issued by Acme Power Limited"}],
    )
    assert outcome.canonical_fact is not None and outcome.feedback is None
    kinds = [item["kind"] for item in outcome.canonical_fact.evidence]
    assert kinds == ["span", "reviewer_span", "reviewer_decision"]


def test_a_flag_is_recorded_without_a_fact_and_withdraws_an_earlier_decision(
    pipeline: Pipeline, db: Session
) -> None:
    from core.models import CanonicalFact

    run = pipeline.extracted_run(db)
    candidate = db.scalars(
        select(Candidate).where(
            Candidate.extraction_run_id == run.id, Candidate.field_path == "security.emd_per_mw"
        )
    ).one()
    approved = pipeline.approvals.approve(
        db, candidate_id=candidate.id, decision="approved", reviewer="Asha"
    )
    assert approved.canonical_fact is not None
    flagged = pipeline.approvals.approve(
        db, candidate_id=candidate.id, decision="flagged", reviewer="Asha", note="unsure"
    )
    assert flagged.canonical_fact is None and flagged.feedback is None
    assert flagged.approval.decision == "flagged" and flagged.approval.note == "unsure"
    facts = list(db.scalars(select(CanonicalFact)))
    assert [fact.is_current for fact in facts] == [False]
    with pytest.raises(ApprovalError):
        pipeline.approvals.approve(
            db, candidate_id=candidate.id, decision="flagged", final_value=1, reviewer="Asha"
        )


def test_a_decision_made_on_an_outdated_view_of_the_field_is_refused(
    pipeline: Pipeline, db: Session
) -> None:
    from core.services.approve import StaleDecisionError

    run = pipeline.extracted_run(db)
    candidate = db.scalars(
        select(Candidate).where(
            Candidate.extraction_run_id == run.id, Candidate.field_path == "security.emd_per_mw"
        )
    ).one()
    first = pipeline.approvals.approve(
        db,
        candidate_id=candidate.id,
        decision="approved",
        reviewer="Asha",
        previous_approval_id=None,
    )
    with pytest.raises(StaleDecisionError):
        pipeline.approvals.approve(
            db,
            candidate_id=candidate.id,
            decision="not_in_document",
            reviewer="Asha",
            previous_approval_id=None,
        )
    second = pipeline.approvals.approve(
        db,
        candidate_id=candidate.id,
        decision="not_in_document",
        reviewer="Asha",
        previous_approval_id=first.approval.id,
    )
    assert second.created and second.approval.supersedes_approval_id == first.approval.id
    with pytest.raises(LookupError):
        pipeline.approvals.approve(
            db,
            candidate_id=candidate.id,
            decision="approved",
            reviewer="Asha",
            object_scope=("tender", "0" * 32),
        )
