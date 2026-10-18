"""What each principal may reach through the public proxy: the role matrix, API keys with
their limits and metering, and the tenant wall under row-level security."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import create_app
from core.db import make_engine, make_session_factory
from core.models import UsageRecord
from core.services.identity import IdentityService
from tests.api.test_auth import PUBLIC, SETTINGS, sign_in
from tests.api.test_tenders import create
from tests.conftest import Pipeline, add_tenant
from tests.fixtures.oidc import FakeOidc, account


@pytest.fixture()
def stack(make_pipeline: Callable[..., Pipeline]) -> tuple[Pipeline, TestClient, FakeOidc]:
    pipeline = make_pipeline(**SETTINGS)
    oidc = FakeOidc(
        {
            "code-boss": account("boss@acme.test"),
            "code-asha": account("asha@acme.test"),
            "code-ravi": account("ravi@acme.test"),
        }
    )
    app = create_app(
        pipeline.settings,
        pipeline.schemas,
        pipeline.storage,
        pipeline.llm,
        pipeline.catalog,
        oidc=oidc,
    )
    return pipeline, TestClient(app, base_url="https://testserver", follow_redirects=False), oidc


def _browser(stack: tuple[Pipeline, TestClient, FakeOidc], code: str) -> TestClient:
    app = stack[1].app
    client = TestClient(app, base_url="https://testserver", follow_redirects=False)
    assert sign_in(client, code).status_code == 302
    return client


def _key(stack: tuple[Pipeline, TestClient, FakeOidc], **body: Any) -> str:
    boss = _browser(stack, "code-boss")
    made = boss.post("/api/v1/admin/api-keys", json={"name": "k", **body}, headers=PUBLIC)
    assert made.status_code == 201, made.text
    secret: str = made.json()["secret"]
    return secret


def test_the_role_matrix_on_the_public_side(stack: tuple[Pipeline, TestClient, FakeOidc]) -> None:
    pipeline, internal, _ = stack
    tender = create(internal)
    reviewer = _browser(stack, "code-asha")
    assert reviewer.get("/api/v1/tenders", headers=PUBLIC).status_code == 200
    assert reviewer.get(f"/api/v1/tenders/{tender['id']}", headers=PUBLIC).status_code == 200
    assert reviewer.get("/api/v1/schemas/tender/solar", headers=PUBLIC).status_code == 200
    # A reviewer decides on fields (the body is wrong on purpose: 422 means the route was
    # reached) and may not mint links, run extractions or reach the admin.
    assert reviewer.post("/api/v1/approvals", json={}, headers=PUBLIC).status_code == 422
    for method, path in (
        ("POST", "/api/v1/review-tokens"),
        ("POST", f"/api/v1/tenders/{tender['id']}/extract"),
        ("POST", "/api/v1/tenders"),
        ("GET", "/api/v1/admin/reliability"),
        ("POST", "/api/v1/admin/gold"),
        ("DELETE", "/api/v1/admin/api-keys/" + "0" * 32),
    ):
        response = reviewer.request(method, path, json={}, headers=PUBLIC)
        assert response.status_code == 403, (method, path, response.text)
    # An approver may make gold (the route then refuses: no completed review), an admin everything.
    boss = _browser(stack, "code-boss")
    promoted = boss.patch(
        f"/api/v1/admin/users/{_user_id(boss, 'ravi@acme.test', invite=True)}",
        json={"role": "approver"},
        headers=PUBLIC,
    )
    assert promoted.status_code == 200
    approver = _browser(stack, "code-ravi")
    gold = approver.post("/api/v1/admin/gold", json={"tender": tender["id"]}, headers=PUBLIC)
    assert gold.status_code != 403, gold.text
    assert approver.get("/api/v1/admin/users", headers=PUBLIC).status_code == 403
    assert (
        boss.post(f"/api/v1/tenders/{tender['id']}/extract", json={}, headers=PUBLIC).status_code
        != 403
    )
    # Inside the deployment nothing changed: no identity, no limit.
    assert internal.get("/api/v1/tenders").status_code == 200


def _user_id(boss: TestClient, email: str, *, invite: bool) -> str:
    if invite:
        made = boss.post(
            "/api/v1/admin/users",
            json={"email": email, "display_name": email, "role": "reviewer"},
            headers=PUBLIC,
        )
        assert made.status_code == 201, made.text
    users = boss.get("/api/v1/admin/users", headers=PUBLIC).json()
    found: str = next(u["id"] for u in users if u["email"] == email)
    return found


def test_an_api_key_reads_is_metered_rate_limited_and_never_writes(
    stack: tuple[Pipeline, TestClient, FakeOidc],
) -> None:
    pipeline, internal, _ = stack
    tender = create(internal)
    secret = _key(stack, scopes=["read"], rate_limit_per_min=3)
    bearer = {**PUBLIC, "Authorization": f"Bearer {secret}"}
    client = TestClient(internal.app, base_url="https://testserver")
    assert client.get("/api/v1/auth/me", headers=bearer).json()["kind"] == "api_key"
    assert client.get(f"/api/v1/tenders/{tender['id']}", headers=bearer).status_code == 200
    forbidden = client.post("/api/v1/approvals", json={}, headers=bearer)
    assert forbidden.status_code == 403 and forbidden.json()["error_type"] == "not_allowed"
    assert (
        client.post(f"/api/v1/tenders/{tender['id']}/model", json={}, headers=bearer).status_code
        == 403
    )
    assert client.get("/api/v1/admin/users", headers=bearer).status_code == 403
    # Three calls were metered (me, tender, the refused approval is not: policy comes first);
    # the fourth is over the minute's limit.
    assert client.get("/api/v1/tenders", headers=bearer).status_code == 200
    limited = client.get("/api/v1/tenders", headers=bearer)
    assert limited.status_code == 429 and limited.json()["error_type"] == "rate_limited"
    with pipeline.session_factory() as session:
        rows = list(session.scalars(select(UsageRecord).order_by(UsageRecord.created_at)))
    assert [r.tool for r in rows] == [
        "GET /auth/me",
        "GET /tenders/{tender_id}",
        "GET /tenders",
        "GET /tenders",
    ]
    assert [r.status for r in rows] == [200, 200, 200, 429] and {r.tier for r in rows} == {"api"}
    assert rows[-1].detail == "rate_limited"
    bad = client.get("/api/v1/tenders", headers={**PUBLIC, "Authorization": "Bearer tie_live_nope"})
    assert bad.status_code == 401 and bad.json()["error_type"] == "api_key_invalid"


def test_a_key_with_the_model_scope_reaches_the_model_route(
    stack: tuple[Pipeline, TestClient, FakeOidc],
) -> None:
    _, internal, _ = stack
    tender = create(internal)
    secret = _key(stack, scopes=["read", "model"])
    bearer = {**PUBLIC, "Authorization": f"Bearer {secret}"}
    client = TestClient(internal.app, base_url="https://testserver")
    response = client.post(f"/api/v1/tenders/{tender['id']}/model", json={}, headers=bearer)
    assert response.status_code != 403, response.text


def test_another_tenants_key_sees_none_of_our_tenders(
    stack: tuple[Pipeline, TestClient, FakeOidc],
) -> None:
    pipeline, internal, _ = stack
    tender = create(internal)
    add_tenant(pipeline.settings, "other")
    other = make_session_factory(make_engine(pipeline.settings), "other")
    with other() as theirs:
        _, secret = IdentityService(pipeline.settings).create_api_key(
            theirs, "other", "theirs", [], created_by="them"
        )
    bearer = {**PUBLIC, "Authorization": f"Bearer {secret}"}
    client = TestClient(internal.app, base_url="https://testserver")
    assert client.get("/api/v1/auth/me", headers=bearer).json()["tenant_id"] == "other"
    assert client.get("/api/v1/tenders", headers=bearer).json() == []
    assert client.get(f"/api/v1/tenders/{tender['id']}", headers=bearer).status_code == 404
    with other() as theirs:
        assert {r.tenant_id for r in theirs.scalars(select(UsageRecord))} == {"other"}
