import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header
from sqlalchemy import select

from api.deps import (
    ActorDep,
    AwardsDep,
    CatalogDep,
    DerivedWriterDep,
    ReviewDep,
    ReviewStateDep,
    SchemasDep,
    SessionDep,
    SettingsDep,
    SummaryWriterDep,
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
from evals.threeway import low_review_fields
from tender.models import ReviewToken
from tender.services import review as reviews
from tender.services.amendments import TenderAmendments, tender_amendments
from tender.services.review import TenderReview
from tender.services.tenders import TenderError
from tender.services.tokens import document_belongs

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
    awards: AwardsDep,
    tokens: TokensDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> ReviewTokenOut:
    """A review link for one object (a tender, or an award since Stage 6) and one
    reviewer, valid for 30 days. An earlier link for the object stops working. Not
    reachable with a review token or from outside."""
    if (body.tender_id is None) == (body.award_id is None):
        raise AppError("validation_failed", "name exactly one of tender_id and award_id")
    if body.tender_id is not None:
        try:
            tender = tenders.get(session, body.tender_id)
        except LookupError as exc:
            raise AppError("not_found", f"tender {body.tender_id} does not exist") from exc
        object_type, object_id = "tender", tender.id
    else:
        try:
            award = awards.get(session, body.award_id or "")
        except LookupError as exc:
            raise AppError("not_found", f"award {body.award_id} does not exist") from exc
        object_type, object_id = "award", award.id
    try:
        token = tokens.create_for(
            session, object_type, object_id, body.reviewer_name, created_by=actor
        )
    except ValueError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return ReviewTokenOut(
        url=review_url(settings.public_base_url, token.token),
        token=token.token,
        object_type=token.object_type,
        object_id=token.object_id,
        tender_id=token.tender_id,
        reviewer_name=token.reviewer_name,
        expires_at=token.expires_at,
    )


@router.get("/review-session", response_model=ReviewSessionOut)
def get_review_session(
    session: SessionDep, review: ReviewDep, tenant_id: TenantDep
) -> ReviewSessionOut:
    """Who the review token is and which object (tender or award) it opens."""
    if review is None:
        raise AppError("review_link_required")
    token = _token(session, tenant_id, review.token_id)
    return ReviewSessionOut(
        object_type=token.object_type,
        object_id=token.object_id,
        tender_id=token.tender_id,
        reviewer_name=token.reviewer_name,
        expires_at=token.expires_at,
        completed_at=token.completed_at,
        round_no=token.round_no,
        from_version=token.from_version,
    )


@router.get("/tenders/{tender_id}/review", response_model=TenderReview)
def get_tender_review(
    tender_id: str,
    session: SessionDep,
    tenders: TendersDep,
    review_state: ReviewStateDep,
    catalog: CatalogDep,
    writer: SummaryWriterDep,
    deriver: DerivedWriterDep,
    review_link: ReviewDep,
    tenant_id: TenantDep,
    settings: SettingsDep,
) -> TenderReview:
    """The tender as the reviewer sees it: every field once, with what each version says
    about it and the entry to decide (the latest version that states the field). Through
    a review link that opens a round, the round's scope and counts."""
    try:
        tender = tenders.get(session, tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {tender_id} does not exist") from exc
    token = _token(session, tenant_id, review_link.token_id) if review_link else None
    review = reviews.tender_review(
        session,
        catalog,
        tenders,
        review_state,
        tender,
        round_no=token.round_no if token else None,
        from_version=token.from_version if token else None,
        # Stage 5B's production confidence rule: the fields the three-way comparison found
        # reviewer, engine and agent agreeing on are shown with low-review emphasis.
        low_review=low_review_fields(
            tenant_id, Path(settings.results_root) if settings.results_root else None
        ),
    )
    state = writer.state(session, tender, review)
    review.summary = state.model_dump()
    review.derived = deriver.state(session, tender, review).model_dump()
    # While a summary is being written the summary field may have no entry to decide for
    # a moment; the review cannot be completed across that gap.
    review.can_complete = review.can_complete and not state.being_written and not state.waiting_for
    return review


@router.get("/tenders/{tender_id}/amendments", response_model=TenderAmendments)
def get_tender_amendments(
    tender_id: str,
    session: SessionDep,
    tenders: TendersDep,
    review_state: ReviewStateDep,
    catalog: CatalogDep,
    schemas: SchemasDep,
) -> TenderAmendments:
    """The tender's later versions, each with the fields it states against what stood
    before them, and that version's reading to decide. A projection of the review."""
    try:
        tender = tenders.get(session, tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {tender_id} does not exist") from exc
    return tender_amendments(session, catalog, tenders, review_state, schemas, tender)


@router.post("/tenders/{tender_id}/complete-review", response_model=SnapshotOut, status_code=201)
def complete_review(
    tender_id: str,
    session: SessionDep,
    tenders: TendersDep,
    review_state: ReviewStateDep,
    catalog: CatalogDep,
    review: ReviewDep,
    tenant_id: TenantDep,
    writer: SummaryWriterDep,
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
    state = writer.state(session, tender)
    try:
        row = reviews.complete_review(
            session,
            catalog,
            tenders,
            review_state,
            tender,
            token,
            summary_being_written=state.being_written,
            summary_waiting_for=state.waiting_for,
        )
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
    must belong to a document of the review token's object (its tender or its award)."""
    if review is None:
        return
    found = _SHA.search(x_forwarded_uri or "")
    if found is None:
        raise AppError("not_found", "no such file")
    if not document_belongs(
        session, tenant_id, review.object_type, review.object_id, sha256=found.group(1)
    ):
        raise AppError("not_found", "no such file")


__all__ = ["ID", "router"]
