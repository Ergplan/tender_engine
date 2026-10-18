"""The consent page of the library's OAuth server (Stage 5D).

The SDK's `/authorize` sends the browser here with the request signed; a signed-in user
sees what the client asks for and approves in one click, which issues the code and sends
the browser back to the client. A visitor without a session is sent to sign in first.
"""

from html import escape
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from api.deps import SessionDep, SettingsDep
from api.middleware.errors import AppError
from core.db import set_tenant
from core.models import AppUser
from mcpserver.auth import LibraryOAuthProvider, read_request

router = APIRouter(prefix="/oauth", tags=["auth"])


def _page(client: str, scopes: list[str], token: str) -> str:
    wants = ", ".join(escape(s) for s in scopes)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Allow access</title></head><body style='font-family:system-ui;max-width:32rem;"
        "margin:4rem auto'>"
        f"<h1>Allow {escape(client)}?</h1>"
        f"<p>It asks to read on your behalf: <strong>{wants}</strong> — reviewed tender facts, "
        "never a write. You can revoke it from the admin page.</p>"
        "<form method='post'>"
        f"<input type='hidden' name='request' value='{escape(token)}'>"
        "<button type='submit' name='decision' value='allow' style='padding:.6rem 1rem'>"
        "Allow</button> "
        "<button type='submit' name='decision' value='deny' style='padding:.6rem 1rem'>"
        "Deny</button>"
        "</form></body></html>"
    )


@router.get("/consent", response_class=HTMLResponse)
def consent(request: Request, settings: SettingsDep, session: SessionDep) -> Response:
    """The consent page: needs a signed-in user; otherwise sends them to sign in."""
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.kind != "user":
        here = str(request.url.path) + ("?" + str(request.url.query) if request.url.query else "")
        return RedirectResponse(f"/api/v1/auth/login?{urlencode({'next': here})}", status_code=302)
    token = request.query_params.get("request", "")
    payload = read_request(settings.session_secret, token) if settings.session_secret else None
    if payload is None:
        raise AppError("validation_failed", "the authorization request is missing or expired")
    return HTMLResponse(
        _page(str(payload.get("client_name") or payload["client_id"]), payload["scopes"], token)
    )


@router.post("/consent")
def decide(
    request: Request,
    settings: SettingsDep,
    session: SessionDep,
    decision: Annotated[str, Form()],
    request_token: Annotated[str, Form(alias="request")],
) -> Response:
    """Allow issues a code and returns the browser to the client; deny returns an error."""
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.kind != "user":
        return RedirectResponse("/api/v1/auth/login", status_code=302)
    payload = (
        read_request(settings.session_secret, request_token) if settings.session_secret else None
    )
    if payload is None:
        raise AppError("validation_failed", "the authorization request is missing or expired")
    redirect = str(payload["redirect_uri"])
    if decision != "allow":
        query = {"error": "access_denied", "state": payload.get("state") or ""}
        return RedirectResponse(f"{redirect}?{urlencode(query)}", status_code=302)
    set_tenant(session, principal.tenant_id, principal.read_tenants)
    user = session.scalar(
        select(AppUser).where(
            AppUser.id == principal.user_id, AppUser.tenant_id == principal.tenant_id
        )
    )
    if user is None:
        raise AppError("not_found", "the signed-in user is gone")
    provider = LibraryOAuthProvider(
        settings, request.app.state.session_factory, request.app.state.identity
    )
    code = provider.issue_code(session, payload, user)
    query = {"code": code, "state": payload.get("state") or ""}
    return RedirectResponse(f"{redirect}?{urlencode(query)}", status_code=302)
