"""Every change asked of the API leaves a line in the audit log: who (the reviewer of the
token, or the internal caller), which request, and how it ended. The writes themselves are
audited where they happen, in the services; this is the record of the request around them,
including the ones that were refused.
"""

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError

from core.services import audit

log = logging.getLogger("api")
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def audit_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.method not in READ_METHODS and request.url.path.startswith("/api/v1/"):
            await run_in_threadpool(_record, request, response.status_code)
        return response


def _record(request: Request, status: int) -> None:
    review = getattr(request.state, "review", None)
    actor = review.reviewer if review else (request.headers.get("x-reviewer") or "api").strip()
    try:
        with request.app.state.session_factory() as session:
            audit.record(
                session,
                tenant_id=request.app.state.settings.tenant_id,
                actor=actor[:200] or "api",
                action=f"http_{request.method.lower()}",
                table_name="request",
                row_id=str(getattr(request.state, "request_id", ""))[:32],
                after={
                    "path": request.url.path,
                    "status": status,
                    "review_token_id": review.token_id if review else None,
                },
            )
            session.commit()
    except SQLAlchemyError:
        log.exception("request audit could not be written")
