"""Tenders side by side."""

import pytest
from sqlalchemy.orm import Session

from tender.services.compare import MAX_TENDERS, compare_tenders
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE, amended_tender, extracted_tender
from tests.tender.test_rounds import reviewed_tender


def test_fields_as_rows_tenders_as_columns_with_gaps_marked_and_suspended_left_out(
    pipeline: Pipeline, db: Session
) -> None:
    first_id, _ = reviewed_tender(pipeline, db)
    second_id, _ = reviewed_tender(pipeline, db)
    unreviewed = extracted_tender(pipeline, db)
    suspended = pipeline.tenders.get(db, reviewed_tender(pipeline, db)[0])
    amended_tender(pipeline, db, suspended)
    tenders = [
        pipeline.tenders.get(db, first_id),
        pipeline.tenders.get(db, second_id),
        unreviewed,
        suspended,
    ]
    comparison = compare_tenders(db, pipeline.catalog, tenders)
    assert [c.tender_id for c in comparison.columns] == [first_id, second_id, unreviewed.id]
    assert comparison.columns[2].publication_state == "not_published"
    assert [e["tender_id"] for e in comparison.excluded] == [suspended.id]
    assert "suspended" in comparison.excluded[0]["reason"]
    deadline = next(r for r in comparison.rows if r.path == DEADLINE)
    assert len(deadline.cells) == 3
    assert deadline.cells[0] is not None and deadline.cells[0].value == "2026-03-30"
    assert deadline.cells[1] is not None and deadline.cells[1].status == "reviewed"
    assert deadline.cells[2] is None, "a tender with no published view has no cell"
    assert comparison.authority_note.startswith("The tender document")
    with pytest.raises(ValueError, match="at most"):
        compare_tenders(db, pipeline.catalog, tenders * 2)
    assert MAX_TENDERS == 6
