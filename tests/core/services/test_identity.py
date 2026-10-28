"""IdentityService: sign-in claims, browser sessions, API keys, rate limits, usage."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.db import SYSTEM_TENANT, make_engine, make_session_factory, set_tenant
from core.models import ApiKey, AppUser, AuditLog, LoginSession, UsageRecord
from core.services.identity import IdentityError, IdentityService, Principal
from tests.conftest import Pipeline, add_tenant
from tests.fixtures.oidc import account


@pytest.fixture()
def identity(pipeline: Pipeline) -> IdentityService:
    return IdentityService(
        pipeline.settings.model_copy(
            update={
                "oidc_allowed_domains": "acme.test, partner.test",
                "bootstrap_admin_emails": "boss@acme.test",
                "session_hours": 1,
                "api_key_rate_limit_per_min": 3,
                "api_key_daily_cap": 100,
            }
        )
    )


def test_first_sign_in_creates_the_user_with_the_default_or_bootstrap_role(
    identity: IdentityService, db: Session
) -> None:
    asha = identity.login_from_claims(db, account("asha@acme.test", name="Asha Rao"))
    assert (asha.role, asha.display_name, asha.oidc_subject) == (
        "reviewer",
        "Asha Rao",
        "sub-asha@acme.test",
    )
    assert asha.tenant_id == "ergplan" and asha.last_login_at is not None
    boss = identity.login_from_claims(db, account("boss@acme.test"))
    assert boss.role == "admin"
    again = identity.login_from_claims(db, account("asha@acme.test"))
    assert again.id == asha.id
    actions = [
        a.action for a in db.scalars(select(AuditLog).where(AuditLog.table_name == "app_user"))
    ]
    assert sorted(actions) == ["insert", "insert", "login"]


def test_sign_in_refuses_unverified_foreign_and_disabled_accounts(
    identity: IdentityService, db: Session
) -> None:
    with pytest.raises(IdentityError, match="not verified"):
        identity.login_from_claims(db, account("x@acme.test", verified=False))
    with pytest.raises(IdentityError, match="cannot sign in"):
        identity.login_from_claims(db, account("x@elsewhere.test"))
    user = identity.login_from_claims(db, account("y@partner.test"))
    user.status = "disabled"
    db.commit()
    with pytest.raises(IdentityError, match="disabled"):
        identity.login_from_claims(db, account("y@partner.test"))
    with pytest.raises(IdentityError, match="did not name"):
        identity.login_from_claims(db, {"email": "", "sub": ""})


def test_a_session_resolves_until_it_expires_or_is_revoked(
    identity: IdentityService, db: Session
) -> None:
    user = identity.login_from_claims(db, account("asha@acme.test"))
    raw = identity.open_session(db, user)
    principal = identity.resolve_session(db, raw)
    assert principal is not None
    assert (principal.kind, principal.role, principal.name) == (
        "user",
        "reviewer",
        "asha@acme.test",
    )
    assert principal.tenant_id == "ergplan" and principal.read_tenants == ("ergplan", "public")
    assert identity.resolve_session(db, "not-a-session") is None
    assert identity.revoke_session(db, raw) is True
    assert identity.revoke_session(db, raw) is False
    assert identity.resolve_session(db, raw) is None

    raw2 = identity.open_session(db, user)
    set_tenant(db, SYSTEM_TENANT)
    row = db.scalars(select(LoginSession).where(LoginSession.revoked_at.is_(None))).one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert identity.resolve_session(db, raw2) is None
    user.status = "disabled"
    db.commit()
    raw3 = identity.open_session(db, user)
    assert identity.resolve_session(db, raw3) is None


def test_api_keys_resolve_carry_scopes_and_are_revoked(
    identity: IdentityService, db: Session
) -> None:
    key, secret = identity.create_api_key(
        db, "ergplan", "Partner feed", ["model"], created_by="boss"
    )
    assert secret.startswith("tie_live_") and len(secret) == len("tie_live_") + 40
    assert key.prefix == secret[:12] and key.scopes == ["model", "read"]
    assert (key.rate_limit_per_min, key.daily_cap) == (3, 100)
    principal = identity.resolve_api_key(db, secret)
    assert principal is not None
    assert (principal.kind, principal.role, principal.scopes) == (
        "api_key",
        "api_client",
        ("model", "read"),
    )
    assert principal.api_key_id == key.id and principal.name == "Partner feed"
    assert identity.resolve_api_key(db, "tie_live_" + "0" * 40) is None
    assert identity.resolve_api_key(db, "something else") is None
    with pytest.raises(IdentityError, match="unknown scope"):
        identity.create_api_key(db, "ergplan", "x", ["delete"], created_by="boss")
    with pytest.raises(IdentityError, match="needs a name"):
        identity.create_api_key(db, "ergplan", " ", [], created_by="boss")
    assert identity.revoke_api_key(db, "ergplan", key.id, by="boss") is True
    assert identity.revoke_api_key(db, "ergplan", key.id, by="boss") is False
    assert identity.resolve_api_key(db, secret) is None
    with pytest.raises(LookupError):
        identity.revoke_api_key(db, "ergplan", "0" * 32, by="boss")


def test_usage_is_attributed_to_the_calling_tenant_and_counts_against_the_key(
    identity: IdentityService, db: Session, settings: Settings
) -> None:
    add_tenant(settings, "other")
    other = make_session_factory(make_engine(settings), "other")
    with other() as theirs:
        key, secret = identity.create_api_key(theirs, "other", "Theirs", [], created_by="them")
    principal = identity.resolve_api_key(db, secret)
    assert principal is not None and principal.tenant_id == "other"
    for _ in range(3):
        assert identity.check_rate_limit(db, principal) is None
        identity.record_usage(
            db, principal, "GET /tenders", resource_tenant_id="public", status=200, tier="api"
        )
    assert identity.check_rate_limit(db, principal) == "rate_limited"
    with other() as theirs:
        rows = list(theirs.scalars(select(UsageRecord)))
        assert len(rows) == 3 and {r.tenant_id for r in rows} == {"other"}
        assert {r.resource_tenant_id for r in rows} == {"public"}
        assert {r.api_key_id for r in rows} == {key.id}
    # Our tenant's session sees none of it: the rows belong to the caller.
    set_tenant(db, "ergplan", ("ergplan", "public"))
    assert list(db.scalars(select(UsageRecord))) == []
    assert db.scalars(select(ApiKey)).all() == []
    assert db.scalars(select(AppUser)).all() == []


def test_a_principal_is_admin_only_by_role() -> None:
    assert Principal(kind="user", tenant_id="t", read_tenants=("t",), role="admin").is_admin
    assert not Principal(
        kind="api_key", tenant_id="t", read_tenants=("t",), role="api_client"
    ).is_admin
