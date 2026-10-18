"""An admin's routes: users, API keys (shown once), review links, usage."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from tests.api.test_auth import PUBLIC, SETTINGS, sign_in
from tests.api.test_tenders import create
from tests.conftest import Pipeline
from tests.fixtures.oidc import FakeOidc, account


@pytest.fixture()
def admin(make_pipeline: Callable[..., Pipeline]) -> TestClient:
    pipeline = make_pipeline(**SETTINGS)
    oidc = FakeOidc(
        {"code-boss": account("boss@acme.test"), "code-asha": account("asha@acme.test")}
    )
    app = create_app(
        pipeline.settings,
        pipeline.schemas,
        pipeline.storage,
        pipeline.llm,
        pipeline.catalog,
        oidc=oidc,
    )
    client = TestClient(app, base_url="https://testserver", follow_redirects=False)
    assert sign_in(client, "code-boss").status_code == 302
    return client


def test_users_are_invited_listed_and_changed(admin: TestClient) -> None:
    made = admin.post(
        "/api/v1/admin/users",
        json={"email": "Ravi@acme.test", "display_name": "Ravi", "role": "approver"},
        headers=PUBLIC,
    )
    assert made.status_code == 201, made.text
    assert (made.json()["email"], made.json()["role"], made.json()["status"]) == (
        "ravi@acme.test",
        "approver",
        "active",
    )
    again = admin.post(
        "/api/v1/admin/users",
        json={"email": "ravi@acme.test", "display_name": "Ravi"},
        headers=PUBLIC,
    )
    assert again.status_code == 409
    listed = admin.get("/api/v1/admin/users", headers=PUBLIC).json()
    assert [u["email"] for u in listed] == ["boss@acme.test", "ravi@acme.test"]
    changed = admin.patch(
        f"/api/v1/admin/users/{made.json()['id']}", json={"status": "disabled"}, headers=PUBLIC
    )
    assert changed.status_code == 200 and changed.json()["status"] == "disabled"
    assert (
        admin.patch("/api/v1/admin/users/" + "0" * 32, json={}, headers=PUBLIC).status_code == 404
    )


def test_api_keys_are_shown_once_listed_and_revoked(admin: TestClient) -> None:
    made = admin.post(
        "/api/v1/admin/api-keys",
        json={"name": "Partner feed", "scopes": ["read", "model"], "rate_limit_per_min": 5},
        headers=PUBLIC,
    )
    assert made.status_code == 201, made.text
    secret = made.json()["secret"]
    key = made.json()["key"]
    assert secret.startswith("tie_live_") and key["prefix"] == secret[:12]
    assert key["scopes"] == ["model", "read"] and key["rate_limit_per_min"] == 5
    assert key["created_by"] == "boss@acme.test"
    listed = admin.get("/api/v1/admin/api-keys", headers=PUBLIC).json()
    assert len(listed) == 1 and "secret" not in listed[0] and "key_hash" not in listed[0]
    revoked = admin.delete(f"/api/v1/admin/api-keys/{key['id']}", headers=PUBLIC)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
    assert admin.delete("/api/v1/admin/api-keys/" + "0" * 32, headers=PUBLIC).status_code == 404
    # A client without the admin's cookie: the revoked key alone.
    machine = TestClient(admin.app, base_url="https://testserver")
    with_key = machine.get(
        "/api/v1/tenders", headers={**PUBLIC, "Authorization": f"Bearer {secret}"}
    )
    assert with_key.status_code == 401 and with_key.json()["error_type"] == "api_key_invalid"


def test_an_admin_mints_a_review_link_and_reads_usage(admin: TestClient) -> None:
    tender = create(admin)
    minted = admin.post(
        "/api/v1/admin/review-tokens",
        json={"tender": tender["id"], "reviewer_name": "Asha Rao"},
        headers=PUBLIC,
    )
    assert minted.status_code == 201, minted.text
    body = minted.json()
    assert body["reviewer_name"] == "Asha Rao" and body["url"].endswith(f"/review/{body['token']}")
    assert (
        admin.post(
            "/api/v1/admin/review-tokens",
            json={"tender": "no-such-slug", "reviewer_name": "x"},
            headers=PUBLIC,
        ).status_code
        == 404
    )
    usage = admin.get("/api/v1/admin/usage", params={"days": 7}, headers=PUBLIC)
    assert usage.status_code == 200 and usage.json()["days"] == 7


def test_a_reviewer_may_not_use_the_admin_routes(make_pipeline: Callable[..., Pipeline]) -> None:
    pipeline = make_pipeline(**SETTINGS)
    oidc = FakeOidc({"code-asha": account("asha@acme.test")})
    app = create_app(
        pipeline.settings,
        pipeline.schemas,
        pipeline.storage,
        pipeline.llm,
        pipeline.catalog,
        oidc=oidc,
    )
    client = TestClient(app, base_url="https://testserver", follow_redirects=False)
    assert sign_in(client, "code-asha").status_code == 302
    for method, path in (
        ("GET", "/api/v1/admin/users"),
        ("POST", "/api/v1/admin/api-keys"),
        ("POST", "/api/v1/admin/review-tokens"),
        ("GET", "/api/v1/admin/usage"),
    ):
        response = client.request(method, path, json={}, headers=PUBLIC)
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["error_type"] == "not_allowed"
