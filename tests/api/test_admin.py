"""The reliability dashboard's route: behind the admin token, closed when none is set."""

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from api.main import create_app
from tests.api.test_review_tokens import as_reviewer, link
from tests.api.test_tenders import extracted
from tests.conftest import Pipeline

RELIABILITY = "/api/v1/admin/reliability"


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
