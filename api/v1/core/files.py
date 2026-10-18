"""Stored files served by the API itself (Stage 5C): `GET /files/documents/<sha>.pdf` and
`GET /files/renders/<sha>/<n>.png` straight from the storage backend, for the Cloud Run
deployment where no proxy serves /data from disk. The check is the one `/files-auth` makes
for the proxy: the file must belong to a document of the caller's review link's tender; a
request from outside without a link is refused. Locally Caddy keeps serving the files
from disk after asking `/files-auth`, and this route is simply unused.
"""

import re
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import SessionDep, SettingsDep, StorageDep, TenantDep
from api.middleware.errors import AppError
from api.middleware.review_token import (
    PUBLIC_HEADER,
    TOKEN_COOKIE,
    TOKEN_ERRORS,
    TOKEN_HEADER,
    ReviewContext,
)
from core.models import Document
from tender.models import TenderVersion, TenderVersionDocument
from tender.services.tokens import TokenError, TokenService

router = APIRouter(tags=["files"])
KEY = re.compile(r"^(documents/([0-9a-f]{64})\.pdf|renders/([0-9a-f]{64})/\d+\.png)$")
CACHE = "private, max-age=86400, immutable"
RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def file_is_linked(session: Session, tenant_id: str, sha256: str, tender_id: str) -> bool:
    """Whether a stored file (by its document's sha256) belongs to the tender."""
    return (
        session.scalar(
            select(TenderVersionDocument.id)
            .join(TenderVersion, TenderVersion.id == TenderVersionDocument.tender_version_id)
            .join(Document, Document.id == TenderVersionDocument.document_id)
            .where(
                Document.tenant_id == tenant_id,
                TenderVersionDocument.tenant_id == tenant_id,
                TenderVersion.tenant_id == tenant_id,
                Document.sha256 == sha256,
                TenderVersion.tender_id == tender_id,
            )
            .limit(1)
        )
        is not None
    )


def _review_of(request: Request, session: Session, tenant_id: str) -> ReviewContext | None:
    """The review link behind the request. The token middleware resolves links only under
    /api/v1, so this route resolves the cookie or header itself, the same way."""
    review: ReviewContext | None = getattr(request.state, "review", None)
    if review is not None:
        return review
    token = request.headers.get(TOKEN_HEADER) or request.cookies.get(TOKEN_COOKIE)
    if not token:
        return None
    try:
        row = TokenService(tenant_id).resolve(session, token)
    except TokenError as exc:
        raise AppError(TOKEN_ERRORS[exc.reason]) from exc
    return ReviewContext(
        token_id=row.id,
        tender_id=row.tender_id,
        reviewer=row.reviewer_name,
        completed=row.completed_at is not None,
    )


@router.get("/files/{path:path}")
def get_file(
    path: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    tenant_id: TenantDep,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """A stored PDF or page image. A request from outside needs the review link of the
    tender the file belongs to (header or cookie); one byte range is honoured for the PDF
    viewer."""
    found = KEY.match(path)
    if found is None:
        raise AppError("not_found", "no such file")
    sha256 = found.group(2) or found.group(3)
    review = _review_of(request, session, tenant_id)
    if review is None and PUBLIC_HEADER in request.headers:
        raise AppError("review_link_required")
    if review is not None and not file_is_linked(session, tenant_id, sha256, review.tender_id):
        raise AppError("not_found", "no such file")
    if not storage.exists(path):
        raise AppError("not_found", "no such file")
    data = storage.get(path)
    media = "application/pdf" if path.endswith(".pdf") else "image/png"
    headers = {"Cache-Control": CACHE, "Accept-Ranges": "bytes"}
    wanted = RANGE.match(range_header or "")
    if wanted is None:
        return Response(content=data, media_type=media, headers=headers)
    start_text, end_text = wanted.groups()
    total = len(data)
    if start_text:
        start = int(start_text)
        end = min(int(end_text), total - 1) if end_text else total - 1
    else:
        # A suffix range: the last N bytes.
        start, end = max(total - int(end_text or 0), 0), total - 1
    if start > end or start >= total:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{total}"})
    headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return Response(
        content=data[start : end + 1], status_code=206, media_type=media, headers=headers
    )
