"""Helpers for the published view: a reviewed tender, a round completed, a later version
that touches a non-critical field."""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tender.models import ReviewToken, Tender
from tender.services.review import complete_review, tender_review
from tests.conftest import Pipeline
from tests.fixtures.tenders import _answer, parsed

PRE_BID = "core.key_dates.pre_bid_meeting_date"
# A version that moves the pre-bid meeting: a key-dates reading, not a critical field.
RESCHEDULE_PAGES = [
    [
        "AMENDMENT-02",
        "The pre-bid meeting is rescheduled to 20.03.2026 at the registered office.",
        "All other terms and conditions remain unchanged.",
    ]
]
RESCHEDULE_ANSWERS: dict[str, dict[str, Any]] = {
    "pre_bid_meeting_date": _answer(
        "20.03.2026", "The pre-bid meeting is rescheduled to 20.03.2026"
    ),
}


def reschedule_version(pipeline: Pipeline, db: Session, tender: Tender) -> None:
    """Version 2: the pre-bid meeting moved, extracted and validated, not reviewed."""
    pipeline.sdk.answers = dict(RESCHEDULE_ANSWERS)
    document = parsed(pipeline, db, RESCHEDULE_PAGES, "amendment-02.pdf")
    pipeline.tenders.add_version(
        db, tender, document, "amendment", date(2026, 3, 18), created_by="pytest"
    )
    pipeline.tenders.start_extraction(db, tender, created_by="pytest", is_fixture=True)
    pipeline.runner.run_until_idle()


def open_round_token(db: Session, tender_id: str) -> ReviewToken:
    return db.scalars(
        select(ReviewToken).where(
            ReviewToken.tender_id == tender_id,
            ReviewToken.revoked_at.is_(None),
            ReviewToken.completed_at.is_(None),
        )
    ).one()


def complete_round(pipeline: Pipeline, db: Session, tender: Tender, reviewer: str = "Asha") -> None:
    """Decide every reading in the open round's scope (approve what is located, else not
    in document) and complete it."""
    token = open_round_token(db, tender.id)
    for _ in range(2):
        review = tender_review(
            db,
            pipeline.catalog,
            pipeline.tenders,
            pipeline.review_state,
            tender,
            round_no=token.round_no,
            from_version=token.from_version,
        )
        for field in review.fields:
            if not field.in_scope or field.decided or field.current is None:
                continue
            candidate = field.entries[field.current].state.candidate
            if candidate is None or candidate.status == "not_found":
                continue
            located = any(s.char_start is not None for s in candidate.evidence)
            pipeline.approvals.approve(
                db,
                candidate_id=candidate.id,
                decision="approved"
                if (candidate.value is not None or candidate.withdrawn) and located
                else "not_in_document",
                reviewer=reviewer,
            )
        pipeline.runner.run_until_idle()
    complete_review(db, pipeline.catalog, pipeline.tenders, pipeline.review_state, tender, token)
    db.expire_all()
