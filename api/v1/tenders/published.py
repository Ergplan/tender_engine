"""The client-facing output of a tender (Stage 5C): the published view of canonical facts
with their evidence pages, the same as a PDF with a page-reference appendix, the changelog
across versions, and tenders side by side. Never a candidate: what is not reviewed is a
marked gap."""

from pathlib import Path

from fastapi import APIRouter, Query, Response
from sqlalchemy.orm import Session

from api.deps import CatalogDep, SessionDep, SettingsDep, TendersDep
from api.middleware.errors import AppError
from api.v1.schemas.published import ChangelogOut, CompareOut, PublishedOut
from tender.models import Tender
from tender.services.changelog import changelog
from tender.services.compare import MAX_TENDERS, compare_tenders
from tender.services.publication import publication_state
from tender.services.published import published_tender
from tender.services.published_pdf import render_pdf
from tender.services.tenders import TenderService

router = APIRouter(tags=["published"])


def _tender(tenders: TenderService, session: Session, tender_id: str) -> Tender:
    try:
        return tenders.get(session, tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {tender_id} does not exist") from exc


def _results_root(settings: SettingsDep) -> Path | None:
    return Path(settings.results_root) if settings.results_root else None


@router.get("/tenders/compare", response_model=CompareOut)
def compare(
    session: SessionDep,
    tenders: TendersDep,
    catalog: CatalogDep,
    settings: SettingsDep,
    ids: str = Query(..., description="Comma-separated tender ids, at most six"),
) -> CompareOut:
    """Tenders side by side: fields as rows, tenders as columns, provenance on every cell,
    a field not reviewed marked as such. A tender whose publication is suspended is left
    out with the reason."""
    wanted = [item.strip() for item in ids.split(",") if item.strip()]
    if not wanted:
        raise AppError("validation_failed", "give at least one tender id")
    if len(wanted) > MAX_TENDERS:
        raise AppError("validation_failed", f"at most {MAX_TENDERS} tenders can be compared")
    rows = [_tender(tenders, session, tender_id) for tender_id in wanted]
    return compare_tenders(session, catalog, rows, results_root=_results_root(settings))


@router.get("/tenders/{tender_id}/published", response_model=PublishedOut)
def get_published(
    tender_id: str,
    session: SessionDep,
    tenders: TendersDep,
    catalog: CatalogDep,
    settings: SettingsDep,
) -> PublishedOut:
    """The published view: canonical facts only, each with the version that set it, its
    evidence pages, the review date and the reviewer's role; the publication state with
    its banner; a field without a fact as a gap with its reason and the likely page. While
    an unreviewed version touches a critical field the view carries the suspension and the
    amending documents instead of values."""
    tender = _tender(tenders, session, tender_id)
    return published_tender(session, catalog, tender, results_root=_results_root(settings))


@router.get("/tenders/{tender_id}/published.pdf", response_class=Response)
def get_published_pdf(
    tender_id: str,
    session: SessionDep,
    tenders: TendersDep,
    catalog: CatalogDep,
    settings: SettingsDep,
) -> Response:
    """The published view as a PDF: cover, facts by section with a reference number each,
    the changelog, and an appendix of page references."""
    tender = _tender(tenders, session, tender_id)
    view = published_tender(session, catalog, tender, results_root=_results_root(settings))
    data = render_pdf(view, changelog(session, catalog, tender))
    name = f"{tender.slug or tender.id}-published.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


@router.get("/tenders/{tender_id}/changes", response_model=ChangelogOut)
def get_changes(
    tender_id: str, session: SessionDep, tenders: TendersDep, catalog: CatalogDep
) -> ChangelogOut:
    """The changelog across versions: per version, the facts it changed (old to new, a
    withdrawal flagged) with their evidence, decision date and reviewer role; an
    unreviewed version lists the fields it may touch, by path only."""
    tender = _tender(tenders, session, tender_id)
    log = changelog(session, catalog, tender)
    if publication_state(session, catalog, tender).state == "publication_suspended":
        # A suspended tender publishes no values, old or new: the versions and what each
        # may touch stay, the changed values do not.
        for version in log.versions:
            version.changes = []
    return log
