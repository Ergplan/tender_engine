"""FastAPI application factory. Routes only; business logic lives in core/ and tender/."""

from fastapi import FastAPI

from api.middleware import errors
from api.v1.core import documents, extraction, health, review
from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.schemas import SchemaRegistry
from core.storage import Storage, make_storage

V1_ROUTERS = (health.router, documents.router, extraction.router, review.router)


def create_app(
    settings: Settings | None = None,
    schemas: SchemaRegistry | None = None,
    storage: Storage | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Tender Intelligence Engine", version="0.1.0")
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.storage = storage or make_storage(settings)
    app.state.schemas = schemas or SchemaRegistry()
    # The API never calls the model; it needs the client only to check that a prompt
    # version is registered before queueing a run.
    app.state.llm = llm or LLMClient(settings, app.state.session_factory)
    errors.install(app)
    # /health at the root is what Caddy and make deploy probe; the versioned copy is the API.
    app.include_router(health.router)
    for router in V1_ROUTERS:
        app.include_router(router, prefix="/api/v1")
    return app
