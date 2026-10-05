"""Request dependencies: settings, db session, tenant, reviewer and tenant-scoped services."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from api.middleware.errors import AppError
from api.middleware.review_token import ReviewContext
from core.config import Settings
from core.schemas import SchemaRegistry
from core.services.approve import ApprovalService
from core.services.extract import ExtractService
from core.services.ingest import IngestService
from core.services.review_state import ReviewStateService
from core.storage import Storage
from tender.services.packs import Catalog
from tender.services.summary import SummaryGuard, SummaryWriter
from tender.services.tenders import TenderService
from tender.services.tokens import TokenService
from tender.services.worker_jobs import summary_writer


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_tenant_id(settings: Annotated[Settings, Depends(get_settings)]) -> str:
    """Phase 1 resolves every request to the single configured tenant."""
    return settings.tenant_id


def get_review(request: Request) -> ReviewContext | None:
    """The reviewer of the request's review token, set by api.middleware.review_token."""
    review: ReviewContext | None = getattr(request.state, "review", None)
    return review


ReviewDep = Annotated[ReviewContext | None, Depends(get_review)]


def get_reviewer(review: ReviewDep, x_reviewer: Annotated[str | None, Header()] = None) -> str:
    """Who decides: the reviewer name of the review token. A request made inside the
    deployment, which carries no token, names the reviewer in the X-Reviewer header."""
    if review is not None:
        return review.reviewer
    if x_reviewer is None or not x_reviewer.strip():
        raise AppError("validation_failed", "the X-Reviewer header is required")
    return x_reviewer.strip()


def get_actor(review: ReviewDep, x_reviewer: Annotated[str | None, Header()] = None) -> str:
    if review is not None:
        return review.reviewer
    return x_reviewer.strip() if x_reviewer and x_reviewer.strip() else "api"


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
TenantDep = Annotated[str, Depends(get_tenant_id)]
ReviewerDep = Annotated[str, Depends(get_reviewer)]
ActorDep = Annotated[str, Depends(get_actor)]


def get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


def get_schemas(request: Request) -> SchemaRegistry:
    schemas: SchemaRegistry = request.app.state.schemas
    return schemas


StorageDep = Annotated[Storage, Depends(get_storage)]
SchemasDep = Annotated[SchemaRegistry, Depends(get_schemas)]


def get_ingest(storage: StorageDep, tenant_id: TenantDep) -> IngestService:
    return IngestService(storage, tenant_id)


def get_extract(
    request: Request, storage: StorageDep, schemas: SchemasDep, tenant_id: TenantDep
) -> ExtractService:
    settings: Settings = request.app.state.settings
    return ExtractService(
        request.app.state.llm,
        storage,
        schemas,
        settings.model_copy(update={"tenant_id": tenant_id}),
    )


def get_approvals(
    request: Request, schemas: SchemasDep, storage: StorageDep, tenant_id: TenantDep
) -> ApprovalService:
    """Decisions, with the tender layer's rule on when the summary may be decided."""
    settings: Settings = request.app.state.settings
    catalog: Catalog = request.app.state.catalog
    extract = ExtractService(
        request.app.state.llm,
        storage,
        schemas,
        settings.model_copy(update={"tenant_id": tenant_id}),
    )
    writer = summary_writer(request.app.state.llm, catalog, extract, schemas, tenant_id)
    guard = SummaryGuard(writer, TenderService(catalog, extract, tenant_id))
    return ApprovalService(schemas, tenant_id, settings.evidence_match_threshold, guards=[guard])


def get_review_state(schemas: SchemasDep, tenant_id: TenantDep) -> ReviewStateService:
    return ReviewStateService(schemas, tenant_id)


IngestDep = Annotated[IngestService, Depends(get_ingest)]
ExtractDep = Annotated[ExtractService, Depends(get_extract)]
ApprovalsDep = Annotated[ApprovalService, Depends(get_approvals)]
ReviewStateDep = Annotated[ReviewStateService, Depends(get_review_state)]


def get_catalog(request: Request) -> Catalog:
    catalog: Catalog = request.app.state.catalog
    return catalog


CatalogDep = Annotated[Catalog, Depends(get_catalog)]


def get_tenders(catalog: CatalogDep, extract: ExtractDep, tenant_id: TenantDep) -> TenderService:
    return TenderService(catalog, extract, tenant_id)


TendersDep = Annotated[TenderService, Depends(get_tenders)]


def get_summary_writer(
    request: Request,
    catalog: CatalogDep,
    extract: ExtractDep,
    schemas: SchemasDep,
    tenant_id: TenantDep,
) -> SummaryWriter:
    """Only to queue the summary: the API never calls the model."""
    return summary_writer(request.app.state.llm, catalog, extract, schemas, tenant_id)


SummaryWriterDep = Annotated[SummaryWriter, Depends(get_summary_writer)]


def get_tokens(tenant_id: TenantDep) -> TokenService:
    return TokenService(tenant_id)


TokensDep = Annotated[TokenService, Depends(get_tokens)]
