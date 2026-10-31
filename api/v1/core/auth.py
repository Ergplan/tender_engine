"""Sign-in (Google OIDC), the session cookie, sign-out and "who am I".

The state of a sign-in travels in a short-lived cookie signed with the session secret, so
the callback can tell the sign-in it started from one it did not. The browser session is
an HttpOnly cookie whose value is known only to the login_session row's hash.
"""

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import quote, unquote

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from api.deps import SessionDep, SettingsDep
from api.middleware.auth import SESSION_COOKIE
from api.middleware.errors import AppError
from api.v1.schemas.identity import MeOut, PasswordLoginIn
from api.v1.schemas.library import SignupIn
from core.config import Settings
from core.db import SYSTEM_TENANT, set_tenant
from core.models import AppUser
from core.services.identity import IdentityError, IdentityService, Principal
from core.services.oidc import OidcError, OidcProvider
from tender.services.library import LibraryError, signup

router = APIRouter(prefix="/auth", tags=["auth"])
STATE_COOKIE = "tie_oidc"
STATE_SECONDS = 600


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.public_base_url.rstrip('/')}/api/v1/auth/callback"


def _secure(settings: Settings) -> bool:
    return settings.public_base_url.lower().startswith("https://")


def _sign(secret: str, *parts: str) -> str:
    return hmac.new(secret.encode(), "|".join(parts).encode(), hashlib.sha256).hexdigest()


def _provider(request: Request) -> OidcProvider:
    provider: OidcProvider = request.app.state.oidc
    return provider


def _identity(request: Request) -> IdentityService:
    identity: IdentityService = request.app.state.identity
    return identity


