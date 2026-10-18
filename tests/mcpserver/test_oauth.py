"""The OAuth flow an MCP client follows: register, authorize with a signed-in user,
consent, code, token; PKCE and single use enforced."""

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.main import create_app
from api.middleware.auth import SESSION_COOKIE
from core.models import ApiKey, AppUser
from core.services.identity import IdentityService
from tests.conftest import Pipeline
from tests.fixtures.oidc import FakeOidc


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _signed_in(client: TestClient, pipeline: Pipeline, db: Session, email: str) -> AppUser:
    identity = IdentityService(pipeline.settings)
    user = identity.login_from_claims(
        db, {"sub": f"sub-{email}", "email": email, "email_verified": True, "name": "Asha"}
    )
    raw = identity.open_session(db, user)
    client.cookies.set(SESSION_COOKIE, raw)
    return user


def _app(pipeline: Pipeline) -> TestClient:
    settings = pipeline.settings.model_copy(
        update={"session_secret": "s" * 32, "public_base_url": "https://testserver"}
    )
    app = create_app(
        settings,
        pipeline.schemas,
        pipeline.storage,
        pipeline.llm,
        pipeline.catalog,
        oidc=FakeOidc(),
    )
    return TestClient(app, follow_redirects=False)


def _register(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/register",
        json={
            "client_name": "Claude Desktop",
            "redirect_uris": ["http://localhost:9999/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _authorize(client: TestClient, client_id: str, challenge: str) -> str:
    response = client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "http://localhost:9999/callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "scope": "public:read",
        },
    )
    assert response.status_code in (302, 307), response.text
    return response.headers["location"]


def test_register_authorize_consent_token_and_a_tool_call(pipeline: Pipeline, db: Session) -> None:
    with _app(pipeline) as client:
        registered = _register(client)
        verifier, challenge = _pkce()
        consent_url = _authorize(client, registered["client_id"], challenge)
        assert "/api/v1/oauth/consent?request=" in consent_url
        path = consent_url[consent_url.index("/api/v1") :]

        # No session: sent to sign in.
        anonymous = client.get(path)
        assert anonymous.status_code == 302
        assert anonymous.headers["location"].startswith(
            "/api/v1/auth/login?next=%2Fapi%2Fv1%2Foauth%2Fconsent"
        )

        user = _signed_in(client, pipeline, db, "asha@ergplan.test")
        page = client.get(path)
        assert (
            page.status_code == 200 and "Claude Desktop" in page.text and "public:read" in page.text
        )
        request_token = parse_qs(urlparse(consent_url).query)["request"][0]
        approved = client.post(
            "/api/v1/oauth/consent", data={"decision": "allow", "request": request_token}
        )
        assert approved.status_code == 302
        location = urlparse(approved.headers["location"])
        query = parse_qs(location.query)
        assert location.netloc == "localhost:9999" and query["state"] == ["xyz"]
        code = query["code"][0]

        wrong = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/callback",
                "client_id": registered["client_id"],
                "code_verifier": "not-the-verifier",
            },
        )
        assert wrong.status_code == 400, wrong.text

        token = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/callback",
                "client_id": registered["client_id"],
                "code_verifier": verifier,
            },
        )
        assert token.status_code == 200, token.text
        body = token.json()
        assert body["token_type"].lower() == "bearer" and body["scope"] == "public:read"
        assert "refresh_token" not in body or body["refresh_token"] is None

        reused = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/callback",
                "client_id": registered["client_id"],
                "code_verifier": verifier,
            },
        )
        assert reused.status_code == 400

        # The token is a key of the user's tenant, scoped to the library.
        key = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id)).one()
        assert "public:read" in key.scopes and "own:read" not in key.scopes
        assert key.name.startswith("mcp:")
        principal = IdentityService(pipeline.settings).resolve_api_key(db, body["access_token"])
        assert principal is not None and principal.tenant_id == "ergplan"

        # And it opens the MCP endpoint.
        client.cookies.clear()
        opened = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
            headers={
                "Authorization": f"Bearer {body['access_token']}",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert opened.status_code == 200, opened.text
        assert (
            client.post("/mcp", json={}, headers={"Accept": "application/json"}).status_code == 401
        )


def test_denying_consent_returns_an_error_to_the_client(pipeline: Pipeline, db: Session) -> None:
    with _app(pipeline) as client:
        registered = _register(client)
        _, challenge = _pkce()
        consent_url = _authorize(client, registered["client_id"], challenge)
        _signed_in(client, pipeline, db, "asha@ergplan.test")
        request_token = parse_qs(urlparse(consent_url).query)["request"][0]
        denied = client.post(
            "/api/v1/oauth/consent", data={"decision": "deny", "request": request_token}
        )
        assert denied.status_code == 302
        assert parse_qs(urlparse(denied.headers["location"]).query)["error"] == ["access_denied"]
        tampered = client.post(
            "/api/v1/oauth/consent",
            data={"decision": "allow", "request": request_token[:-4] + "zzzz"},
        )
        assert tampered.status_code == 422


def test_a_code_exchanged_twice_at_the_provider_fails_the_second_time(
    pipeline: Pipeline, db: Session
) -> None:
    import anyio
    from mcp.server.auth.provider import TokenError
    from mcp.shared.auth import OAuthClientInformationFull

    from mcpserver.auth import LibraryOAuthProvider

    settings = pipeline.settings.model_copy(update={"session_secret": "s" * 32})
    identity = IdentityService(settings)
    provider = LibraryOAuthProvider(settings, pipeline.session_factory, identity)
    user = identity.login_from_claims(
        db, {"sub": "sub-x", "email": "asha@ergplan.test", "email_verified": True, "name": "A"}
    )
    client = OAuthClientInformationFull(
        client_id="c1", client_name="c", redirect_uris=["http://localhost:1/cb"]
    )
    anyio.run(provider.register_client, client)
    request = {
        "client_id": "c1",
        "redirect_uri": "http://localhost:1/cb",
        "scopes": ["public:read"],
        "code_challenge": "x" * 43,
    }
    raw = provider.issue_code(db, request, user)
    loaded = anyio.run(provider.load_authorization_code, client, raw)
    assert loaded is not None
    first = anyio.run(provider.exchange_authorization_code, client, loaded)
    assert first.access_token.startswith("tie_live_")
    with pytest.raises(TokenError):
        anyio.run(provider.exchange_authorization_code, client, loaded)
    assert anyio.run(provider.load_authorization_code, client, raw) is None
