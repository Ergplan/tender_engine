"""Request dependencies: settings, db session, tenant, reviewer and tenant-scoped services."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from api.middleware.errors import AppError
from core.config import Settings
from core.schemas import SchemaRegistry
from core.services.approve import ApprovalService
from core.services.extract import ExtractService
from core.services.ingest import IngestService
from core.services.review_state import ReviewStateService
from core.storage import Storage
from tender.services.packs import Catalog
from tender.services.tenders import TenderService


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_tenant_id(settings: Annotated[Settings, Depends(get_settings)]) -> str:
    """Phase 1 resolves every request to the single configured tenant."""
    return settings.tenant_id


def get_reviewer(x_reviewer: Annotated[str | None, Header()] = None) -> str:
    """Phase 1 identity: the X-Reviewer header, set by the token middleware from Stage 3."""
    if x_reviewer is None or not x_reviewer.strip():
        raise AppError("validation_failed", "the X-Reviewer header is required")
    return x_reviewer.strip()


def get_actor(x_reviewer: Annotated[str | None, Header()] = None) -> str:
    return x_reviewer.strip() if x_reviewer and x_reviewer.strip() else "api"


SessionDep = Annotated[Session, Depends(get_session)]
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


def get_approvals(request: Request, schemas: SchemasDep, tenant_id: TenantDep) -> ApprovalService:
    settings: Settings = request.app.state.settings
    return ApprovalService(schemas, tenant_id, settings.evidence_match_threshold)


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
