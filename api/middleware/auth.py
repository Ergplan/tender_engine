"""Who the request is, and what it may reach (Stage 5C).

Resolution, in order: a review token (the link a reviewer opens; `review_token.py`), the
browser session cookie of a signed-in user, an API key in the Authorization header, the
admin token header (internal automation and the tests). The principal goes on
`request.state.principal`; a review token also sets `request.state.review` as before.

Policy: a request that came through the public proxy (`X-Public-Request`) without a
principal is refused, except the health probe and the sign-in routes. A principal reaches
what its role allows (`ALLOWED_BY_ROLE`); an API key is also rate-limited and metered;
`/admin/*` needs the admin token or an admin's session (an approver may make gold).
Requests made inside the deployment with no identity are not limited, as before.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError

from api.middleware import review_token
from api.middleware.errors import AppError
from core.services.identity import IdentityService, Principal

log = logging.getLogger("api")
API = review_token.API
ADMIN = review_token.ADMIN
SESSION_COOKIE = "tie_session"
BEARER = "bearer "
# Reachable from outside without any identity.
OPEN = {
    f"{API}/health",
    f"{API}/auth/login",
    f"{API}/auth/callback",
    f"{API}/auth/signup",
    # The OAuth consent page sends a visitor without a session to sign in itself.
    f"{API}/oauth/consent",
    # The public correction form (Stage 5D): a claim with an email address, no sign-in.
    f"{API}/public/corrections",
}
ID = review_token.ID

# What each role may call, by method and path under /api/v1. A review token has its own
# list in review_token.py. Admins reach everything.
_READS = (
    r"/auth/me",
    r"/tenders",
    rf"/tenders/{ID}",
    rf"/tenders/{ID}/(versions|view|review|review-state|snapshot|amendments|agent-pass)",
    rf"/tenders/{ID}/agent-pass/{ID}",
    rf"/tenders/{ID}/(published|published\.pdf|changes)",
    r"/tenders/compare",
    r"/schemas/tender/[a-z_]+",
    rf"/documents/{ID}",
    rf"/documents/{ID}/(sections|pages|search)",
    rf"/documents/{ID}/pages/\d+/render",
    r"/files-auth",
    r"/review-session",
    r"/reports/[a-z-]+",
    r"/canonical",
    r"/review-state",
    # The library (Stage 5D): search, matching, the watchlist.
    r"/tenders/search",
    r"/tenders/match",
    r"/me/watchlist",
)
_INTELLIGENCE = (
    rf"/tenders/{ID}/(published|published\.pdf|changes)",
    r"/tenders/compare",
    rf"/tenders/{ID}/model",
    r"/reports/[a-z-]+",
    r"/tenders/search",
    r"/tenders/match",
)
ALLOWED_BY_ROLE: dict[str, tuple[tuple[str, str], ...]] = {
    "reviewer": (
        *((m, p) for m in ("GET",) for p in _READS),
        ("POST", r"/approvals"),
        ("POST", rf"/tenders/{ID}/complete-review"),
        ("POST", r"/auth/logout"),
        # The library (Stage 5D): the model and its assumptions (a free tenant is refused
        # by the route with `tier_required`), the watchlist, a correction.
        ("POST", rf"/tenders/{ID}/model"),
        ("PUT", rf"/tenders/{ID}/assumptions"),
        ("POST", r"/me/watchlist"),
        ("DELETE", r"/me/watchlist"),
        ("POST", r"/public/corrections"),
        # The library's OAuth consent page (an MCP client asking to read on the user's behalf).
        ("GET", r"/oauth/consent"),
        ("POST", r"/oauth/consent"),
    ),
    "api_client": (
        ("GET", r"/auth/me"),
        ("GET", r"/tenders"),
        ("GET", rf"/tenders/{ID}"),
        ("GET", rf"/tenders/{ID}/(versions|view)"),
        ("GET", rf"/tenders/{ID}/(published|published\.pdf|changes)"),
        ("GET", r"/tenders/compare"),
        ("GET", r"/tenders/search"),
        ("GET", r"/tenders/match"),
        ("GET", r"/admin/reliability"),
        ("GET", r"/reports/[a-z-]+"),
        ("GET", r"/schemas/tender/[a-z_]+"),
        ("POST", rf"/tenders/{ID}/model"),
        ("POST", r"/public/corrections"),
    ),
}
ALLOWED_BY_ROLE["approver"] = (*ALLOWED_BY_ROLE["reviewer"], ("POST", r"/admin/gold"))
_COMPILED = {
    role: tuple((method, re.compile(f"^{API}{pattern}$")) for method, pattern in rules)
    for role, rules in ALLOWED_BY_ROLE.items()
}
_METERED = tuple(re.compile(f"^{API}{pattern}$") for pattern in _INTELLIGENCE)
_MODEL = re.compile(rf"^{API}/tenders/{ID}/model$")


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def authenticate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.review = None
        request.state.review_identity = None
        request.state.principal = None
        path = request.url.path
        if not path.startswith(API + "/"):
            return await call_next(request)
        refusal = await run_in_threadpool(_resolve, request)
        if refusal is not None:
            return _refuse(request, refusal)
        principal: Principal | None = request.state.principal
        public = review_token.PUBLIC_HEADER in request.headers
        if principal is None:
            if path.startswith(ADMIN):
                return _refuse(request, "admin_token_required")
            if public and path not in OPEN:
                return _refuse(request, "review_link_required")
            return await call_next(request)
        if principal.kind == "review_token":
            return await call_next(request)
        if not _allowed(principal, request.method, path):
            return _refuse(request, "not_allowed")
        if principal.kind == "api_key":
            limit = await run_in_threadpool(_rate_limit, request, principal)
            if limit is not None:
                await run_in_threadpool(_meter, request, principal, 429, limit)
                return _refuse(request, "rate_limited")
        response = await call_next(request)
        if principal.kind == "api_key" or (
            principal.kind == "user" and any(p.match(path) for p in _METERED)
        ):
            await run_in_threadpool(_meter, request, principal, response.status_code, None)
        return response


def _refuse(request: Request, error_type: str) -> Response:
    return AppError(error_type).response(getattr(request.state, "request_id", ""))


def _resolve(request: Request) -> str | None:
    """Set request.state.principal (and .review for a token). Returns a refusal."""
    settings = request.app.state.settings
    token = request.headers.get(review_token.TOKEN_HEADER) or request.cookies.get(
        review_token.TOKEN_COOKIE
    )
    if token:
        if request.url.path.startswith(ADMIN):
            # A review link never admits to /admin/, whatever else it carries.
            return "admin_token_required"
        refusal = review_token._admit(request, token)
        if refusal is not None:
            return refusal
        review = request.state.review
        request.state.principal = Principal(
            kind="review_token",
            tenant_id=settings.tenant_id,
            read_tenants=(settings.tenant_id,),
            role="reviewer",
            name=review.reviewer,
            token_id=review.token_id,
        )
        return None
    identity: IdentityService = request.app.state.identity
    cookie = request.cookies.get(SESSION_COOKIE)
    authorization = request.headers.get("authorization", "")
    admin_given = request.headers.get(review_token.ADMIN_HEADER, "")
    try:
        with request.app.state.session_factory() as session:
            if cookie:
                principal = identity.resolve_session(session, cookie)
                if principal is None:
                    return "session_expired"
                request.state.principal = principal
                return None
            if authorization.lower().startswith(BEARER):
                principal = identity.resolve_api_key(session, authorization[len(BEARER) :].strip())
                if principal is None:
                    return "api_key_invalid"
                request.state.principal = principal
                return None
    except SQLAlchemyError:
        log.exception("identity could not be resolved")
        return "dependency_unavailable"
    # The admin token opens /admin/* and nothing else, as before Stage 5C: outside it the
    # header is ignored and the request is whatever else it carries.
    if admin_given and request.url.path.startswith(ADMIN):
        if review_token.admin_token_matches(settings, admin_given):
            request.state.principal = Principal(
                kind="admin_token",
                tenant_id=settings.tenant_id,
                read_tenants=(settings.tenant_id, "public"),
                role="admin",
                name="admin-token",
            )
            return None
        return "admin_token_required"
    return None


def _allowed(principal: Principal, method: str, path: str) -> bool:
    if principal.is_admin:
        return True
    if path.startswith(ADMIN) and not (
        principal.role == "approver" and method == "POST" and path == f"{ADMIN}gold"
    ):
        return principal.role == "api_client" and method == "GET" and path == f"{ADMIN}reliability"
    if principal.role == "api_client" and _MODEL.match(path) and "model" not in principal.scopes:
        return False
    return any(
        m == method and pattern.match(path) for m, pattern in _COMPILED.get(principal.role, ())
    )


def _rate_limit(request: Request, principal: Principal) -> str | None:
    identity: IdentityService = request.app.state.identity
    with request.app.state.session_factory() as session:
        return identity.check_rate_limit(session, principal)


def _meter(request: Request, principal: Principal, status: int, detail: str | None) -> None:
    identity: IdentityService = request.app.state.identity
    route: Any = request.scope.get("route")
    template = getattr(route, "path", None) or request.url.path
    tool = f"{request.method} {template.replace('/api/v1', '', 1)}"
    tier = "api" if principal.kind == "api_key" else "enterprise"
    try:
        with request.app.state.session_factory() as session:
            identity.record_usage(
                session,
                principal,
                tool,
                resource_tenant_id=principal.tenant_id,
                status=status,
                tier=tier,
                detail=detail,
            )
    except SQLAlchemyError:
        log.exception("usage could not be recorded")
