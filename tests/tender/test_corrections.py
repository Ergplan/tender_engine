"""Correction cases and publication holds: a case never changes a value and queues the
field for re-review; a hold suspends publication whatever the review state."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import AuditLog, CanonicalFact
from core.services.identity import Principal
from tender.models import ReviewToken
from tender.services import corrections
from tender.services.changelog import changelog
from tender.services.corrections import TAKEDOWN_COLUMNS, CorrectionError, append_takedown_row
from tender.services.publication import publication_state
from tender.services.published import published_tender
from tests.conftest import Pipeline
from tests.evals.test_gold import completed_review
from tests.fixtures.tenders import DEADLINE, EMD


@pytest.fixture()
def client(pipeline: Pipeline) -> TestClient:
    """The API wired to the pipeline, for the completed review the fixtures need."""
    from api.main import create_app

    return TestClient(
        create_app(
            pipeline.settings, pipeline.schemas, pipeline.storage, pipeline.llm, pipeline.catalog
        )
    )


def _facts(db: Session) -> list[tuple[str, object]]:
    return sorted(
        (f.field_path, f.value)
        for f in db.scalars(select(CanonicalFact).where(CanonicalFact.is_current.is_(True)))
    )


def test_a_case_never_changes_a_value_and_opens_a_round_for_the_last_reviewer(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    reviewed, _ = completed_review(client, pipeline)
    tender = pipeline.tenders.get(db, reviewed["id"])
    before = _facts(db)
    claimant = Principal(
        kind="user",
        tenant_id="free-abc",
        read_tenants=("free-abc", "public"),
        role="reviewer",
        user_id=None,
        name="reader@example.org",
    )
    case = corrections.open_case(
        db,
        pipeline.catalog,
        tender=tender,
        field_path=EMD,
        claimed_error="the EMD is per project, not per MW",
        reasoning="clause 17 reads 'INR 10 lakh per project'",
        claimant=claimant,
    )
    assert case.status == "open" and case.claimant_tenant_id == "free-abc"
    assert case.tenant_id == tender.tenant_id
    assert _facts(db) == before, "a claim changes nothing"
    token = db.scalars(
        select(ReviewToken).where(
            ReviewToken.tender_id == tender.id,
            ReviewToken.revoked_at.is_(None),
            ReviewToken.completed_at.is_(None),
        )
    ).one()
    assert token.round_no == 2 and token.from_version == 1
    assert case.resolution is None
    db.refresh(tender)
    assert tender.status == "in_review"
    audited = db.scalars(select(AuditLog).where(AuditLog.table_name == "correction_case")).all()
    assert len(audited) == 1 and audited[0].after["round"].startswith("round 2 opened")

    # A second claim while the round is open: recorded, no second round.
    second = corrections.open_case(
        db,
        pipeline.catalog,
        tender=tender,
        field_path=DEADLINE,
        claimed_error="the date moved",
        reasoning="amendment 1",
        claimant=None,
        claimant_email="Someone@Example.org",
    )
    assert second.claimant_email == "someone@example.org"
    assert second.resolution and "no round opened" in second.resolution
    assert (
        db.scalar(
            select(func.count())
            .select_from(ReviewToken)
            .where(
                ReviewToken.tender_id == tender.id,
                ReviewToken.completed_at.is_(None),
                ReviewToken.revoked_at.is_(None),
            )
        )
        == 1
    )

    resolved = corrections.resolve_case(
        db, case, accepted=True, resolution="reviewer agreed; re-approved", by="boss@acme.test"
    )
    assert resolved.status == "accepted" and resolved.resolved_by == "boss@acme.test"
    with pytest.raises(CorrectionError, match="already resolved"):
        corrections.resolve_case(db, case, accepted=False, resolution="x", by="y")
    assert _facts(db) == before


def test_the_reviewers_new_approval_changes_the_value_and_the_changelog_shows_it(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    """A case changes nothing; the reviewer's approval, through the normal pipeline, does,
    and the changelog carries the change with its date and the reviewer's role."""
    reviewed, _ = completed_review(client, pipeline)
    tender = pipeline.tenders.get(db, reviewed["id"])
    case = corrections.open_case(
        db,
        pipeline.catalog,
        tender=tender,
        field_path=EMD,
        claimed_error="the figure is 11,60,000 per MW",
        reasoning="clause 17 of the RfS",
        claimant=None,
        claimant_email="reader@example.org",
    )
    before = changelog(db, pipeline.catalog, tender)
    emd_before = next(c for c in before.versions[0].changes if c.field_path == EMD)
    assert emd_before.after == 1000000
    field = next(
        f
        for f in pipeline.review_state.for_object(db, "tender", tender.id, 1).fields
        if f.field_path == EMD
    )
    assert field.candidate is not None
    pipeline.approvals.approve(
        db,
        candidate_id=field.candidate.id,
        decision="edited",
        final_value=1160000,
        reviewer="asha@acme.test",
        note=f"correction case {case.id}",
    )
    after = changelog(db, pipeline.catalog, tender)
    emd_after = next(c for c in after.versions[0].changes if c.field_path == EMD)
    assert emd_after.after == 1160000
    assert emd_after.decided_at is not None and emd_after.decided_at >= case.created_at
    assert emd_after.reviewer_role == "reviewer"
    assert (EMD, 1160000) in _facts(db)
    resolved = corrections.resolve_case(
        db,
        case,
        accepted=True,
        resolution="the reviewer agreed and re-approved",
        by="boss@acme.test",
    )
    assert resolved.status == "accepted" and resolved.resolved_at is not None


