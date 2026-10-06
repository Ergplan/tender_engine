"""The reliability dashboard's route: behind the admin token, closed when none is set."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import evals.gold
import evals.report
import evals.runner
from api.main import create_app
from tests.api.test_review_tokens import as_reviewer, link
from tests.api.test_tenders import extracted
from tests.conftest import Pipeline
from tests.evals.test_gold import EMD, completed_review

RELIABILITY = "/api/v1/admin/reliability"
ADMIN = {"X-Admin-Token": "s3cret-admin"}


@pytest.fixture()
def eval_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Gold records, results and reports written under tmp_path, not into the repository."""
    monkeypatch.setattr(evals.gold, "GOLD_ROOT", tmp_path / "gold")
    monkeypatch.setattr(evals.runner, "RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(evals.report, "RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(evals.report, "DEFAULT_OUT", tmp_path / "RELIABILITY-REPORT.md")
    monkeypatch.setattr(evals.report, "DEFAULT_LOG", tmp_path / "REVIEW-LOG.md")
    return tmp_path


def app_for(pipeline: Pipeline) -> TestClient:
    return TestClient(
        create_app(
            pipeline.settings, pipeline.schemas, pipeline.storage, pipeline.llm, pipeline.catalog
        )
    )


def test_the_route_needs_the_admin_token_and_a_review_link_does_not_open_it(
    make_pipeline: Callable[..., Pipeline],
) -> None:
    pipeline = make_pipeline(admin_token="s3cret-admin")
    client = app_for(pipeline)
    tender = extracted(client, pipeline)
    token = link(client, tender["id"])["token"]
    for headers in (
        {},
        {"X-Admin-Token": "wrong"},
        as_reviewer(token),
        {**as_reviewer(token), "X-Admin-Token": "wrong"},
    ):
        response = client.get(RELIABILITY, headers=headers)
        assert response.status_code == 401, headers
        assert response.json()["error_type"] == "admin_token_required"
    # The admin token opens the dashboard and nothing else.
    opened = client.get(RELIABILITY, headers={"X-Admin-Token": "s3cret-admin"})
    assert opened.status_code == 200, opened.text
    body: dict[str, Any] = opened.json()
    assert body["tenders_in_set"] == {"solar": 1} and body["gold_records"] >= 0
    assert set(body) >= {"summary", "stability", "tenders", "prompt_comparison", "generated_at"}
    assert body["stability"]["met"] is False
    assert body["summary"]["by_type_field"] == {} or isinstance(
        body["summary"]["by_type_field"], dict
    )
    assert (
        client.get(
            f"/api/v1/tenders/{tender['id']}/review",
            headers={"X-Admin-Token": "s3cret-admin", **{"X-Public-Request": "1"}},
        ).status_code
        == 401
    )


def test_the_route_is_closed_when_no_admin_token_is_configured(
    make_pipeline: Callable[..., Pipeline],
) -> None:
    client = app_for(make_pipeline(admin_token=""))
    for headers in ({}, {"X-Admin-Token": ""}, {"X-Admin-Token": "anything"}):
        response = client.get(RELIABILITY, headers=headers)
        assert (
            response.status_code == 401 and response.json()["error_type"] == "admin_token_required"
        )


def test_gold_eval_and_feedback_are_api_operations(
    make_pipeline: Callable[..., Pipeline], eval_roots: Path
) -> None:
    pipeline = make_pipeline(admin_token="s3cret-admin")
    client = app_for(pipeline)
    tender = extracted(client, pipeline)
    tid = tender["id"]
    # No completed review yet: nothing to make gold from, nothing to score.
    early = client.post("/api/v1/admin/gold", json={"tender_id": tid}, headers=ADMIN)
    assert early.status_code == 422 and "no completed review" in early.json()["detail"]
    assert client.post("/api/v1/admin/evals", json={}, headers=ADMIN).status_code == 422
    assert (
        client.post("/api/v1/admin/gold", json={"tender_id": "x" * 32}, headers=ADMIN).status_code
        == 404
    )
    assert client.post("/api/v1/admin/gold", json={"tender_id": tid}).status_code == 401

    completed_review(client, pipeline, tender)
    made = client.post("/api/v1/admin/gold", json={"tender_id": tid}, headers=ADMIN)
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["tender_type"] == "solar" and body["decided"] == body["total"] > 0
    assert Path(body["path"]).is_relative_to(eval_roots) and Path(body["path"]).exists()
    assert (eval_roots / "RELIABILITY-REPORT.md").exists() and (
        eval_roots / "REVIEW-LOG.md"
    ).exists()

    shown = client.get(RELIABILITY, headers=ADMIN).json()
    assert shown["gold_records"] == 1 and shown["tenders"][0]["edited_fields"] == [EMD]
    assert shown["summary"]["misses"][0]["field_path"] == EMD

    scored = client.post("/api/v1/admin/evals", json={}, headers=ADMIN)
    assert scored.status_code == 201, scored.text
    assert scored.json()["status"] == "scored" and scored.json()["summary"]["scored"] > 0
    assert Path(scored.json()["results_file"]).is_relative_to(eval_roots / "results")

    # A prompt evaluation: queued runs, then scored by their ids and nothing else.
    bad = client.post("/api/v1/admin/evals", json={"prompt": "nope/v1"}, headers=ADMIN)
    assert bad.status_code == 422 and "no run queued" in bad.json()["detail"]
    queued = client.post("/api/v1/admin/evals", json={"prompt": "commercial/v2"}, headers=ADMIN)
    assert queued.status_code == 201, queued.text
    run_ids = sum(queued.json()["queued"].values(), [])
    assert queued.json()["status"] == "queued" and len(run_ids) == 1
    pipeline.runner.run_until_idle()
    rescored = client.post("/api/v1/admin/evals", json={"run_ids": run_ids}, headers=ADMIN)
    assert rescored.status_code == 201, rescored.text
    summary = rescored.json()["summary"]
    assert set(summary["by_section"]) == {"commercial"}

    feedback = client.get("/api/v1/admin/feedback", headers=ADMIN)
    assert feedback.status_code == 200
    assert feedback.json()["corrections"] == 1 and feedback.json()["rows"][0]["field_path"] == EMD
    assert "# Feedback report" in feedback.json()["markdown"]
