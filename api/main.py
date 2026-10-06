"""FastAPI application factory. Routes only; business logic lives in core/ and tender/."""

import logging

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from api.middleware import audit, errors, review_token
from api.v1.admin import reliability
from api.v1.core import documents, extraction, health, review
from api.v1.tenders import review as tender_review
from api.v1.tenders import tenders
from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.schemas import SchemaRegistry
from core.storage import Storage, make_storage
from tender.services.field_defs import sync_field_defs
from tender.services.packs import Catalog, load_catalog

log = logging.getLogger("api")
V1_ROUTERS = (
    health.router,
    documents.router,
    extraction.router,
    review.router,
    tenders.router,
    tender_review.router,
    reliability.router,
)


def create_app(
    settings: Settings | None = None,
    schemas: SchemaRegistry | None = None,
    storage: Storage | None = None,
    llm: LLMClient | None = None,
    catalog: Catalog | None = None,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Tender Intelligence Engine", version="0.3.0")
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.storage = storage or make_storage(settings)
    # The tender types of the domain packs are registered with core at start-up.
    app.state.catalog = catalog or load_catalog()
    app.state.schemas = schemas or SchemaRegistry()
    app.state.catalog.register(app.state.schemas)
    # The API never calls the model; it needs the client only to check that a prompt
    # version is registered before queueing a run.
    app.state.llm = llm or LLMClient(
        settings, app.state.session_factory, prompt_roots=app.state.catalog.prompt_roots
    )
    try:
        with app.state.session_factory() as session:
            sync_field_defs(session, app.state.catalog, settings.tenant_id)
    except SQLAlchemyError:
        # The table is for introspection only; the schemas are served from the catalog.
        log.exception("tender_field_def could not be refreshed")
    # The last one installed runs first: request id and error payloads around everything,
    # then the audit line of the request, then the review token.
    review_token.install(app)
    audit.install(app)
    errors.install(app)
    # /health at the root is what Caddy and make deploy probe; the versioned copy is the API.
    app.include_router(health.router)
    for router in V1_ROUTERS:
        app.include_router(router, prefix="/api/v1")
    return app
