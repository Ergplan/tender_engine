"""Award results (Stage 6). An award is reviewed with the same approval route as a tender
(`POST /approvals`, scoped by the award's review link); these routes list the imported
publications, serve the reviewer's view and the core review state, complete a review, and
give a reader the approved rows and nothing else."""

from fastapi import APIRouter
from sqlalchemy import select

from api.deps import AwardsDep, ReviewDep, ReviewStateDep, SessionDep, TenantDep, TendersDep
from api.middleware.errors import AppError
from api.v1.schemas.awards import AwardOut
from core.services.review_state import ReviewState
from tender.models import Award, ReviewToken
from tender.services.awards import AwardError, AwardResults, AwardReview, TenderAwards

router = APIRouter(tags=["awards"])


def _out(award: Award) -> AwardOut:
    return AwardOut(
        id=award.id,
        source_id=award.source_id,
        source_name=award.source_name,
        source_url=award.source_url,
        source_sha256=award.source_sha256,
        dataset=award.dataset,
        dataset_procurer=award.procurer,
        dataset_reference=award.reference,
        dataset_result_kind=award.result_kind,
        dataset_verification=award.verification,
        row_count=award.row_count,
        document_id=award.document_id,
        tender_id=award.tender_id,
        tender_link_basis=award.tender_link_basis,
        tender_link_page=award.tender_link_page,
        status=award.status,
        created_at=award.created_at,
    )


def _award(awards: AwardsDep, session: SessionDep, award_id: str) -> Award:
    try:
        return awards.get(session, award_id)
    except LookupError as exc:
        raise AppError("not_found", f"award {award_id} does not exist") from exc


@router.get("/awards", response_model=list[AwardOut])
def list_awards(
    session: SessionDep, awards: AwardsDep, tender_id: str | None = None
) -> list[AwardOut]:
    """Every imported result publication, or those linked to one tender."""
    return [_out(award) for award in awards.all(session, tender_id=tender_id)]


@router.get("/awards/{award_id}", response_model=AwardOut)
def get_award(award_id: str, session: SessionDep, awards: AwardsDep) -> AwardOut:
    return _out(_award(awards, session, award_id))


@router.get("/awards/{award_id}/review", response_model=AwardReview)
def get_award_review(
    award_id: str, session: SessionDep, awards: AwardsDep, review_state: ReviewStateDep
) -> AwardReview:
    """The award as the reviewer sees it: every field with its imported candidate, the
    evidence located on the cited page, the validation and the decision."""
    return awards.review(session, review_state, _award(awards, session, award_id))


@router.get("/awards/{award_id}/review-state", response_model=ReviewState)
def get_award_review_state(
    award_id: str, session: SessionDep, awards: AwardsDep, review_state: ReviewStateDep
) -> ReviewState:
    """Core's review state of the award (its one version)."""
    award = _award(awards, session, award_id)
    return review_state.for_object(session, "award", award.id, 1)


@router.get("/awards/{award_id}/results", response_model=AwardResults)
def get_award_results(
    award_id: str, session: SessionDep, awards: AwardsDep, review_state: ReviewStateDep
) -> AwardResults:
    """The award's approved rows and facts; nothing a reviewer did not approve."""
    return awards.results(session, review_state, _award(awards, session, award_id))


@router.post("/awards/{award_id}/complete-review", response_model=AwardOut, status_code=201)
def complete_award_review(
    award_id: str,
    session: SessionDep,
    awards: AwardsDep,
    review_state: ReviewStateDep,
    review: ReviewDep,
    tenant_id: TenantDep,
) -> AwardOut:
    """Complete the review of the link's award: refused while a required field has no
    decision. Marks the link completed and the award reviewed."""
    if review is None:
        raise AppError("review_link_required", "a review is completed with its review link")
    award = _award(awards, session, award_id)
    token = session.scalars(
        select(ReviewToken).where(
            ReviewToken.id == review.token_id, ReviewToken.tenant_id == tenant_id
        )
    ).one()
    try:
        awards.complete_review(session, review_state, award, token)
    except AwardError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc
    return _out(award)


@router.get("/tenders/{tender_id}/awards", response_model=TenderAwards)
def get_tender_awards(
    tender_id: str,
    session: SessionDep,
    tenders: TendersDep,
    awards: AwardsDep,
    review_state: ReviewStateDep,
) -> TenderAwards:
    """The result publications linked to the tender, each with its approved rows only."""
    try:
        tender = tenders.get(session, tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {tender_id} does not exist") from exc
    return awards.tender_awards(session, review_state, tender.id)
