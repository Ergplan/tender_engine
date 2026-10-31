"""Password sign-in (2026-10-31): a username and password open the same browser session as
the provider's sign-in; failures are refused alike and lock after five."""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.main import create_app
from api.v1.core import auth as auth_routes
from core.db import make_engine, make_session_factory
from core.models import AppUser, AuditLog
from core.services.identity import IdentityError, IdentityService, hash_password, password_matches
from scripts import set_password
from tests.conftest import Pipeline

PUBLIC = {"X-Public-Request": "1"}
GOOD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def no_lockouts() -> Iterator[None]:
    auth_routes._failures.clear()
    yield
    auth_routes._failures.clear()


@pytest.fixture()
def stack(make_pipeline: Callable[..., Pipeline]) -> tuple[Pipeline, TestClient]:
    pipeline = make_pipeline(public_base_url="https://engine.test")
    app = create_app(
        pipeline.settings, pipeline.schemas, pipeline.storage, pipeline.llm, pipeline.catalog
    )
    return pipeline, TestClient(app, base_url="https://testserver", follow_redirects=False)


def _admin(pipeline: Pipeline) -> None:
    factory = make_session_factory(make_engine(pipeline.settings), pipeline.settings.tenant_id)
    with factory() as session:
        IdentityService(pipeline.settings).set_password(session, "Admin", GOOD, role="admin")


def _login(client: TestClient, username: str, password: str) -> int:
    response = client.post(
        "/api/v1/auth/password",
        json={"username": username, "password": password},
        headers=PUBLIC,
    )
    return response.status_code


def test_hashes_are_salted_and_checked() -> None:
    one, two = hash_password(GOOD), hash_password(GOOD)
    assert one != two and one.startswith("scrypt$")
    assert password_matches(GOOD, one) and password_matches(GOOD, two)
    assert not password_matches("wrong-password-1", one)
    assert not password_matches(GOOD, None) and not password_matches(GOOD, "garbage")


def test_set_password_creates_then_updates_and_refuses_weak_ones(
    pipeline: Pipeline, db: Session
) -> None:
    identity = IdentityService(pipeline.settings)
    user = identity.set_password(db, "Admin", GOOD, role="admin")
    assert (user.email, user.role, user.status) == ("admin", "admin", "active")
    assert user.password_hash and GOOD not in user.password_hash
    again = identity.set_password(db, "admin", "another-long-password")
    assert again.id == user.id and again.role == "admin"
    with pytest.raises(IdentityError, match="at least 12"):
        identity.set_password(db, "admin", "admin")
    with pytest.raises(IdentityError, match="one word"):
        identity.set_password(db, "two words", GOOD)
    with pytest.raises(IdentityError, match="unknown role"):
        identity.set_password(db, "x", GOOD, role="god")
    logged = db.scalars(select(AuditLog).where(AuditLog.table_name == "app_user")).all()
    assert len(logged) >= 2
    assert all("scrypt" not in str(row.after) for row in logged), "the hash is never logged"


def test_a_right_password_opens_a_session_the_api_accepts(
    stack: tuple[Pipeline, TestClient],
) -> None:
    pipeline, client = stack
    _admin(pipeline)
    assert client.get("/api/v1/auth/me", headers=PUBLIC).status_code == 401
    response = client.post(
        "/api/v1/auth/password", json={"username": " ADMIN ", "password": GOOD}, headers=PUBLIC
    )
    assert response.status_code == 204, response.text
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "samesite=lax" in cookie.lower()
    me = client.get("/api/v1/auth/me", headers=PUBLIC)
    assert me.status_code == 200 and me.json()["role"] == "admin" and me.json()["name"] == "admin"
    assert client.get("/api/v1/tenders", headers=PUBLIC).status_code == 200
    client.post("/api/v1/auth/logout", headers=PUBLIC)
    assert client.get("/api/v1/auth/me", headers=PUBLIC).status_code == 401


def test_wrong_username_and_wrong_password_are_refused_alike(
    stack: tuple[Pipeline, TestClient],
) -> None:
    pipeline, client = stack
    _admin(pipeline)
    for username, password in (("admin", "wrong-password-1"), ("nobody", GOOD)):
        response = client.post(
            "/api/v1/auth/password",
            json={"username": username, "password": password},
            headers=PUBLIC,
        )
        assert response.status_code == 401
        assert response.json()["error_type"] == "login_failed"
    assert "set-cookie" not in response.headers


def test_five_failures_lock_the_username_for_the_window(
    stack: tuple[Pipeline, TestClient],
) -> None:
    pipeline, client = stack
    _admin(pipeline)
    for _ in range(auth_routes.LOCK_FAILURES):
        assert _login(client, "admin", "wrong-password-1") == 401
    assert _login(client, "admin", GOOD) == 429, "locked even with the right password"


def test_a_disabled_user_cannot_sign_in(stack: tuple[Pipeline, TestClient]) -> None:
    pipeline, client = stack
    _admin(pipeline)
    factory = make_session_factory(make_engine(pipeline.settings), pipeline.settings.tenant_id)
    with factory() as session:
        user = session.scalars(select(AppUser).where(AppUser.email == "admin")).one()
        user.status = "disabled"
        session.commit()
    assert _login(client, "admin", GOOD) == 401


def test_a_stale_session_cookie_does_not_block_signing_in(
    stack: tuple[Pipeline, TestClient],
) -> None:
    pipeline, client = stack
    _admin(pipeline)
    client.cookies.set("tie_session", "expired-or-forged")
    assert client.get("/api/v1/tenders", headers=PUBLIC).status_code == 401
    assert _login(client, "admin", GOOD) == 204


def test_the_command_generates_a_strong_password_once(
    pipeline: Pipeline, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(set_password, "Settings", lambda: pipeline.settings)
    assert set_password.main(["--username", "ops", "--role", "admin"]) == 0
    out = capsys.readouterr().out
    password = out.split("password: ", 1)[1].strip()
    assert len(password) >= 16 and "role: admin" in out
    factory = make_session_factory(make_engine(pipeline.settings), pipeline.settings.tenant_id)
    with factory() as session:
        user = IdentityService(pipeline.settings).login_with_password(session, "ops", password)
        assert user.role == "admin"
    assert set_password.main(["--username", "ops", "--password", "short"]) == 2
