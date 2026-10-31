"""IdentityService: who a request is, from a sign-in, a browser session or an API key.

A Principal is what the API's policy reads (api/middleware/auth.py): its tenant and the
tenants it may read, its role, its scopes. Sessions and keys are looked up across tenants
(the system scope of core.db) because the tenant is not known until they resolve; every
other query here is tenant-scoped. Every write is audited.
"""

import base64
import hashlib
import hmac
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.db import SYSTEM_TENANT, set_tenant
from core.models import ApiKey, AppUser, LoginSession, UsageRecord
from core.models.identity import API_KEY_SCOPES, ROLES
from core.services import audit

ACTOR = "identity"
KEY_PREFIX = "tie_live_"
PUBLIC_TENANT = "public"
PrincipalKind = Literal["user", "api_key", "review_token", "admin_token"]


class IdentityError(ValueError):
    """The sign-in or the key cannot be used. The message is safe to show."""


@dataclass(frozen=True)
class Principal:
    kind: PrincipalKind
    tenant_id: str
    read_tenants: tuple[str, ...]
    role: str
    scopes: tuple[str, ...] = ()
    user_id: str | None = None
    api_key_id: str | None = None
    name: str = ""
    # For a review token: the token's row id; the token's tender is on request.state.review.
    token_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# Password hashing (2026-10-31): scrypt from the standard library, with its parameters in
# the stored value so they can be raised later without breaking older hashes.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
MIN_PASSWORD = 12
USERNAME_MAX = 120


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=2**26
    )
    b64 = base64.urlsafe_b64encode
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt).decode()}${b64(digest).decode()}"


