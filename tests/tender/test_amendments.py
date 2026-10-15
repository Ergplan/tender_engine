"""The amendments of a tender as the reviewer checks them: per later version, the fields it
states against what stood before, with that version's reading and its decision."""

from datetime import date

from sqlalchemy.orm import Session

from tender.services.amendments import TenderAmendments, tender_amendments
from tender.services.summary import SUMMARY_FIELD
from tests.conftest import Pipeline
from tests.fixtures.tenders import (
    AMENDMENT_ANSWERS,
    DEADLINE,
    EMD,
    amended_tender,
    extracted_tender,
    parsed,
)
from tests.fixtures.tenders import _answer as answer

RESTATING_PAGES = [
    [
        "CORRIGENDUM-02",
        "The last date of bid submission is extended to 30.04.2026 at 15:00 hrs.",
        "Earnest Money Deposit (EMD) of INR 928000 per MW shall be furnished.",
    ]
]


def amendments(pipeline: Pipeline, db: Session, tender_id: str) -> TenderAmendments:
    tender = pipeline.tenders.get(db, tender_id)
    return tender_amendments(
        db,
        pipeline.catalog,
        pipeline.tenders,
        pipeline.review_state,
        pipeline.schemas,
        tender,
    )


def test_a_tender_with_only_its_original_has_no_amendments(pipeline: Pipeline, db: Session) -> None:
    tender = extracted_tender(pipeline, db)
    result = amendments(pipeline, db, tender.id)
    assert result.versions == [] and result.tender_id == tender.id
    assert result.untouched > 0, "every field stands as the original states it"


