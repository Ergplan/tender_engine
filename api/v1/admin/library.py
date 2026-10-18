"""An admin's library routes (Stage 5D): correction cases and publication holds (takedown).
Behind the admin policy of api.middleware.auth."""

from fastapi import APIRouter
from sqlalchemy import select

from api.deps import ActorDep, PrincipalDep, SessionDep, SettingsDep, TendersDep
from api.middleware.errors import AppError
from api.v1.schemas.library import CorrectionOut, CorrectionResolve, HoldIn, HoldOut
from core.services.identity import read_tenants_of
from tender.models import CorrectionCase, PublicationHold
from tender.services import corrections

router = APIRouter(prefix="/admin", tags=["admin"])


def _tenants(principal: PrincipalDep, settings: SettingsDep) -> tuple[str, ...]:
    return principal.read_tenants if principal else read_tenants_of(settings.tenant_id)


@router.get("/corrections", response_model=list[CorrectionOut])
def list_corrections(
    session: SessionDep,
    principal: PrincipalDep,
    settings: SettingsDep,
    status: str | None = None,
) -> list[CorrectionCase]:
    """The correction cases on the tenders the admin may read, oldest first."""
    return corrections.cases(session, _tenants(principal, settings), status=status)


@router.post("/corrections/{case_id}/resolve", response_model=CorrectionOut)
def resolve_correction(
    case_id: str,
    body: CorrectionResolve,
    session: SessionDep,
    principal: PrincipalDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> CorrectionCase:
    """Close a case as accepted or rejected. The value, if it changed, changed through
    the reviewer's approval; this records the outcome."""
    case = session.scalar(
        select(CorrectionCase).where(
            CorrectionCase.id == case_id,
            CorrectionCase.tenant_id.in_(list(_tenants(principal, settings))),
        )
    )
    if case is None:
        raise AppError("not_found", f"correction case {case_id} does not exist")
    try:
        return corrections.resolve_case(
            session, case, accepted=body.accepted, resolution=body.resolution, by=actor
        )
    except corrections.CorrectionError as exc:
        raise AppError("conflict", str(exc)) from exc


@router.post("/holds", response_model=HoldOut, status_code=201)
def place_hold(
    body: HoldIn, session: SessionDep, tenders: TendersDep, actor: ActorDep
) -> PublicationHold:
    """Suspend a tender's publication: a takedown (an agency's or rights-holder's request,
    also recorded in docs/KNOWN-GAPS.md) or a correction hold."""
    try:
        tender = tenders.get(session, body.tender_id)
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc
    try:
        return corrections.place_hold(
            session,
            tender=tender,
            kind=body.kind,
            reason=body.reason,
            requested_by=actor,
            requested_at=body.requested_at,
        )
    except corrections.CorrectionError as exc:
        raise AppError("validation_failed", str(exc)) from exc


@router.get("/holds", response_model=list[HoldOut])
def list_holds(
    session: SessionDep, principal: PrincipalDep, settings: SettingsDep
) -> list[PublicationHold]:
    return list(
        session.scalars(
            select(PublicationHold)
            .where(PublicationHold.tenant_id.in_(list(_tenants(principal, settings))))
            .order_by(PublicationHold.created_at)
        )
    )


@router.delete("/holds/{hold_id}", response_model=HoldOut)
def lift_hold(
    hold_id: str,
    session: SessionDep,
    principal: PrincipalDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> PublicationHold:
    """Lift a hold: publication follows the review state again."""
    hold = session.scalar(
        select(PublicationHold).where(
            PublicationHold.id == hold_id,
            PublicationHold.tenant_id.in_(list(_tenants(principal, settings))),
        )
    )
    if hold is None:
        raise AppError("not_found", f"hold {hold_id} does not exist")
    try:
        return corrections.lift_hold(session, hold, by=actor)
    except corrections.CorrectionError as exc:
        raise AppError("conflict", str(exc)) from exc
