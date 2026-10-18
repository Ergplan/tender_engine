"""The publication state machine."""

from sqlalchemy.orm import Session

from tender.services.publication import CRITICAL_FIELDS, fields_touched, publication_state
from tests.conftest import Pipeline
from tests.fixtures.published import PRE_BID, complete_round, reschedule_version
from tests.fixtures.tenders import DEADLINE, amended_tender, extracted_tender
from tests.tender.test_rounds import reviewed_tender


def test_not_published_until_a_review_is_completed_then_published(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    before = publication_state(db, pipeline.catalog, tender)
    assert (before.state, before.reviewed_version, before.current_version) == (
        "not_published",
        None,
        1,
    )
    tender_id, _ = reviewed_tender(pipeline, db)
    after = publication_state(db, pipeline.catalog, pipeline.tenders.get(db, tender_id))
    assert (after.state, after.reviewed_version, after.current_version) == ("published", 1, 1)
    assert after.unreviewed_version is None and after.possibly_superseded == []


def test_an_unreviewed_version_that_touches_a_plain_field_leaves_the_view_update_pending(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, _ = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    reschedule_version(pipeline, db, tender)
    state = publication_state(db, pipeline.catalog, tender)
    assert state.state == "update_pending"
    assert (state.reviewed_version, state.current_version) == (1, 2)
    assert state.unreviewed_version is not None
    assert (state.unreviewed_version.version_no, state.unreviewed_version.kind) == (2, "amendment")
    assert state.unreviewed_version.issued_on is not None
    assert len(state.unreviewed_version.document_ids) == 1
    assert PRE_BID in state.possibly_superseded and DEADLINE not in state.possibly_superseded
    assert state.suspended_by == []
    assert fields_touched(db, tender, 2) == set(state.possibly_superseded)
    # Once the round opened by the version is completed, the view is published again.
    complete_round(pipeline, db, tender)
    done = publication_state(db, pipeline.catalog, tender)
    assert (done.state, done.reviewed_version, done.current_version) == ("published", 2, 2)


def test_an_unreviewed_version_that_touches_a_critical_field_suspends_publication(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, _ = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    amended_tender(pipeline, db, tender)
    state = publication_state(db, pipeline.catalog, tender)
    assert state.state == "publication_suspended"
    assert state.suspended_by == [DEADLINE] and DEADLINE in CRITICAL_FIELDS
    assert DEADLINE in state.possibly_superseded
    assert state.unreviewed_version is not None and state.unreviewed_version.version_no == 2
