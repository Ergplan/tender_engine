"""A provision withdrawn by a later version: the model's `withdrawn` reading becomes a
candidate with no value and the removing words as its evidence; approving it is the
decision that the earlier value no longer applies; the current view and the amendment
screen tell it apart from a value never stated and from a plain null."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Candidate, CanonicalFact, ExtractionRun, ValidationResult
from tender.services.amendments import tender_amendments
from tender.services.current_view import current_view
from tests.conftest import Pipeline
from tests.fixtures.tenders import AMENDMENT_ANSWERS, DEADLINE, EMD, extracted_tender, parsed

WITHDRAWING_PAGES = [
    [
        "AMENDMENT-02",
        "Clause 17: the requirement of Earnest Money Deposit (EMD) per MW stands deleted; "
        "no EMD shall be furnished with the bid.",
        "The last date of bid submission is extended to 15.04.2026 at 15:00 hrs.",
    ]
]
WITHDRAWN = {
    "value": None,
    "withdrawn": True,
    "confidence": 0.9,
    "rationale": "Clause 17 deletes the EMD requirement.",
    "evidence": [{"page_no": 1, "quote": "Earnest Money Deposit (EMD) per MW stands deleted"}],
}


def withdrawing_amendment(pipeline: Pipeline, db: Session) -> tuple[str, Candidate]:
    """The original with its EMD approved, then an amendment that deletes the EMD."""
    tender = extracted_tender(pipeline, db)
    state = pipeline.review_state.for_object(db, "tender", tender.id, 1)
    emd = next(f for f in state.fields if f.field_path == EMD)
    assert emd.candidate is not None and emd.candidate.value is not None
    pipeline.approvals.approve(db, candidate_id=emd.candidate.id, decision="approved", reviewer="A")
    pipeline.sdk.answers = {**AMENDMENT_ANSWERS, "emd_per_mw_inr": WITHDRAWN}
    document = parsed(pipeline, db, WITHDRAWING_PAGES, "amendment-02.pdf")
    pipeline.tenders.add_version(
        db, tender, document, "amendment", date(2026, 4, 1), created_by="pytest"
    )
    pipeline.tenders.start_extraction(db, tender, created_by="pytest", is_fixture=True)
    pipeline.runner.run_until_idle()
    candidate = db.scalars(
        select(Candidate)
        .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
        .where(ExtractionRun.object_version == 2, Candidate.field_path == EMD)
    ).one()
    return tender.id, candidate


def test_a_withdrawal_is_a_located_reading_with_no_value_not_an_absence(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, candidate = withdrawing_amendment(pipeline, db)
    assert (candidate.withdrawn, candidate.value, candidate.status) == (True, None, "validated")
    rules = {
        r.rule_name: r.passed
        for r in db.scalars(
            select(ValidationResult).where(ValidationResult.candidate_id == candidate.id)
        )
    }
    assert rules["withdrawn"] is True and rules["evidence_located"] is True
    assert "type" not in rules, "no value to type"
    # The deadline the same amendment restates is an ordinary reading beside it.
    deadline = db.scalars(
        select(Candidate)
        .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
        .where(ExtractionRun.object_version == 2, Candidate.field_path == DEADLINE)
    ).one()
    assert not deadline.withdrawn and deadline.value == "15.04.2026"
    # The review state carries the flag; a field the amendment does not mention is not_found
    # and not withdrawn.
    state = pipeline.review_state.for_object(db, "tender", tender_id, 2)
    view = next(f for f in state.fields if f.field_path == EMD)
    assert view.candidate is not None and view.candidate.withdrawn
    absent = [f for f in state.fields if f.candidate and f.candidate.status == "not_found"]
    assert absent and not any(f.candidate.withdrawn for f in absent if f.candidate)


def test_approving_the_removal_withdraws_the_value_from_the_current_view_and_says_so(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, candidate = withdrawing_amendment(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    before = next(
        f for f in current_view(db, pipeline.catalog, tender).fields if f.field_path == EMD
    )
    assert before.decided and before.value is not None and before.version_no == 1
    assert not before.withdrawn

    # The amendment screen lists the removal against what stood before.
    projection = tender_amendments(
        db, pipeline.catalog, pipeline.tenders, pipeline.review_state, pipeline.schemas, tender
    )
    (version,) = projection.versions
    removal = next(c for c in version.changes if c.field_path == EMD)
    assert removal.kind == "removed" and version.removed == 1
    assert removal.before is not None and removal.before.value == before.value
    assert removal.before.decision == "approved" and removal.changes_decided

    outcome = pipeline.approvals.approve(
        db, candidate_id=candidate.id, decision="approved", reviewer="Asha"
    )
    assert (
        outcome.canonical_fact is not None
        and outcome.canonical_fact.withdrawn
        and outcome.canonical_fact.value is None
    )
    after = next(
        f for f in current_view(db, pipeline.catalog, tender).fields if f.field_path == EMD
    )
    assert (after.decided, after.value, after.withdrawn) == (True, None, True)
    assert (after.version_no, after.version_kind) == (2, "amendment")
    assert (after.withdrawn_value, after.withdrawn_from_version) == (before.value, 1)
    # Every other decided field is untouched; one never stated is neither decided nor withdrawn.
    others = [f for f in current_view(db, pipeline.catalog, tender).fields if f.field_path != EMD]
    assert not any(f.withdrawn for f in others)
    assert any(not f.decided and not f.withdrawn and f.value is None for f in others)
    facts = db.scalars(select(CanonicalFact).where(CanonicalFact.field_path == EMD)).all()
    assert sorted((f.object_version, f.is_current, f.withdrawn) for f in facts) == [
        (1, True, False),
        (2, True, True),
    ], "the earlier fact stays current at its version; the view projects the withdrawal"


def test_an_edit_with_a_value_says_the_provision_stands_after_all(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, candidate = withdrawing_amendment(pipeline, db)
    outcome = pipeline.approvals.approve(
        db,
        candidate_id=candidate.id,
        decision="edited",
        final_value=500000,
        reviewer="Asha",
        evidence=[{"page_no": 1, "quote": "no EMD shall be furnished with the bid"}],
    )
    assert outcome.canonical_fact is not None and not outcome.canonical_fact.withdrawn
    assert outcome.canonical_fact.value == 500000
    tender = pipeline.tenders.get(db, tender_id)
    field = next(
        f for f in current_view(db, pipeline.catalog, tender).fields if f.field_path == EMD
    )
    assert (field.value, field.withdrawn, field.version_no) == (500000, False, 2)
