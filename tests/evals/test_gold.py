"""A completed review becomes a gold record; the record scores the candidates it was made
from; the report and the log are written from it."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from evals.gold import NoCompletedReview, build_gold, load_gold, write_gold
from evals.report import render_log, render_report, tender_lines, timing
from evals.runner import candidates_in_review, score_record, summarise
from tender.models import Tender
from tests.api.test_review_tokens import (
    SUMMARY,
    as_reviewer,
    current,
    decide,
    decide_others,
    link,
    review,
    with_amendment,
)
from tests.api.test_tenders import extracted
from tests.conftest import Pipeline

EMD = "core.guarantees.emd_per_mw_inr"
DEADLINE = "core.key_dates.bid_submission_deadline"


def completed_review(
    client: TestClient, pipeline: Pipeline, tender: dict[str, Any] | None = None
) -> tuple[dict[str, Any], str]:
    tender = tender or extracted(client, pipeline)
    tid = tender["id"]
    token = link(client, tid)["token"]
    body = review(client, tid, token)
    # The EMD is corrected (well beyond the half-percent band), the deadline approved as
    # read, the rest approved or marked absent.
    assert (
        decide(client, token, current(body, EMD), "edited", final_value=1000000).status_code == 201
    )
    decide_others(client, token, body, skip=(EMD,))
    pipeline.runner.run_until_idle()  # the summary is written again from the decisions
    body = review(client, tid, token)
    assert decide(client, token, current(body, SUMMARY), "approved").status_code == 201
    done = client.post(f"/api/v1/tenders/{tid}/complete-review", headers=as_reviewer(token))
    assert done.status_code == 201, done.text
    return tender, token


def test_a_gold_record_is_made_from_the_completed_review_only(
    client: TestClient,
    pipeline: Pipeline,
    db,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    tender = extracted(client, pipeline)
    row = db.scalars(select(Tender).where(Tender.id == tender["id"])).one()
    with pytest.raises(NoCompletedReview):
        build_gold(db, pipeline.catalog, row)


def test_the_gold_record_keeps_decisions_evidence_pages_and_the_candidate_judged(
    client: TestClient,
    pipeline: Pipeline,
    db,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    tender, _ = completed_review(client, pipeline)
    row = db.scalars(select(Tender).where(Tender.id == tender["id"])).one()
    record = build_gold(db, pipeline.catalog, row)
    assert record.reviewer == "Asha Rao" and record.reviewed_version == 1
    assert record.tender_type == "solar" and record.slug == row.id  # no slug: named by id
    decided = [f for f in record.fields if f.decision]
    assert len(decided) == len(record.fields) and all(f.decided_at for f in decided)
    emd = record.field(EMD)
    assert emd is not None and emd.decision == "edited" and emd.final_value == 1000000
    assert emd.candidate is not None and emd.candidate.value == 928000
    assert emd.candidate.prompt_version and emd.candidate.pages and emd.evidence_pages
    deadline = record.field(DEADLINE)
    assert deadline is not None and deadline.decision == "approved"
    assert (
        deadline.final_value == "2026-03-30" and deadline.evidence_pages == deadline.candidate.pages
    )  # type: ignore[union-attr]
    # A field marked absent keeps the candidate it was judged on: the model's null reading.
    absent = [f for f in decided if f.decision == "not_in_document"]
    assert absent and all(f.final_value is None for f in absent)
    assert all(f.candidate is None or f.candidate.value is None for f in absent)

    path = write_gold(record, tmp_path)
    assert path == tmp_path / "solar" / f"{record.slug}.yaml"
    assert path.read_text().startswith("# Gold record of")
    assert load_gold(path) == record

    # Scored against the candidates it was made from: everything right but the edit.
    found = candidates_in_review(db, pipeline.review_state, record)
    scores = score_record(record, found, pipeline.catalog, pipeline.schemas)
    summary = summarise(scores)
    misses = {m["field_path"]: m["outcome"] for m in summary.misses}
    assert misses == {EMD: "wrong_value"}
    assert summary.evidence_accuracy == 1.0 and summary.needs_judgement >= 1
    # A section the run did not read again is not scored when only another is asked for.
    assert all(
        s.section == "guarantees"
        for s in score_record(record, found, pipeline.catalog, pipeline.schemas, {"guarantees"})
    )

    sitting = timing(db, pipeline.settings.tenant_id, record)
    assert sitting is not None and sitting.sittings == 1 and sitting.decisions >= len(decided)
    lines = tender_lines([record], scores, {record.slug: sitting})
    assert lines[0].edited == 1 and lines[0].edited_fields == [EMD]
    assert lines[0].notable_misses == [f"{EMD} (wrong_value)"]
    report = render_report([record], scores, {"solar": 1, "wind": 2}, {record.slug: sitting}, [])
    assert "| solar | 1 | 1 | " in report and "**Not met.**" in report
    assert f"`{EMD}`" in report and "fewer than 2 reviewed tenders for: wind" in report
    log = render_log(lines)
    assert f"| {record.slug} | solar | Asha Rao |" in log and f"1: `{EMD}`" in log


def test_a_field_decided_on_an_earlier_version_keeps_its_decision_in_the_gold_record(
    client: TestClient,
    pipeline: Pipeline,
    db,  # type: ignore[no-untyped-def]
) -> None:
    """An amendment moves the deadline; the other fields are shown, and decided, from the
    original version. The record of the review completed at version 2 holds them all."""
    tender = with_amendment(client, pipeline)
    tid = tender["id"]
    token = link(client, tid)["token"]
    body = review(client, tid, token)
    decide_others(client, token, body)
    pipeline.runner.run_until_idle()
    body = review(client, tid, token)
    assert decide(client, token, current(body, SUMMARY), "approved").status_code == 201
    done = client.post(f"/api/v1/tenders/{tid}/complete-review", headers=as_reviewer(token))
    assert done.status_code == 201, done.text
    row = db.scalars(select(Tender).where(Tender.id == tid)).one()
    record = build_gold(db, pipeline.catalog, row)
    assert record.reviewed_version == 2
    deadline = record.field(DEADLINE)
    assert deadline is not None and deadline.version_no == 2 and deadline.decision == "approved"
    assert deadline.final_value == "2026-04-15"
    inherited = [f for f in record.fields if f.version_no == 1 and f.decision]
    assert inherited and all(f.candidate is not None for f in inherited)
    assert sum(1 for f in record.fields if f.decision) == done.json()["snapshot"]["decided"]