def password_matches(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.urlsafe_b64decode(digest)
        got = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.urlsafe_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=2**26,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


# A hash of nothing in particular, checked when the username is unknown, so a wrong
# username takes as long to refuse as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def _list(setting: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in setting.split(",") if part.strip())


def read_tenants_of(tenant_id: str) -> tuple[str, ...]:
    """A principal reads its own tenant and the public library."""
    return (tenant_id,) if tenant_id == PUBLIC_TENANT else (tenant_id, PUBLIC_TENANT)


class IdentityService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tenant_id = settings.tenant_id

    # -- sign-in -------------------------------------------------------------------------

    def login_from_claims(self, session: Session, claims: dict[str, Any]) -> AppUser:
        """The user behind verified OIDC claims, created on first sign-in. Refuses an
        unverified address, a domain outside the allowed ones, a disabled user."""
        email = str(claims.get("email") or "").strip().lower()
        subject = str(claims.get("sub") or "").strip()
        if not email or not subject:
            raise IdentityError("the sign-in did not name an account")
        if not claims.get("email_verified", False):
            raise IdentityError("the account's email address is not verified")
        domain = email.rpartition("@")[2]
        allowed = _list(self._settings.oidc_allowed_domains)
        if allowed and domain not in allowed:
            raise IdentityError(f"accounts of {domain} cannot sign in here")
        set_tenant(session, SYSTEM_TENANT)
        user = session.scalar(select(AppUser).where(AppUser.oidc_subject == subject))
        if user is None:
            user = session.scalar(
                select(AppUser).where(AppUser.tenant_id == self._tenant_id, AppUser.email == email)
            )
        now = datetime.now(UTC)
        if user is None:
            role = (
                "admin"
                if email in _list(self._settings.bootstrap_admin_emails)
                else self._settings.oidc_default_role
            )
            if role not in ROLES:
                raise IdentityError(f"unknown default role {role!r}")
            user = AppUser(
                tenant_id=self._tenant_id,
                created_by=ACTOR,
                email=email,
                display_name=str(claims.get("name") or email).strip()[:200],
                role=role,
                status="active",
                oidc_subject=subject,
                last_login_at=now,
            )
            session.add(user)
            session.flush()
            audit.record(
                session,
                tenant_id=user.tenant_id,
                actor=ACTOR,
                action="insert",
                table_name="app_user",
                row_id=user.id,
                after={"email": email, "role": role, "first_login": True},
            )
        else:
            if user.status != "active":
                raise IdentityError("this account is disabled")
            before = {"oidc_subject": user.oidc_subject, "last_login_at": _iso(user.last_login_at)}
            user.oidc_subject = user.oidc_subject or subject
            user.last_login_at = now
            audit.record(
                session,
                tenant_id=user.tenant_id,
                actor=ACTOR,
                action="login",
                table_name="app_user",
                row_id=user.id,
                before=before,
                after={"oidc_subject": user.oidc_subject, "last_login_at": _iso(now)},
            )
        session.commit()
        return user

    def login_with_password(self, session: Session, username: str, password: str) -> AppUser:
        """The user behind a username and password of this deployment's tenant. One message
        for every refusal, so it does not tell which half was wrong."""
        name = username.strip().lower()
        set_tenant(session, self._tenant_id)
        user = session.scalar(
            select(AppUser).where(AppUser.tenant_id == self._tenant_id, AppUser.email == name)
        )
        if user is None or not user.password_hash:
            password_matches(password, _DUMMY_HASH)
            raise IdentityError("wrong username or password")
        if not password_matches(password, user.password_hash) or user.status != "active":
            raise IdentityError("wrong username or password")
        user.last_login_at = datetime.now(UTC)
        audit.record(
            session,
            tenant_id=user.tenant_id,
            actor=user.email,
            action="login",
            table_name="app_user",
            row_id=user.id,
            after={"method": "password", "last_login_at": _iso(user.last_login_at)},
        )
        session.commit()
        return user

    def set_password(
        self,
        session: Session,
        username: str,
        password: str,
        *,
        role: str | None = None,
        created_by: str = ACTOR,
    ) -> AppUser:
        """Set a user's password, creating the user (with `role`, default reviewer) when
        the username is new. Audited; the hash is never written to the log."""
        name = username.strip().lower()
        if not name or len(name) > USERNAME_MAX or any(c.isspace() for c in name):
            raise IdentityError("a username is one word of at most 120 characters")
        if len(password) < MIN_PASSWORD:
            raise IdentityError(f"a password has at least {MIN_PASSWORD} characters")
        if role is not None and role not in ROLES:
            raise IdentityError(f"unknown role {role!r}; one of {list(ROLES)}")
        set_tenant(session, self._tenant_id)
        user = session.scalar(
            select(AppUser).where(AppUser.tenant_id == self._tenant_id, AppUser.email == name)
        )
        if user is None:
            user = AppUser(
                tenant_id=self._tenant_id,
                created_by=created_by,
                email=name,
                display_name=name,
                role=role or "reviewer",
                status="active",
                password_hash=hash_password(password),
            )
            session.add(user)
            session.flush()
            audit.record(
                session,
                tenant_id=user.tenant_id,
                actor=created_by,
                action="insert",
                table_name="app_user",
                row_id=user.id,
                after={"email": name, "role": user.role, "password": "set"},
            )
        else:
            before = {"role": user.role, "status": user.status}
            user.password_hash = hash_password(password)
            if role is not None:
                user.role = role
            user.status = "active"
            audit.record(
                session,
                tenant_id=user.tenant_id,
                actor=created_by,
                action="update",
                table_name="app_user",
                row_id=user.id,
                before=before,
                after={"role": user.role, "status": user.status, "password": "changed"},
            )
        session.commit()
        return user

    def open_session(self, session: Session, user: AppUser) -> str:
        """A new browser session for the user; returns the cookie value."""
        raw = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        row = LoginSession(
            tenant_id=user.tenant_id,
            created_by=user.email,
            user_id=user.id,
            token_hash=_hash(raw),
            expires_at=now + timedelta(hours=self._settings.session_hours),
            last_seen_at=now,
        )
        set_tenant(session, user.tenant_id)
        session.add(row)
        session.flush()
        audit.record(
            session,
            tenant_id=user.tenant_id,
            actor=user.email,
            action="insert",
            table_name="login_session",
            row_id=row.id,
            after={"user_id": user.id, "expires_at": _iso(row.expires_at)},
        )
        session.commit()
        return raw

    def resolve_session(self, session: Session, raw: str) -> Principal | None:
        """The principal of a cookie value, or None when it is unknown, expired, revoked
        or the user is disabled."""
        set_tenant(session, SYSTEM_TENANT)
        row = session.scalar(select(LoginSession).where(LoginSession.token_hash == _hash(raw)))
        if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
            return None
        user = session.scalar(
            select(AppUser).where(AppUser.id == row.user_id, AppUser.tenant_id == row.tenant_id)
        )
        if user is None or user.status != "active":
            return None
        row.last_seen_at = datetime.now(UTC)
        session.commit()
        return Principal(
            kind="user",
            tenant_id=user.tenant_id,
            read_tenants=read_tenants_of(user.tenant_id),
            role=user.role,
            user_id=user.id,
            name=user.email,
        )

    def revoke_session(self, session: Session, raw: str) -> bool:
        set_tenant(session, SYSTEM_TENANT)
        row = session.scalar(select(LoginSession).where(LoginSession.token_hash == _hash(raw)))
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = datetime.now(UTC)
        audit.record(
            session,
            tenant_id=row.tenant_id,
            actor=row.created_by,
            action="revoke",
            table_name="login_session",
            row_id=row.id,
            after={"revoked_at": _iso(row.revoked_at)},
        )
        session.commit()
        return True

    # -- API keys ------------------------------------------------------------------------

    def create_api_key(
        self,
        session: Session,
        tenant_id: str,
        name: str,
        scopes: Sequence[str],
        *,
        created_by: str,
        user_id: str | None = None,
        rate_limit_per_min: int | None = None,
        daily_cap: int | None = None,
    ) -> tuple[ApiKey, str]:
        """A new key; the raw value is returned once and never stored."""
        if not name.strip():
            raise IdentityError("a key needs a name")
        unknown = sorted(set(scopes) - set(API_KEY_SCOPES))
        if unknown:
            raise IdentityError(f"unknown scope(s) {unknown}; one of {list(API_KEY_SCOPES)}")
        raw = KEY_PREFIX + secrets.token_hex(20)
        row = ApiKey(
            tenant_id=tenant_id,
            created_by=created_by,
            name=name.strip(),
            user_id=user_id,
            prefix=raw[:12],
            key_hash=_hash(raw),
            scopes=sorted(set(scopes) | {"read"}),
            rate_limit_per_min=rate_limit_per_min or self._settings.api_key_rate_limit_per_min,
            daily_cap=daily_cap or self._settings.api_key_daily_cap,
        )
        set_tenant(session, tenant_id)
        session.add(row)
        session.flush()
        audit.record(
            session,
            tenant_id=tenant_id,
            actor=created_by,
            action="insert",
            table_name="api_key",
            row_id=row.id,
            after={"name": row.name, "prefix": row.prefix, "scopes": row.scopes},
        )
        session.commit()
        return row, raw

    def resolve_api_key(self, session: Session, raw: str) -> Principal | None:
        if not raw.startswith(KEY_PREFIX):
            return None
        set_tenant(session, SYSTEM_TENANT)
        row = session.scalar(select(ApiKey).where(ApiKey.key_hash == _hash(raw)))
        now = datetime.now(UTC)
        if row is None or row.revoked_at is not None:
            return None
        if row.expires_at is not None and row.expires_at <= now:
            return None
        row.last_used_at = now
        session.commit()
        return Principal(
            kind="api_key",
            tenant_id=row.tenant_id,
            read_tenants=read_tenants_of(row.tenant_id),
            role="api_client",
            scopes=tuple(row.scopes),
            user_id=row.user_id,
            api_key_id=row.id,
            name=row.name,
        )

    def revoke_api_key(self, session: Session, tenant_id: str, key_id: str, *, by: str) -> bool:
        set_tenant(session, tenant_id)
        row = session.scalar(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
        )
        if row is None:
            raise LookupError(f"api key {key_id} not found")
        if row.revoked_at is not None:
            return False
        row.revoked_at = datetime.now(UTC)
        audit.record(
            session,
            tenant_id=tenant_id,
            actor=by,
            action="revoke",
            table_name="api_key",
            row_id=row.id,
            after={"revoked_at": _iso(row.revoked_at)},
        )
        session.commit()
        return True

    def check_rate_limit(self, session: Session, principal: Principal) -> str | None:
        """None when the key may make the call now; else "rate_limited" (the per-minute
        limit) or "daily_cap" (the calls since midnight UTC)."""
        if principal.api_key_id is None:
            return None
        set_tenant(session, principal.tenant_id)
        key = session.scalar(
            select(ApiKey).where(
                ApiKey.id == principal.api_key_id, ApiKey.tenant_id == principal.tenant_id
            )
        )
        if key is None:
            return None
        now = datetime.now(UTC)
        minute = self._usage_since(session, key, now - timedelta(seconds=60))
        if minute >= key.rate_limit_per_min:
            return "rate_limited"
        day = self._usage_since(
            session, key, now.replace(hour=0, minute=0, second=0, microsecond=0)
        )
        if day >= key.daily_cap:
            return "daily_cap"
        return None

    def _usage_since(self, session: Session, key: ApiKey, since: datetime) -> int:
        return int(
            session.scalar(
                select(func.count())
                .select_from(UsageRecord)
                .where(
                    UsageRecord.tenant_id == key.tenant_id,
                    UsageRecord.api_key_id == key.id,
                    UsageRecord.created_at >= since,
                )
            )
            or 0
        )

    # -- usage ---------------------------------------------------------------------------

    def record_usage(
        self,
        session: Session,
        principal: Principal,
        tool: str,
        *,
        resource_tenant_id: str | None,
        status: int,
        tier: str,
        units: int = 1,
        tokens: int | None = None,
        detail: str | None = None,
    ) -> UsageRecord:
        """One metered call, attributed to the calling tenant."""
        set_tenant(session, principal.tenant_id)
        row = UsageRecord(
            tenant_id=principal.tenant_id,
            created_by=principal.name or principal.kind,
            resource_tenant_id=resource_tenant_id,
            user_id=principal.user_id,
            api_key_id=principal.api_key_id,
            tool=tool[:100],
            tier=tier,
            units=units,
            tokens=tokens,
            status=status,
            detail=detail,
        )
        session.add(row)
        session.commit()
        return row


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None
