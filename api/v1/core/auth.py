"""Sign-in (Google OIDC), the session cookie, sign-out and "who am I".

The state of a sign-in travels in a short-lived cookie signed with the session secret, so
the callback can tell the sign-in it started from one it did not. The browser session is
an HttpOnly cookie whose value is known only to the login_session row's hash.
"""

import hashlib
import hmac
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from api.deps import SessionDep, SettingsDep
from api.middleware.auth import SESSION_COOKIE
from api.middleware.errors import AppError
from api.v1.schemas.identity import MeOut
from core.config import Settings
from core.services.identity import IdentityError, IdentityService, Principal
from core.services.oidc import OidcError, OidcProvider

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


@router.get("/login", status_code=302)
def login(request: Request, settings: SettingsDep) -> Response:
    """Send the browser to the identity provider. The state and nonce of this sign-in go
    in a signed cookie that lives ten minutes."""
    if not settings.session_secret:
        raise AppError("dependency_unavailable", "sign-in is not configured (SESSION_SECRET)")
    state, nonce = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    expires = str(int(time.time()) + STATE_SECONDS)
    try:
        url = _provider(request).authorization_url(state, nonce, _redirect_uri(settings))
    except OidcError as exc:
        raise AppError("dependency_unavailable", str(exc)) from exc
    response = RedirectResponse(url, status_code=302)
    signature = _sign(settings.session_secret, state, nonce, expires)
    response.set_cookie(
        STATE_COOKIE,
        f"{state}.{nonce}.{expires}.{signature}",
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
    parts = raw.split(".")
    if len(parts) != 4 or not code or not state:
        raise AppError("login_refused", "the sign-in did not start here; start again")
    started_state, nonce, expires, signature = parts
    expected = _sign(settings.session_secret, started_state, nonce, expires)
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
        user = _identity(request).login_from_claims(session, claims)
    except (OidcError, IdentityError) as exc:
        raise AppError("login_refused", str(exc)) from exc
    token = _identity(request).open_session(session, user)
    response = RedirectResponse("/", status_code=302)
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
