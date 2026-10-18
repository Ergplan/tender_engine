"""Sign-in through the API: the redirect, the callback, the session cookie, sign-out."""

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from tests.conftest import Pipeline
from tests.fixtures.oidc import FakeOidc, account

PUBLIC = {"X-Public-Request": "1"}
SETTINGS: dict[str, Any] = {
    "session_secret": "test-session-secret",
    "oidc_allowed_domains": "acme.test",
    "bootstrap_admin_emails": "boss@acme.test",
    "admin_token": "s3cret-admin",
}


@pytest.fixture()
def oidc() -> FakeOidc:
    return FakeOidc(
        {
            "code-asha": account("asha@acme.test", name="Asha Rao"),
            "code-boss": account("boss@acme.test", name="The Boss"),
            "code-outsider": account("mallory@elsewhere.test"),
        }
    )


@pytest.fixture()
def signed(make_pipeline: Callable[..., Pipeline], oidc: FakeOidc) -> TestClient:
    """A browser through the public proxy, on https (the cookies are Secure)."""
    pipeline = make_pipeline(**SETTINGS)
    app = create_app(
        pipeline.settings,
        pipeline.schemas,
        pipeline.storage,
        pipeline.llm,
        pipeline.catalog,
        oidc=oidc,
    )
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def sign_in(client: TestClient, code: str) -> Any:
    started = client.get("/api/v1/auth/login", headers=PUBLIC)
    assert started.status_code == 302, started.text
    query = parse_qs(urlparse(started.headers["location"]).query)
    assert "tie_oidc" in started.cookies
    return client.get(
        "/api/v1/auth/callback",
        params={"code": code, "state": query["state"][0]},
        headers=PUBLIC,
    )


def test_sign_in_opens_a_session_and_me_says_who(signed: TestClient, oidc: FakeOidc) -> None:
    assert signed.get("/api/v1/auth/me", headers=PUBLIC).status_code == 401
    done = sign_in(signed, "code-asha")
    assert done.status_code == 302 and done.headers["location"] == "/"
    assert "tie_session" in signed.cookies
    assert oidc.exchanged[0][1].endswith("/api/v1/auth/callback")
    me = signed.get("/api/v1/auth/me", headers=PUBLIC)
    assert me.status_code == 200, me.text
    body = me.json()
    assert (body["kind"], body["name"], body["role"], body["tenant_id"]) == (
        "user",
        "asha@acme.test",
        "reviewer",
        "ergplan",
    )
    assert body["read_tenants"] == ["ergplan", "public"]
    # The session reaches what a reviewer may; sign-out ends it.
    assert signed.get("/api/v1/tenders", headers=PUBLIC).status_code == 200
    raw = signed.cookies["tie_session"]
    assert signed.post("/api/v1/auth/logout", headers=PUBLIC).status_code == 204
    assert "tie_session" not in signed.cookies
    assert signed.get("/api/v1/auth/me", headers=PUBLIC).status_code == 401
    # A browser that still holds the old cookie is told the session ended.
    signed.cookies.set("tie_session", raw)
    stale = signed.get("/api/v1/auth/me", headers=PUBLIC)
    assert stale.status_code == 401 and stale.json()["error_type"] == "session_expired"


def test_the_bootstrap_address_is_an_admin(signed: TestClient) -> None:
    assert sign_in(signed, "code-boss").status_code == 302
    me = signed.get("/api/v1/auth/me", headers=PUBLIC).json()
    assert me["role"] == "admin"
    assert signed.get("/api/v1/admin/users", headers=PUBLIC).status_code == 200


def test_a_foreign_domain_a_bad_state_and_an_unknown_code_are_refused(
    signed: TestClient,
) -> None:
    refused = sign_in(signed, "code-outsider")
    assert refused.status_code == 403 and refused.json()["error_type"] == "login_refused"
    assert "tie_session" not in signed.cookies
    unknown = sign_in(signed, "code-nope")
    assert unknown.status_code == 403
    started = signed.get("/api/v1/auth/login", headers=PUBLIC)
    assert started.status_code == 302
    wrong_state = signed.get(
        "/api/v1/auth/callback", params={"code": "code-asha", "state": "forged"}, headers=PUBLIC
    )
    assert wrong_state.status_code == 403 and "did not match" in wrong_state.json()["detail"]
    signed.cookies.clear()
    no_start = signed.get(
        "/api/v1/auth/callback", params={"code": "code-asha", "state": "x"}, headers=PUBLIC
    )
    assert no_start.status_code == 403 and "did not start" in no_start.json()["detail"]


def test_sign_in_needs_a_session_secret(
    make_pipeline: Callable[..., Pipeline], oidc: FakeOidc
) -> None:
    pipeline = make_pipeline(**{**SETTINGS, "session_secret": ""})
    app = create_app(
        pipeline.settings,
        pipeline.schemas,
        pipeline.storage,
        pipeline.llm,
        pipeline.catalog,
        oidc=oidc,
    )
    client = TestClient(app, base_url="https://testserver", follow_redirects=False)
    response = client.get("/api/v1/auth/login", headers=PUBLIC)
    assert response.status_code == 503 and "SESSION_SECRET" in response.json()["detail"]
