from fastapi import APIRouter, Response

from api.deps import ApprovalsDep, ReviewerDep, ReviewStateDep, SessionDep
from api.middleware.errors import AppError
from api.v1.schemas.core import ApprovalOut, ApprovalRequest
from core.schemas import UnknownSchemaError
from core.services.approve import ApprovalError
from core.services.review_state import CanonicalFactView, ReviewState

router = APIRouter(tags=["review"])


@router.get("/review-state", response_model=ReviewState)
def get_review_state(
    object_type: str,
    object_id: str,
    session: SessionDep,
    review_state: ReviewStateDep,
    version: int | None = None,
) -> ReviewState:
    """Every field of the object with its best candidate, evidence, validation and approval."""
    try:
        return review_state.for_object(session, object_type, object_id, version)
    except UnknownSchemaError as exc:
        raise AppError("dependency_unavailable", str(exc)) from exc


@router.post("/approvals", response_model=ApprovalOut, status_code=201)
def post_approval(
    body: ApprovalRequest,
    response: Response,
    session: SessionDep,
    approvals: ApprovalsDep,
    reviewer: ReviewerDep,
) -> ApprovalOut:
    """Record a reviewer's decision. This is the only route that produces a canonical fact.
    An identical repeat returns the existing approval with 200 and writes nothing."""
    try:
        outcome = approvals.approve(
            session,
            candidate_id=body.candidate_id,
            decision=body.decision,
            final_value=body.final_value,
            reviewer=reviewer,
            note=body.note,
        )
    except ApprovalError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc
    if not outcome.created:
        response.status_code = 200
    approval = outcome.approval
    return ApprovalOut(
        id=approval.id,
        candidate_id=approval.candidate_id,
        field_path=approval.field_path,
        decision=approval.decision,
        final_value=approval.final_value,
        reviewer=approval.reviewer,
        note=approval.note,
        decided_at=approval.decided_at,
        status=approval.status,
        canonical_fact_id=outcome.canonical_fact.id if outcome.canonical_fact else None,
        feedback_delta_kind=outcome.feedback.delta_kind if outcome.feedback else None,
        created=outcome.created,
    )


@router.get("/canonical", response_model=list[CanonicalFactView])
def get_canonical(
    object_type: str,
    object_id: str,
    session: SessionDep,
    review_state: ReviewStateDep,
    version: int | None = None,
) -> list[CanonicalFactView]:
    """Current canonical facts of an object: approved by a human, with their evidence."""
    return review_state.canonical(session, object_type, object_id, version)