def safe_next(value: str | None) -> str:
    """Where to go after sign-in: a path of this origin, else the app's root."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


@router.get("/login", status_code=302)
def login(request: Request, settings: SettingsDep, next: str | None = None) -> Response:
    """Send the browser to the identity provider. The state and nonce of this sign-in go
    in a signed cookie that lives ten minutes, with where to return to (`next`: a path of
    this origin, else the root)."""
    if not settings.session_secret:
        raise AppError("dependency_unavailable", "sign-in is not configured (SESSION_SECRET)")
    state, nonce = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    expires = str(int(time.time()) + STATE_SECONDS)
    back = safe_next(next)
    try:
        url = _provider(request).authorization_url(state, nonce, _redirect_uri(settings))
    except OidcError as exc:
        raise AppError("dependency_unavailable", str(exc)) from exc
    response = RedirectResponse(url, status_code=302)
    signature = _sign(settings.session_secret, state, nonce, expires, back)
    response.set_cookie(
        STATE_COOKIE,
        f"{state}.{nonce}.{expires}.{signature}.{quote(back, safe='')}",
        max_age=STATE_SECONDS,
        httponly=True,
        secure=_secure(settings),
        samesite="lax",
        path="/api/v1/auth",
    )
    return response


@router.get("/callback", status_code=302)
def callback(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    code: Annotated[str, ""] = "",
    state: Annotated[str, ""] = "",
) -> Response:
    """The provider sends the browser back here with a code: exchange it, verify the
    identity, open a session and go to the app."""
    if not settings.session_secret:
        raise AppError("dependency_unavailable", "sign-in is not configured (SESSION_SECRET)")
    raw = request.cookies.get(STATE_COOKIE, "")
    parts = raw.split(".", 4)
    if len(parts) != 5 or not code or not state:
        raise AppError("login_refused", "the sign-in did not start here; start again")
    started_state, nonce, expires, signature, back = parts
    back = safe_next(unquote(back))
    expected = _sign(settings.session_secret, started_state, nonce, expires, back)
    if (
        not hmac.compare_digest(signature, expected)
        or started_state != state
        or int(expires) < int(time.time())
    ):
        raise AppError(
            "login_refused", "the sign-in did not match the one that started; start again"
        )
    try:
        claims = _provider(request).exchange(code, _redirect_uri(settings), nonce)
        user = _login_or_signup(session, settings, _identity(request), claims)
    except (OidcError, IdentityError, LibraryError) as exc:
        raise AppError("login_refused", str(exc)) from exc
    token = _identity(request).open_session(session, user)
    response = RedirectResponse(back, status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(settings.session_hours * 3600),
        httponly=True,
        secure=_secure(settings),
        samesite="lax",
        path="/",
    )
    response.delete_cookie(STATE_COOKIE, path="/api/v1/auth")
    return response


def _login_or_signup(
    session: SessionDep, settings: Settings, identity: IdentityService, claims: dict[str, Any]
) -> AppUser:
    """The enterprise sign-in; for a verified address outside the allowed domains that is
    no user yet, a free account (Stage 5D) when sign-up is open."""
    try:
        return identity.login_from_claims(session, claims)
    except IdentityError as exc:
        domain = str(claims.get("email") or "").rpartition("@")[2]
        outside = f"accounts of {domain} cannot sign in here"
        if not settings.free_signup_enabled or str(exc) != outside:
            raise
        if not claims.get("email_verified", False):
            raise
        subject = str(claims.get("sub") or "").strip()
        set_tenant(session, SYSTEM_TENANT)
        # The subject look-up cannot filter by tenant (it is how the tenant is found);
        # once known, the row is read again by id and tenant before it is touched.
        found = session.scalar(select(AppUser.tenant_id).where(AppUser.oidc_subject == subject))
        if found is not None:
            set_tenant(session, found)
            existing = session.scalar(
                select(AppUser).where(AppUser.oidc_subject == subject, AppUser.tenant_id == found)
            )
            if existing is None or existing.status != "active":
                raise IdentityError("this account is disabled") from exc
            existing.last_login_at = datetime.now(UTC)
            session.commit()
            return existing
        _, user = signup(
            session,
            email=str(claims.get("email") or ""),
            display_name=str(claims.get("name") or claims.get("email") or ""),
            oidc_subject=subject,
        )
        return user


@router.post("/signup", status_code=201)
def programmatic_signup(
    body: SignupIn, request: Request, session: SessionDep, settings: SettingsDep
) -> Response:
    """A free sign-up without the browser dance: the provider's code is exchanged as the
    callback would and a session opened. The same rules as the callback: a verified
    address, outside the enterprise domains, no account yet."""
    if not settings.session_secret:
        raise AppError("dependency_unavailable", "sign-in is not configured (SESSION_SECRET)")
    if not settings.free_signup_enabled:
        raise AppError("login_refused", "free sign-up is closed")
    try:
        claims = _provider(request).exchange(body.code, _redirect_uri(settings), "")
        user = _login_or_signup(session, settings, _identity(request), claims)
    except (OidcError, IdentityError, LibraryError) as exc:
        raise AppError("login_refused", str(exc)) from exc
    token = _identity(request).open_session(session, user)
    response = Response(status_code=201)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(settings.session_hours * 3600),
        httponly=True,
        secure=_secure(settings),
        samesite="lax",
        path="/",
    )
    return response


# Failed password sign-ins per username and per address, in this process: five in fifteen
# minutes and the next attempts are refused until the window has passed.
LOCK_FAILURES = 5
LOCK_SECONDS = 15 * 60
_failures: dict[str, deque[float]] = {}
_failures_lock = threading.Lock()


def _client(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "")


def _locked(keys: list[str], now: float) -> bool:
    with _failures_lock:
        for key in keys:
            seen = _failures.get(key)
            while seen and seen[0] < now - LOCK_SECONDS:
                seen.popleft()
            if seen and len(seen) >= LOCK_FAILURES:
                return True
    return False


def _fail(keys: list[str], now: float) -> None:
    with _failures_lock:
        for key in keys:
            _failures.setdefault(key, deque()).append(now)


def _clear(keys: list[str]) -> None:
    with _failures_lock:
        for key in keys:
            _failures.pop(key, None)


@router.post("/password", status_code=204)
def password_login(
    body: PasswordLoginIn, request: Request, session: SessionDep, settings: SettingsDep
) -> Response:
    """Sign in with a username and password (2026-10-31): the same browser session as the
    provider's sign-in. Five failures in fifteen minutes for a username or an address lock
    further attempts for the rest of the window."""
    now = time.time()
    keys = [f"user:{body.username.strip().lower()}", f"ip:{_client(request)}"]
    if _locked(keys, now):
        raise AppError("login_locked")
    try:
        user = _identity(request).login_with_password(session, body.username, body.password)
    except IdentityError as exc:
        _fail(keys, now)
        raise AppError("login_failed") from exc
    _clear(keys[:1])
    token = _identity(request).open_session(session, user)
    response = Response(status_code=204)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(settings.session_hours * 3600),
        httponly=True,
        secure=_secure(settings),
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", status_code=204)
def logout(request: Request, session: SessionDep, settings: SettingsDep) -> Response:
    """End the browser session: the row is revoked and the cookie cleared."""
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        _identity(request).revoke_session(session, raw)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=MeOut)
def me(request: Request) -> MeOut:
    """The principal of the request: the signed-in user, the API key or the review link."""
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None:
        raise AppError("login_required")
    return MeOut(
        kind=principal.kind,
        name=principal.name,
        role=principal.role,
        tenant_id=principal.tenant_id,
        read_tenants=list(principal.read_tenants),
        scopes=list(principal.scopes),
        user_id=principal.user_id,
    )
