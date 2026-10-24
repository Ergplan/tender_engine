"""Review rounds opened by a version: a reviewed tender that an amendment reaches gets a
round for its reviewer, scoped to what the amendment touched; the earlier decisions carry
forward with their provenance; completing the round takes a snapshot of the whole view."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import AuditLog
from tender.models import ReviewToken
from tender.services.review import complete_review, tender_review
from tender.services.tokens import TokenService
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE, EMD, amended_tender, extracted_tender

SUMMARY = "core.summary.plain_english_summary"
OPTIMISER = "sector.power.common.optimizer_constraints"


def reviewed_tender(pipeline: Pipeline, db: Session) -> tuple[str, ReviewToken]:
    """The original reviewed to completion by Asha: every field with a candidate decided."""
    tender = extracted_tender(pipeline, db)
    tokens = TokenService(pipeline.settings.tenant_id)
    token = tokens.create(db, tender, "Asha", created_by="t")
    review = tender_review(db, pipeline.catalog, pipeline.tenders, pipeline.review_state, tender)
    for field in review.fields:
        if field.current is None or field.decided:
            continue
        candidate = field.entries[field.current].state.candidate
        if candidate is None:
            continue
        located = any(s.char_start is not None for s in candidate.evidence)
        decision = "approved" if candidate.value is not None and located else "not_in_document"
        pipeline.approvals.approve(
            db, candidate_id=candidate.id, decision=decision, reviewer="Asha"
        )
    pipeline.runner.run_until_idle()  # the summary and the derived tables, from the decisions
    review = tender_review(db, pipeline.catalog, pipeline.tenders, pipeline.review_state, tender)
    for field in review.fields:
        if field.current is not None and not field.decided:
            candidate = field.entries[field.current].state.candidate
            if candidate is not None and candidate.status != "not_found":
                pipeline.approvals.approve(
                    db, candidate_id=candidate.id, decision="approved", reviewer="Asha"
                )
    complete_review(db, pipeline.catalog, pipeline.tenders, pipeline.review_state, tender, token)
    db.expire_all()
    assert tender.status == "reviewed" and token.completed_at is not None
    return tender.id, token


def test_an_amendment_on_a_reviewed_tender_opens_a_round_for_its_reviewer(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, first = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    amended_tender(pipeline, db, tender)  # ingests v2, extracts it, runs the queue
    db.expire_all()
    live = db.scalars(
        select(ReviewToken).where(
            ReviewToken.tender_id == tender_id, ReviewToken.revoked_at.is_(None)
        )
    ).all()
    opened = [t for t in live if t.completed_at is None]
    assert len(opened) == 1, "one round, for the reviewer who completed the review"
    (token,) = opened
    assert (token.round_no, token.from_version, token.reviewer_name) == (2, 2, "Asha")
    assert first.completed_at is not None and first.revoked_at is None, "the completed link stays"
    assert tender.status == "in_review"
    row = db.scalars(select(AuditLog).where(AuditLog.action == "open_round")).one()
    assert row.after is not None and row.after["review_token_id"] == token.id

    # The round asks about what v2 touched — the deadline, the summary written from it and
    # any derived table reading it — and carries everything else forward, decided.
    review = tender_review(
        db,
        pipeline.catalog,
        pipeline.tenders,
        pipeline.review_state,
        tender,
        round_no=token.round_no,
        from_version=token.from_version,
    )
    assert review.round is not None
    assert (review.round.round_no, review.round.from_version) == (2, 2)
    in_scope = {f.field_path for f in review.fields if f.in_scope}
    assert DEADLINE in in_scope and SUMMARY in in_scope
    assert EMD not in in_scope, "untouched by v2: carried forward"
    assert review.round.in_scope == len(in_scope) and review.round.carried == len(
        review.fields
    ) - len(in_scope)
    assert review.total == len(in_scope) and review.decided < review.total
    carried = next(f for f in review.fields if f.field_path == EMD)
    entry = carried.entries[carried.current or 0]
    assert carried.decided and entry.state.approval is not None
    assert (entry.state.approval.reviewer, entry.version_no) == ("Asha", 1), "with its provenance"
    assert not review.can_complete, "the deadline's new reading is undecided"

    # Nothing opens twice while the round is live.
    tokens = TokenService(pipeline.settings.tenant_id)
    assert tokens.open_round(db, tender, from_version=2, created_by="t") is None


def test_completing_a_round_needs_only_its_scope_and_snapshots_the_whole_view(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, _ = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    amended_tender(pipeline, db, tender)
    db.expire_all()
    token = db.scalars(
        select(ReviewToken).where(
            ReviewToken.tender_id == tender_id,
            ReviewToken.revoked_at.is_(None),
            ReviewToken.completed_at.is_(None),
        )
    ).one()
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
            decision="approved" if candidate.value is not None and located else "not_in_document",
            reviewer="Asha",
        )
    pipeline.runner.run_until_idle()  # the summary is written again from the new decisions
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
        if field.in_scope and not field.decided and field.current is not None:
            candidate = field.entries[field.current].state.candidate
            if candidate is not None and candidate.status != "not_found":
                pipeline.approvals.approve(
                    db, candidate_id=candidate.id, decision="approved", reviewer="Asha"
                )
    row = complete_review(
        db, pipeline.catalog, pipeline.tenders, pipeline.review_state, tender, token
    )
    assert row.snapshot["round"] == {
        "round_no": 2,
        "from_version": 2,
        "in_scope": review.round.in_scope if review.round else None,
        "carried": review.round.carried if review.round else None,
    }
    assert row.snapshot["view"]["current_version_no"] == 2
    deadline = next(f for f in row.snapshot["view"]["fields"] if f["field_path"] == DEADLINE)
    emd = next(f for f in row.snapshot["view"]["fields"] if f["field_path"] == EMD)
    assert deadline["version_no"] == 2 and emd["version_no"] == 1, "carried value in the view"
    db.expire_all()
    assert tender.status == "reviewed" and token.completed_at is not None


def test_a_reading_of_a_version_the_review_already_saw_opens_no_round(
    pipeline: Pipeline, db: Session
) -> None:
    """A section of the reviewed version read again (a prompt evaluation, a re-read) is
    not a new version reaching the tender: nothing opens, the tender stays reviewed."""
    tender_id, _ = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    pipeline.tenders.start_extraction(
        db, tender, version_no=1, created_by="pytest", groups=["key_dates"], is_fixture=True
    )
    pipeline.runner.run_until_idle()
    db.expire_all()
    assert tender.status == "reviewed"
    assert (
        db.scalar(
            select(ReviewToken).where(
                ReviewToken.tender_id == tender_id, ReviewToken.completed_at.is_(None)
            )
        )
        is None
    )
    assert db.scalar(select(AuditLog).where(AuditLog.action == "open_round")) is None


def test_the_round_command_opens_one_round_and_refuses_a_second(
    pipeline: Pipeline, db: Session
) -> None:
    """`python -m scripts.review_token round`: for a tender reviewed before rounds existed
    (seci-cni-1-700mw v3, 2026-10-13), the operator opens the round by hand."""
    import pytest

    from scripts.review_token import open_round, review_url

    tender_id, first = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    db.commit()
    url = open_round(pipeline.settings, tender.slug or tender.id, 2)
    db.expire_all()
    opened = db.scalars(
        select(ReviewToken).where(
            ReviewToken.tender_id == tender_id,
            ReviewToken.revoked_at.is_(None),
            ReviewToken.completed_at.is_(None),
        )
    ).one()
    assert url == review_url(pipeline.settings.public_base_url, opened.token)
    assert (opened.round_no, opened.from_version, opened.reviewer_name) == (2, 2, "Asha")
    assert first.revoked_at is None, "the completed link stays readable"
    with pytest.raises(SystemExit, match="live link already"):
        open_round(pipeline.settings, tender.slug or tender.id, 2)