def test_an_amendment_lists_what_it_states_against_what_stood_before(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    amended_tender(pipeline, db, tender)
    result = amendments(pipeline, db, tender.id)
    (version,) = result.versions
    assert (version.version_no, version.kind, version.issued_on) == (
        2,
        "amendment",
        date(2026, 3, 20),
    )
    assert [d.filename for d in version.documents] == ["amendment-01.pdf"]
    assert "key_dates" in version.sections_read
    # The summary is written again from the amended record, but it is not something the
    # amendment states, so it is not among its changes.
    assert [c.field_path for c in version.changes] == [DEADLINE]
    (change,) = version.changes
    assert (change.kind, change.section_label, change.value_type) == (
        "changed",
        "Key dates",
        "date",
    )
    assert change.before is not None
    assert (change.before.version_no, change.before.value, change.before.decision) == (
        1,
        "30.03.2026",
        None,
    )
    assert change.entry.version_no == 2 and change.entry.state.candidate is not None
    assert change.entry.state.candidate.value == "15.04.2026"
    assert change.entry.state.candidate.evidence[0].page_no == 1
    assert (change.is_current, change.decided, change.set_aside, change.flagged) == (
        True,
        False,
        False,
        False,
    )
    assert (version.added, version.changed, version.restated) == (0, 1, 0)
    assert (version.decided, version.undecided) == (0, 1)
    # Every other field the view can list (not the summary, not a derived table) stands
    # as the original states it.
    compiled = pipeline.catalog.get("solar")
    derived = {s.name for s in compiled.sections if s.derived}
    listed = [f for f in compiled.fields if f.path != SUMMARY_FIELD and f.section not in derived]
    assert result.untouched == len(listed) - 1


def test_a_decision_before_the_amendment_shows_and_setting_it_aside_brings_the_original_back(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    original = next(
        f
        for f in pipeline.review_state.for_object(db, "tender", tender.id, 1).fields
        if f.field_path == DEADLINE
    )
    assert original.candidate is not None
    pipeline.approvals.approve(
        db,
        candidate_id=original.candidate.id,
        decision="edited",
        final_value="2026-03-31",
        reviewer="Asha",
    )
    amended_tender(pipeline, db, tender)
    (change,) = amendments(pipeline, db, tender.id).versions[0].changes
    assert change.before is not None
    assert (change.before.value, change.before.decision) == ("2026-03-31", "edited"), (
        "what stood before is the reviewer's edit, not the model's reading"
    )
    assert change.kind == "changed" and change.is_current
    assert change.changes_decided, "deciding this reading replaces the reviewer's own value"

    assert change.entry.state.candidate is not None
    pipeline.approvals.approve(
        db,
        candidate_id=change.entry.state.candidate.id,
        decision="not_in_document",
        reviewer="Asha",
    )
    (version,) = amendments(pipeline, db, tender.id).versions
    (change,) = version.changes
    assert (change.decided, change.set_aside, change.is_current) == (True, True, False), (
        "set aside, the amendment's reading no longer decides the field"
    )
    assert (version.decided, version.undecided) == (1, 0)

    pipeline.approvals.approve(
        db,
        candidate_id=change.entry.state.candidate.id,
        decision="flagged",
        note="check",
        reviewer="Asha",
    )
    (change,) = amendments(pipeline, db, tender.id).versions[0].changes
    assert (change.decided, change.flagged, change.is_current) == (False, True, True)


def test_a_restated_value_is_told_apart_from_a_changed_one(pipeline: Pipeline, db: Session) -> None:
    tender = extracted_tender(pipeline, db)
    pipeline.sdk.answers = {
        **AMENDMENT_ANSWERS,
        "bid_submission_deadline": answer(
            "30.04.2026", "The last date of bid submission is extended to 30.04.2026"
        ),
        "emd_per_mw_inr": answer(
            928000, "Earnest Money Deposit (EMD) of INR 928000 per MW shall be furnished."
        ),
    }
    document = parsed(pipeline, db, RESTATING_PAGES, "corrigendum-02.pdf")
    pipeline.tenders.add_version(
        db,
        tender,
        document,
        "corrigendum",
        date(2026, 4, 1),
        created_by="pytest",
        summary_of_change="Deadline extended; EMD restated.",
    )
    pipeline.tenders.start_extraction(db, tender, created_by="pytest", is_fixture=True)
    pipeline.runner.run_until_idle()
    (version,) = amendments(pipeline, db, tender.id).versions
    assert version.summary_of_change == "Deadline extended; EMD restated."
    kinds = {c.field_path: c.kind for c in version.changes}
    assert kinds == {DEADLINE: "changed", EMD: "restated"}
    assert (version.changed, version.restated) == (1, 1)
    # Impact cues: neither field was decided before, and no derived table reads them.
    assert all(not c.changes_decided and c.impacts == [] for c in version.changes)


def test_what_stood_before_skips_a_reading_set_aside_as_not_in_its_document(
    pipeline: Pipeline, db: Session
) -> None:
    """v2's reading of the deadline is set aside, so v1's stands; v3 then changes v1's
    value, not v2's (the independent review of 2026-10-13)."""
    tender = extracted_tender(pipeline, db)
    amended_tender(pipeline, db, tender)
    (change,) = amendments(pipeline, db, tender.id).versions[0].changes
    assert change.entry.state.candidate is not None
    pipeline.approvals.approve(
        db, candidate_id=change.entry.state.candidate.id, decision="not_in_document", reviewer="A"
    )
    pipeline.sdk.answers = {
        **AMENDMENT_ANSWERS,
        "bid_submission_deadline": answer(
            "30.04.2026", "The last date of bid submission is extended to 30.04.2026"
        ),
        "emd_per_mw_inr": answer(
            928000, "Earnest Money Deposit (EMD) of INR 928000 per MW shall be furnished."
        ),
    }
    document = parsed(pipeline, db, RESTATING_PAGES, "corrigendum-02.pdf")
    pipeline.tenders.add_version(
        db, tender, document, "corrigendum", date(2026, 4, 1), created_by="pytest"
    )
    pipeline.tenders.start_extraction(db, tender, created_by="pytest", is_fixture=True)
    pipeline.runner.run_until_idle()
    second, third = amendments(pipeline, db, tender.id).versions
    (deadline,) = [c for c in third.changes if c.field_path == DEADLINE]
    assert deadline.before is not None
    assert (deadline.before.version_no, deadline.before.value, deadline.before.decision) == (
        1,
        "30.03.2026",
        None,
    ), "v2's set-aside reading never stood; v3 changes what v1 states"
    assert deadline.kind == "changed"
    (set_aside,) = second.changes
    assert set_aside.set_aside and set_aside.before is not None
    assert set_aside.before.version_no == 1, "v2 is still shown against v1, as before"
