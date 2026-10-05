import re
from typing import Annotated

from fastapi import APIRouter, Header
from sqlalchemy import select

from api.deps import (
    ActorDep,
    CatalogDep,
    ReviewDep,
    ReviewStateDep,
    SessionDep,
    SettingsDep,
    TenantDep,
    TendersDep,
    TokensDep,
)
from api.middleware.errors import AppError
from api.middleware.review_token import ID
from api.v1.schemas.tenders import (
    ReviewSessionOut,
    ReviewTokenCreate,
    ReviewTokenOut,
    SnapshotOut,
)
from core.models import Document
from tender.models import ReviewToken, TenderVersion, TenderVersionDocument
from tender.services import review as reviews
from tender.services.review import TenderReview
from tender.services.tenders import TenderError

router = APIRouter(tags=["review"])
_SHA = re.compile(r"/files/(?:documents|renders)/([0-9a-f]{64})[./]")


def _token(session: SessionDep, tenant_id: str, token_id: str) -> ReviewToken:
    return session.scalars(
        select(ReviewToken).where(ReviewToken.id == token_id, ReviewToken.tenant_id == tenant_id)
    ).one()


def review_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/review/{token}"


@router.post("/review-tokens", response_model=ReviewTokenOut, status_code=201)
def create_review_token(
    body: ReviewTokenCreate,
    session: SessionDep,
    tenders: TendersDep,
    tokens: TokensDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> ReviewTokenOut:
    """A review link for one tender and one reviewer, valid for 30 days. An earlier link
    for the tender stops working. Not reachable with a review token or from outside."""
    try:
        tender = tenders.get(session, body.tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {body.tender_id} does not exist") from exc
    try:
        token = tokens.create(session, tender, body.reviewer_name, created_by=actor)
    except ValueError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return ReviewTokenOut(
        url=review_url(settings.public_base_url, token.token),
        token=token.token,
        tender_id=token.tender_id,
        reviewer_name=token.reviewer_name,
        expires_at=token.expires_at,
    )


@router.get("/review-session", response_model=ReviewSessionOut)
def get_review_session(
    session: SessionDep, review: ReviewDep, tenant_id: TenantDep
) -> ReviewSessionOut:
    """Who the review token is and which tender it opens."""
    if review is None:
        raise AppError("review_link_required")
    token = _token(session, tenant_id, review.token_id)
    return ReviewSessionOut(
        tender_id=token.tender_id,
        reviewer_name=token.reviewer_name,
        expires_at=token.expires_at,
        completed_at=token.completed_at,
    )


@router.get("/tenders/{tender_id}/review", response_model=TenderReview)
def get_tender_review(
    tender_id: str,
    session: SessionDep,
    tenders: TendersDep,
    review_state: ReviewStateDep,
    catalog: CatalogDep,
) -> TenderReview:
    """The tender as the reviewer sees it: every field once, with what each version says
    about it and the entry to decide (the latest version that states the field)."""
    try:
        tender = tenders.get(session, tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {tender_id} does not exist") from exc
    return reviews.tender_review(session, catalog, tenders, review_state, tender)


@router.post("/tenders/{tender_id}/complete-review", response_model=SnapshotOut, status_code=201)
def complete_review(
    tender_id: str,
    session: SessionDep,
    tenders: TendersDep,
    review_state: ReviewStateDep,
    catalog: CatalogDep,
    review: ReviewDep,
    tenant_id: TenantDep,
) -> SnapshotOut:
    """Complete the review of the token's tender: refused while a required field has no
    decision. Marks the token completed and the tender reviewed, and stores the current
    view as the snapshot the gold set is made from."""
    if review is None:
        raise AppError("review_link_required", "a review is completed with its review link")
    try:
        tender = tenders.get(session, tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {tender_id} does not exist") from exc
    token = _token(session, tenant_id, review.token_id)
    try:
        row = reviews.complete_review(session, catalog, tenders, review_state, tender, token)
    except TenderError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return SnapshotOut(
        id=row.id,
        tender_id=row.tender_id,
        reviewer=row.reviewer,
        created_at=row.created_at,
        snapshot=row.snapshot,
    )


@router.get("/tenders/{tender_id}/snapshot", response_model=SnapshotOut)
def get_snapshot(tender_id: str, session: SessionDep, tenders: TendersDep) -> SnapshotOut:
    """The final values of the tender's latest completed review."""
    try:
        tender = tenders.get(session, tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {tender_id} does not exist") from exc
    row = reviews.latest_snapshot(session, tender)
    if row is None:
        raise AppError("not_found", "this tender has no completed review")
    return SnapshotOut(
        id=row.id,
        tender_id=row.tender_id,
        reviewer=row.reviewer,
        created_at=row.created_at,
        snapshot=row.snapshot,
    )


@router.get("/files-auth", status_code=204)
def authorise_file(
    session: SessionDep,
    tenant_id: TenantDep,
    review: ReviewDep,
    x_forwarded_uri: Annotated[str | None, Header()] = None,
) -> None:
    """Asked by the proxy before it serves a stored file (a PDF or a page image): the file
    must belong to a document of the review token's tender."""
    if review is None:
        return
    found = _SHA.search(x_forwarded_uri or "")
    if found is None:
        raise AppError("not_found", "no such file")
    linked = session.scalar(
        select(TenderVersionDocument.id)
        .join(TenderVersion, TenderVersion.id == TenderVersionDocument.tender_version_id)
        .join(Document, Document.id == TenderVersionDocument.document_id)
        .where(
            Document.tenant_id == tenant_id,
            TenderVersionDocument.tenant_id == tenant_id,
            TenderVersion.tenant_id == tenant_id,
            Document.sha256 == found.group(1),
            TenderVersion.tender_id == review.tender_id,
        )
        .limit(1)
    )
    if linked is None:
        raise AppError("not_found", "no such file")


__all__ = ["ID", "router"]
