"""Review tokens on the API: the reviewer behind a link and what the link may reach.

A request that carries a review token (the X-Review-Token header, or the review_token
cookie for images and the PDF the browser fetches itself) is that token's reviewer and is
limited to that token's object: the routes the reviewer screen needs for that tender or,
since Stage 6, that award, and nothing else. An expired, revoked or unknown token is
refused with a plain message. A completed review can be read and no longer changed.

Since Stage 5C the middleware that runs this is api.middleware.auth, which also knows
signed-in users, API keys and the admin token; this module keeps the token's own rules.
"""

import re
import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from tender.services.tokens import TokenError, TokenService, document_belongs

TOKEN_HEADER = "x-review-token"
TOKEN_COOKIE = "review_token"
PUBLIC_HEADER = "x-public-request"
ADMIN_HEADER = "x-admin-token"
API = "/api/v1"
ADMIN = f"{API}/admin/"
ID = r"[0-9a-f]{32}"
# What a review token may call. {tender} must be the token's tender, {award} the token's
# award, {document} one of that object's documents.
ALLOWED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, re.compile(f"^{API}{pattern}$"))
    for method, pattern in (
        ("GET", r"/health"),
        ("GET", r"/review-session"),
        ("GET", r"/files-auth"),
        ("GET", rf"/tenders/(?P<tender>{ID})"),
        (
            "GET",
            rf"/tenders/(?P<tender>{ID})/(versions|review|review-state|view|snapshot|amendments)",
        ),
        ("POST", rf"/tenders/(?P<tender>{ID})/complete-review"),
        ("GET", rf"/awards/(?P<award>{ID})"),
        ("GET", rf"/awards/(?P<award>{ID})/(review|review-state|results)"),
        ("POST", rf"/awards/(?P<award>{ID})/complete-review"),
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
    """The reviewer behind a request, from their token, and the object the token opens."""

    token_id: str
    object_type: str
    object_id: str
    reviewer: str
    completed: bool

    @property
    def tender_id(self) -> str | None:
        """The token's tender; None for an award's token."""
        return self.object_id if self.object_type == "tender" else None

    @property
    def scope(self) -> tuple[str, str]:
        return (self.object_type, self.object_id)


def admin_token_matches(settings: Any, given: str) -> bool:
    """The admin token header (settings.admin_token; empty means it opens nothing)."""
    expected = settings.admin_token
    return bool(expected and given and secrets.compare_digest(given, expected))


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
            object_type=row.object_type,
            object_id=row.object_id,
            reviewer=row.reviewer_name,
            completed=row.completed_at is not None,
        )
        # Who asked is known from here on, also if the request is then refused. Only the
        # request audit reads this; access is granted by request.state.review alone.
        request.state.review_identity = context
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
        for kind in ("tender", "award"):
            if scope.get(kind) is not None and (kind, scope[kind]) != context.scope:
                return "not_found"
        if scope.get("document") is not None and not document_belongs(
            session,
            settings.tenant_id,
            context.object_type,
            context.object_id,
            document_id=scope["document"],
        ):
            return "not_found"
        if context.completed and request.method != "GET":
            return "review_completed"
    request.state.review = context
    return None
