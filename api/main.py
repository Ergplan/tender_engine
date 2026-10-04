"""FastAPI application factory. Routes only; business logic lives in core/ and tender/."""

from fastapi import FastAPI

from api.middleware import errors
from api.v1.core import health
from core.config import Settings
from core.db import make_engine, make_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Tender Intelligence Engine", version="0.1.0")
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    errors.install(app)
    # /health at the root is what Caddy and make deploy probe; the versioned copy is the API.
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api/v1")
    return app
