"""The library tier's routes (Stage 5D): search and matching over what the principal may
read, the financial model and its assumptions, the watchlist, and the public correction
form. Routes only; the services decide."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy.orm import Session

from api.deps import CatalogDep, PrincipalDep, SessionDep, SettingsDep, TendersDep
from api.middleware.errors import AppError
from api.v1.schemas.library import (
    AssumptionsIn,
    AssumptionsOut,
    CorrectionIn,
    CorrectionOut,
    ModelIn,
    ModelResult,
    SearchResult,
    WatchedTender,
    WatchlistIn,
)
from core.services.identity import Principal, read_tenants_of
from tender.models import Tender
from tender.services import corrections, library
from tender.services.library import Match, NoMatch
from tender.services.tenders import TenderService

router = APIRouter(tags=["library"])


def _tender(tenders: TenderService, session: Session, tender_id: str) -> Tender:
    try:
        return tenders.get(session, tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {tender_id} does not exist") from exc


def _principal(principal: Principal | None, settings_tenant: str) -> Principal:
    """The principal, or the deployment itself for a request made inside it."""
    return principal or Principal(
        kind="admin_token",
        tenant_id=settings_tenant,
        read_tenants=read_tenants_of(settings_tenant),
        role="admin",
        name="internal",
    )


def _paid(session: Session, principal: Principal) -> None:
    if library.is_free(session, principal.tenant_id):
        raise AppError("tier_required")


@router.get("/tenders/search", response_model=SearchResult)
def search(
    session: SessionDep,
    catalog: CatalogDep,
    principal: PrincipalDep,
    settings: SettingsDep,
    q: Annotated[str, Query(max_length=300)] = "",
    tender_type: Annotated[str | None, Query(max_length=30)] = None,
    agency: Annotated[str | None, Query(max_length=200)] = None,
    state: Annotated[str | None, Query(max_length=30)] = None,
) -> SearchResult:
    """Published tenders the caller may read (its own and the public library), narrowed
    by words, type, agency or publication state. A suspended or unreviewed tender is
    absent. Every hit carries its review date, reviewer role and reliability block; the
    response the authority note."""
    who = _principal(principal, settings.tenant_id)
    return library.search_tenders(
        session,
        catalog,
        who.read_tenants,
        query=q,
        tender_type=tender_type,
        agency=agency,
        state=state,
        results_root=Path(settings.results_root) if settings.results_root else None,
    )


@router.get("/tenders/match", response_model=Match | NoMatch)
def match(
    session: SessionDep,
    catalog: CatalogDep,
    principal: PrincipalDep,
    settings: SettingsDep,
    title_or_number: Annotated[str, Query(min_length=1, max_length=300)],
    agency: Annotated[str | None, Query(max_length=200)] = None,
    capacity_mw: Annotated[float | None, Query(gt=0)] = None,
) -> Match | NoMatch:
    """The library tender a document in the caller's hand is, or no_match with up to three
    candidates and what tells them apart. Nothing is ingested or extracted."""
    who = _principal(principal, settings.tenant_id)
    return library.find_matching_tender(
        session,
        catalog,
        settings,
        who.read_tenants,
        title_or_number,
        agency=agency,
        capacity_mw=capacity_mw,
    )


@router.post("/tenders/{tender_id}/model", response_model=ModelResult)
def model(
    tender_id: str,
    body: ModelIn,
    session: SessionDep,
    catalog: CatalogDep,
    tenders: TendersDep,
    principal: PrincipalDep,
    settings: SettingsDep,
) -> ModelResult:
    """The financial model, read-only: the tender's fixed parameters with provenance, the
    assumptions (given now, else saved, else the engine's defaults marked assumed) and the
    engine's figures, labelled indicative. A free tenant is refused (`tier_required`)."""
    who = _principal(principal, settings.tenant_id)
    _paid(session, who)
    tender = _tender(tenders, session, tender_id)
    try:
        return library.model_tender(
            session, catalog, who, tender, body.model_type, body.assumptions
        )
    except library.LibraryError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc


@router.put("/tenders/{tender_id}/assumptions", response_model=AssumptionsOut)
def save_assumptions(
    tender_id: str,
    body: AssumptionsIn,
    session: SessionDep,
    tenders: TendersDep,
    principal: PrincipalDep,
    settings: SettingsDep,
) -> AssumptionsOut:
    """Persist the caller's assumptions for a model of the tender. Separate from the
    model: a read never saves, a save never computes. Never a canonical fact."""
    who = _principal(principal, settings.tenant_id)
    _paid(session, who)
    tender = _tender(tenders, session, tender_id)
    try:
        row = library.upsert_assumptions(session, who, tender, body.model_type, body.assumptions)
    except library.LibraryError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc
    return AssumptionsOut.model_validate(row)


@router.get("/me/watchlist", response_model=list[WatchedTender])
def my_watchlist(
    session: SessionDep,
    catalog: CatalogDep,
    tenders: TendersDep,
    principal: PrincipalDep,
    settings: SettingsDep,
) -> list[WatchedTender]:
    """The tenders the caller follows, with bid deadlines and days remaining. A paid
    tier's tool: a free tenant is refused (`tier_required`)."""
    who = _principal(principal, settings.tenant_id)
    _paid(session, who)
    return library.watchlist(session, catalog, tenders, who)


@router.post("/me/watchlist", response_model=list[WatchedTender], status_code=201)
def watch(
    body: WatchlistIn,
    session: SessionDep,
    catalog: CatalogDep,
    tenders: TendersDep,
    principal: PrincipalDep,
    settings: SettingsDep,
) -> list[WatchedTender]:
    who = _principal(principal, settings.tenant_id)
    _paid(session, who)
    tender = _tender(tenders, session, body.tender_id)
    try:
        library.watchlist_add(session, who, tender)
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc
    return library.watchlist(session, catalog, tenders, who)


@router.delete("/me/watchlist", response_model=list[WatchedTender])
def unwatch(
    body: WatchlistIn,
    session: SessionDep,
    catalog: CatalogDep,
    tenders: TendersDep,
    principal: PrincipalDep,
    settings: SettingsDep,
) -> list[WatchedTender]:
    who = _principal(principal, settings.tenant_id)
    _paid(session, who)
    library.watchlist_remove(session, who, body.tender_id)
    return library.watchlist(session, catalog, tenders, who)


@router.post("/public/corrections", response_model=CorrectionOut, status_code=201)
def open_correction(
    body: CorrectionIn,
    request: Request,
    session: SessionDep,
    catalog: CatalogDep,
    tenders: TendersDep,
    principal: PrincipalDep,
) -> CorrectionOut:
    """A claim that a published field is wrong, from any signed-in principal or from the
    public form (then with an email address). It opens a correction case and queues the
    field for re-review; it never changes a value."""
    tender = _tender(tenders, session, body.tender_id)
    try:
        case = corrections.open_case(
            session,
            catalog,
            tender=tender,
            field_path=body.field_path,
            claimed_error=body.claimed_error,
            reasoning=body.reasoning,
            claimant=principal,
            claimant_email=body.claimant_email,
        )
    except corrections.CorrectionError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return CorrectionOut.model_validate(case)