def test_a_case_is_refused_without_a_field_a_reason_or_a_claimant(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    reviewed, _ = completed_review(client, pipeline)
    tender = pipeline.tenders.get(db, reviewed["id"])
    with pytest.raises(CorrectionError, match="not a field"):
        corrections.open_case(
            db,
            pipeline.catalog,
            tender=tender,
            field_path="core.x.y",
            claimed_error="e",
            reasoning="r",
            claimant=None,
            claimant_email="a@b.c",
        )
    with pytest.raises(CorrectionError, match="email"):
        corrections.open_case(
            db,
            pipeline.catalog,
            tender=tender,
            field_path=EMD,
            claimed_error="e",
            reasoning="r",
            claimant=None,
        )
    with pytest.raises(CorrectionError, match="reasoning"):
        corrections.open_case(
            db,
            pipeline.catalog,
            tender=tender,
            field_path=EMD,
            claimed_error="e",
            reasoning=" ",
            claimant=None,
            claimant_email="a@b.c",
        )


def test_a_hold_suspends_publication_and_lifting_restores_it(
    client: TestClient, pipeline: Pipeline, db: Session, tmp_path: Path
) -> None:
    reviewed, _ = completed_review(client, pipeline)
    tender = pipeline.tenders.get(db, reviewed["id"])
    assert publication_state(db, pipeline.catalog, tender).state == "published"
    ledger = tmp_path / "KNOWN-GAPS.md"
    ledger.write_text("# Known gaps\n\n| Gap | Why | What closes it |\n| --- | --- | --- |\n")
    arrived = datetime(2026, 10, 17, 9, 30, tzinfo=UTC)
    hold = corrections.place_hold(
        db,
        tender=tender,
        kind="takedown",
        reason="rights-holder request of 2026-10-18",
        requested_by="boss@acme.test",
        requested_at=arrived,
        known_gaps=ledger,
    )
    assert hold.requested_at == arrived and hold.created_at >= arrived
    state = publication_state(db, pipeline.catalog, tender)
    assert state.state == "publication_suspended" and state.suspended_by == ["hold:takedown"]
    assert state.unreviewed_version is not None and state.unreviewed_version.kind == "hold:takedown"
    view = published_tender(db, pipeline.catalog, tender)
    assert view.sections == [] and view.suspension is not None
    assert view.suspension.fields == ["hold:takedown"] and "suspended" in (view.banner or "")
    text = ledger.read_text()
    assert "## Takedowns" in text and "rights-holder request" in text and "| suspended |" in text
    assert "| 2026-10-17 | " in text, "the day the request arrived, from requested_at"
    assert "| Gap | Why | What closes it |" in text, "the file's own table is kept"
    with pytest.raises(CorrectionError, match="unknown hold kind"):
        corrections.place_hold(db, tender=tender, kind="whim", reason="r", requested_by="x")

    lifted = corrections.lift_hold(db, hold, by="boss@acme.test", known_gaps=ledger)
    assert lifted.lifted_at is not None
    assert publication_state(db, pipeline.catalog, tender).state == "published"
    assert "| lifted |" in ledger.read_text()
    with pytest.raises(CorrectionError, match="already lifted"):
        corrections.lift_hold(db, hold, by="x", known_gaps=ledger)
    actions = [
        a.action
        for a in db.scalars(select(AuditLog).where(AuditLog.table_name == "publication_hold"))
    ]
    assert actions == ["insert", "lift"]


def test_the_takedown_row_makes_its_table_once(tmp_path: Path) -> None:
    ledger = tmp_path / "gaps.md"
    when = datetime(2026, 10, 18, tzinfo=UTC)
    append_takedown_row(
        ledger, when=when, tender="seci-x", requested_by="a|b", reason="r", state="suspended"
    )
    append_takedown_row(
        ledger,
        when=when,
        requested=datetime(2026, 10, 17, tzinfo=UTC),
        tender="seci-y",
        requested_by="c",
        reason="s",
        state="lifted",
    )
    text = ledger.read_text()
    header = "| " + " | ".join(TAKEDOWN_COLUMNS) + " |"
    assert text.count("## Takedowns") == 1 and text.count(header) == 1
    # The rows follow the header's columns: one source of truth for both.
    rows = [line for line in text.splitlines() if line.startswith("| 2026-")]
    # An escaped pipe inside a cell is not a column boundary.
    assert all(line.replace("\\|", "").count("|") == len(TAKEDOWN_COLUMNS) + 1 for line in rows)
    assert "| 2026-10-18 |  | seci-x | a\\|b | r | suspended |" in text
    assert text.rstrip().endswith("| 2026-10-18 | 2026-10-17 | seci-y | c | s | lifted |")
