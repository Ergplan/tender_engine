"""Review tokens on the API: who the caller is and what they may reach.

A request that carries a review token (the X-Review-Token header, or the review_token
cookie for images and the PDF the browser fetches itself) is that token's reviewer and is
limited to that token's tender: the routes the reviewer screen needs, and nothing else.
An expired, revoked or unknown token is refused with a plain message. A completed review
can be read and no longer changed.

A request that came in through the public proxy (Caddy marks it with X-Public-Request)
and carries no token is refused, whatever it asks for, except the health probe. Requests
made inside the deployment (the management commands, the tests) carry neither and are
not limited. There is no other identity mechanism in phase 1.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import select

from api.middleware.errors import AppError
from tender.models import TenderVersion, TenderVersionDocument
from tender.services.tokens import TokenError, TokenService

TOKEN_HEADER = "x-review-token"
TOKEN_COOKIE = "review_token"
PUBLIC_HEADER = "x-public-request"
API = "/api/v1"
ID = r"[0-9a-f]{32}"
# What a review token may call. {tender} must be the token's tender, {document} one of
# that tender's documents.
ALLOWED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, re.compile(f"^{API}{pattern}$"))
    for method, pattern in (
        ("GET", r"/health"),
        ("GET", r"/review-session"),
        ("GET", r"/files-auth"),
        ("GET", rf"/tenders/(?P<tender>{ID})"),
        ("GET", rf"/tenders/(?P<tender>{ID})/(versions|review|review-state|view|snapshot)"),
        ("POST", rf"/tenders/(?P<tender>{ID})/complete-review"),
        ("GET", r"/schemas/tender/[a-z_]+"),
        ("GET", rf"/documents/(?P<document>{ID})"),
        ("GET", rf"/documents/(?P<document>{ID})/(sections|pages|search)"),
        ("GET", rf"/documents/(?P<document>{ID})/pages/\d+/render"),
        ("POST", r"/approvals"),
    )
)
TOKEN_ERRORS = {
    "unknown": "review_link_invalid",
    "revoked": "review_link_revoked",
    "expired": "review_link_expired",
}


@dataclass(frozen=True)
class ReviewContext:
    """The reviewer behind a request, from their token."""

    token_id: str
    tender_id: str
    reviewer: str
    completed: bool


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def review_token(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.review = None
        path = request.url.path
        if not path.startswith(API + "/"):
            return await call_next(request)
        token = request.headers.get(TOKEN_HEADER) or request.cookies.get(TOKEN_COOKIE)
        public = PUBLIC_HEADER in request.headers
        if not token:
            if public and path != f"{API}/health":
                return _refuse(request, "review_link_required")
            return await call_next(request)
        refusal = await run_in_threadpool(_admit, request, token)
        if refusal is not None:
            return _refuse(request, refusal)
        return await call_next(request)


def _refuse(request: Request, error_type: str) -> Response:
    return AppError(error_type).response(getattr(request.state, "request_id", ""))


def _admit(request: Request, token: str) -> str | None:
    """Resolve the token and check the request against it. Returns the error type of the
    refusal, or None after setting request.state.review."""
    settings = request.app.state.settings
    with request.app.state.session_factory() as session:
        try:
            row = TokenService(settings.tenant_id).resolve(session, token)
        except TokenError as exc:
            return TOKEN_ERRORS[exc.reason]
        context = ReviewContext(
            token_id=row.id,
            tender_id=row.tender_id,
            reviewer=row.reviewer_name,
            completed=row.completed_at is not None,
        )
        match = next(
            (
                found
                for method, pattern in ALLOWED
                if method == request.method and (found := pattern.match(request.url.path))
            ),
            None,
        )
        if match is None:
            return "not_allowed"
        scope = match.groupdict()
        if scope.get("tender") not in (None, context.tender_id):
            return "not_found"
        if scope.get("document") is not None and not _document_of_tender(
            session, settings.tenant_id, scope["document"], context.tender_id
        ):
            return "not_found"
        if context.completed and request.method != "GET":
            return "review_completed"
    request.state.review = context
    return None


def _document_of_tender(session: object, tenant_id: str, document_id: str, tender_id: str) -> bool:
    from sqlalchemy.orm import Session

    assert isinstance(session, Session)
    return (
        session.scalar(
            select(TenderVersionDocument.id)
            .join(TenderVersion, TenderVersion.id == TenderVersionDocument.tender_version_id)
            .where(
                TenderVersionDocument.tenant_id == tenant_id,
                TenderVersion.tenant_id == tenant_id,
                TenderVersionDocument.document_id == document_id,
                TenderVersion.tender_id == tender_id,
            )
            .limit(1)
        )
        is not None
    )
