"""Request id on every response and a typed error payload.

Adapted from tariff-oder services/api/src/tariff_api/errors.py and main.py:67-107:
stable error_type, HTTP status and a user-facing message; stack traces never reach users.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

log = logging.getLogger("api")

ERROR_STATUS: dict[str, tuple[int, str]] = {
    "not_found": (404, "The requested record does not exist."),
    "validation_failed": (422, "The request did not pass validation."),
    "dependency_unavailable": (503, "A required service is not available. Try again shortly."),
    "internal_error": (500, "Something went wrong on our side. The error has been logged."),
}


class AppError(Exception):
    def __init__(self, error_type: str, detail: str | None = None) -> None:
        if error_type not in ERROR_STATUS:
            raise ValueError(f"unknown error_type {error_type!r}")
        super().__init__(detail or error_type)
        self.error_type = error_type
        self.detail = detail

    def response(self, request_id: str) -> JSONResponse:
        status, message = ERROR_STATUS[self.error_type]
        return JSONResponse(
            status_code=status,
            content={
                "error_type": self.error_type,
                "message": message,
                "detail": self.detail,
                "request_id": request_id,
            },
        )


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error on %s", request.url.path)
            response = AppError("internal_error").response(request_id)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return exc.response(request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        return AppError("validation_failed", detail).response(request.state.request_id)
