"""The published view: canonical facts only, with provenance; gaps marked, never blank."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import AppUser, Candidate
from tender.services.published import published_tender, reliability_of
from tests.conftest import Pipeline
from tests.fixtures.published import reschedule_version
from tests.fixtures.tenders import DEADLINE, EMD, amended_tender, extracted_tender
from tests.tender.test_rounds import reviewed_tender
from tests.tender.test_withdrawn import withdrawing_amendment


def field(view, path):  # type: ignore[no-untyped-def]
    return next(f for section in view.sections for f in section.fields if f.path == path)


def test_only_canonical_facts_are_published_never_the_candidate(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, _ = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    # The reviewer corrects the EMD: the candidate's figure must appear nowhere.
    candidate = db.scalars(select(Candidate).where(Candidate.field_path == EMD)).first()
    assert candidate is not None and candidate.value == 928000
    pipeline.approvals.approve(
        db, candidate_id=candidate.id, decision="edited", final_value=1000000, reviewer="Asha"
    )
    view = published_tender(db, pipeline.catalog, tender)
    dumped = view.model_dump(mode="json")
    # The page's own words may hold the figure the reviewer corrected (the quote is the
    # evidence); nothing else may: no candidate value, id, rationale or confidence.
    for section in dumped["sections"]:
        for item in section["fields"]:
            item["evidence"] = [
                {k: v for k, v in e.items() if k != "quote"} for e in item["evidence"]
            ]
    text = json.dumps(dumped)
    assert "rationale" not in text and "confidence" not in text and candidate.id not in text
    assert (
        json.dumps(
            next(f for s in dumped["sections"] for f in s["fields"] if f["path"] == EMD)
        ).count("928000")
        == 0
    )
    emd = field(view, EMD)
    assert emd.value == 1000000 and emd.status == "reviewed"
    assert emd.version_no == 1 and emd.set_by == "original"
    assert emd.evidence and emd.evidence[0].page_no == 3 and emd.evidence[0].filename == "rfs.pdf"
    assert emd.reviewed_at is not None and emd.reviewer_role == "reviewer"
    assert view.publication.state == "published" and view.banner is None
    assert view.reviewed_at is not None and view.reviewer_role == "reviewer"
    assert view.authority_note.startswith("The tender document is the authoritative source")
    assert all(section.name != "summary" for section in view.sections)


def test_the_reviewer_role_comes_from_the_user_record_when_there_is_one(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, _ = reviewed_tender(pipeline, db)
    db.add(
        AppUser(
            tenant_id="ergplan",
            created_by="t",
            email="asha",
            display_name="Asha",
            role="approver",
        )
    )
    db.commit()
    view = published_tender(db, pipeline.catalog, pipeline.tenders.get(db, tender_id))
    assert view.reviewer_role == "approver" and field(view, DEADLINE).reviewer_role == "approver"


def test_a_field_without_a_decision_is_a_marked_gap_with_the_likely_page(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    not_yet = published_tender(db, pipeline.catalog, tender)
    assert not_yet.publication.state == "not_published" and not_yet.sections == []
    assert not_yet.banner and "no completed review" in not_yet.banner
    tender_id, _ = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    reschedule_version(pipeline, db, tender)
    view = published_tender(db, pipeline.catalog, tender)
    assert view.publication.state == "update_pending" and view.banner
    assert "version 2" in view.banner and "possibly superseded" in view.banner
    pre_bid = field(view, "core.key_dates.pre_bid_meeting_date")
    assert pre_bid.status == "possibly_superseded" and pre_bid.value is not None
    # The reviewer clears a decision: the field is undecided again and shown as a gap, with
    # the page its reading cites but not the reading.
    state = pipeline.review_state.for_object(db, "tender", tender.id, 1)
    deadline = next(f for f in state.fields if f.field_path == DEADLINE)
    assert deadline.candidate is not None
    pipeline.approvals.approve(
        db, candidate_id=deadline.candidate.id, decision="cleared", reviewer="Asha"
    )
    view = published_tender(db, pipeline.catalog, tender)
    gaps = [f for section in view.sections for f in section.fields if f.status == "not_reviewed"]
    assert gaps, "a field the reviewer never decided is shown as a gap"
    assert all(g.gap is not None and "not reviewed" in g.gap.reason for g in gaps)
    assert all(g.value is None and g.evidence == [] for g in gaps)
    cleared = field(view, DEADLINE)
    assert cleared.status == "not_reviewed" and cleared.gap is not None
    assert cleared.gap.likely_page == 2 and cleared.gap.document_id is not None
    assert "2026-03-30" not in json.dumps(cleared.model_dump(mode="json"))
    absent = [
        f
        for section in view.sections
        for f in section.fields
        if f.gap and "does not state" in f.gap.reason
    ]
    assert absent, "a field decided as not in the document says so"


def test_a_suspended_tender_publishes_no_values_only_the_suspension(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, _ = reviewed_tender(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    amended_tender(pipeline, db, tender)
    view = published_tender(db, pipeline.catalog, tender)
    assert view.publication.state == "publication_suspended" and view.sections == []
    assert view.suspension is not None
    assert view.suspension.fields == [DEADLINE] and view.suspension.version_no == 2
    assert len(view.suspension.document_ids) == 1 and view.suspension.issued_on == "2026-03-20"
    assert view.banner and "suspended" in view.banner and DEADLINE in view.banner
    assert "15.04.2026" not in json.dumps(view.model_dump(mode="json"))


def test_a_withdrawn_fact_is_published_as_withdrawn_with_the_removing_version(
    pipeline: Pipeline, db: Session
) -> None:
    tender_id, removal = withdrawing_amendment(pipeline, db)
    tender = pipeline.tenders.get(db, tender_id)
    # Review the original to completion, then the round the amendment opened.
    from tender.services.tokens import TokenService
    from tests.tender.test_rounds import complete_review, tender_review

    token = TokenService(pipeline.settings.tenant_id).create(db, tender, "Asha", created_by="t")
    for _ in range(2):
        review = tender_review(
            db, pipeline.catalog, pipeline.tenders, pipeline.review_state, tender
        )
        for item in review.fields:
            if item.decided or item.current is None:
                continue
            candidate = item.entries[item.current].state.candidate
            if candidate is None or candidate.status == "not_found":
                continue
            located = any(s.char_start is not None for s in candidate.evidence)
            pipeline.approvals.approve(
                db,
                candidate_id=candidate.id,
                decision="approved"
                if (candidate.value is not None or candidate.withdrawn) and located
                else "not_in_document",
                reviewer="Asha",
            )
        pipeline.runner.run_until_idle()
    complete_review(db, pipeline.catalog, pipeline.tenders, pipeline.review_state, tender, token)
    db.expire_all()
    view = published_tender(db, pipeline.catalog, tender)
    assert view.publication.state == "published" and view.reviewed_version == 2
    emd = field(view, EMD)
    assert emd.withdrawn and emd.value is None and emd.version_no == 2
    assert emd.withdrawn_from_version == 1 and emd.set_by == "amendment"
    assert emd.gap is not None and "withdrawn by version 2" in emd.gap.reason
    assert emd.evidence and "stands deleted" in emd.evidence[0].quote
    assert removal.id not in json.dumps(view.model_dump(mode="json"))


def test_reliability_reads_the_latest_plain_evaluation_or_says_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert reliability_of("ergplan", "solar", tmp_path) is None
    (tmp_path / "20260101T000000Z-ergplan-latest.json").write_text(
        json.dumps(
            {
                "tenant_id": "ergplan",
                "made_at": "2026-01-01T00:00:00+00:00",
                "summary": {
                    "by_type": {"solar": {"n": 85, "accuracy": 0.97, "evidence_accuracy": 1.0}}
                },
            }
        )
    )
    (tmp_path / "20260102T000000Z-ergplan-latest.json").write_text(
        json.dumps({"tenant_id": "other", "made_at": "x", "summary": {}})
    )
    figures = reliability_of("ergplan", "solar", tmp_path)
    assert figures is not None
    assert (figures.value_accuracy, figures.evidence_accuracy, figures.n_fields) == (0.97, 1.0, 85)
    assert figures.as_of == "2026-01-01T00:00:00+00:00"
    unknown = reliability_of("ergplan", "wind", tmp_path)
    assert unknown is not None and unknown.value_accuracy is None and unknown.n_fields == 0
