"""FastAPI application factory. Routes only; business logic lives in core/ and tender/."""

import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, FastAPI
from sqlalchemy.exc import SQLAlchemyError

from api.middleware import audit, auth, errors
from api.v1.admin import freshness, identity, reliability, threeway
from api.v1.admin import library as admin_library
from api.v1.awards import awards
from api.v1.core import auth as auth_routes
from api.v1.core import documents, extraction, files, health, oauth, review
from api.v1.tenders import agent_pass, ask, contract, library, published, tenders
from api.v1.tenders import review as tender_review
from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.retrieval import ChunkStores, make_embedders
from core.schemas import SchemaRegistry
from core.services.identity import IdentityService
from core.services.oidc import GoogleOidc, OidcProvider
from core.storage import Storage, make_storage
from mcpserver.server import build_server, routes_of, run_session_manager
from tender.services.field_defs import sync_field_defs
from tender.services.packs import Catalog, load_catalog

log = logging.getLogger("api")
V1_ROUTERS = (
    health.router,
    documents.router,
    extraction.router,
    review.router,
    # Before the tenders router: `/tenders/compare`, `/tenders/search` and `/tenders/match`
    # must not be read as a tender id.
    published.router,
    library.router,
    ask.router,
    contract.router,
    tenders.router,
    tender_review.router,
    agent_pass.router,
    awards.router,
    reliability.router,
    freshness.router,
    threeway.router,
    auth_routes.router,
    oauth.router,
    identity.router,
    admin_library.router,
)
# Product B, the intelligence API (settings.product == "api"): the read side only — the
# tenders and their documents, the reliability figures, health. The same code as the
# enterprise product; writes (approvals, review links, gold, extraction) are not mounted.
# The published view, the changelog and the comparison (api/v1/tenders/published.py) are
# the product's own routes; they go before the tenders router for the same reason as above.
API_PRODUCT_ROUTERS = (
    health.router,
    documents.router,
    published.router,
    library.router,
    ask.router,
    contract.router,
    tenders.router,
    awards.router,
    reliability.router,
)
API_PRODUCT_READ_ONLY = ("documents", "tenders", "reliability", "published", "library", "awards")


def routers_for(product: str) -> tuple[APIRouter, ...]:
    """The routers a process mounts under /api/v1 for its product."""
    if product == "api":
        return API_PRODUCT_ROUTERS
    return V1_ROUTERS


def create_app(
    settings: Settings | None = None,
    schemas: SchemaRegistry | None = None,
    storage: Storage | None = None,
    llm: LLMClient | None = None,
    catalog: Catalog | None = None,
    oidc: OidcProvider | None = None,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Tender Intelligence Engine", version="0.3.0")
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine, settings.tenant_id)
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
    # Retrieval (Stage 7, Block 5): one chunk store per tenant served, the embedders of
    # the configured provider; `ask` is the one route that calls the model in a request.
    app.state.retrieval = ChunkStores(settings)
    app.state.embedders = make_embedders(settings)
    try:
        with app.state.session_factory() as session:
            sync_field_defs(session, app.state.catalog, settings.tenant_id)
    except SQLAlchemyError:
        # The table is for introspection only; the schemas are served from the catalog.
        log.exception("tender_field_def could not be refreshed")
    # Who a request is: sessions, keys, review links (Stage 5C); the sign-in provider.
    app.state.identity = IdentityService(settings)
    app.state.oidc = oidc or GoogleOidc(settings)
    # The last one installed runs first: request id and error payloads around everything,
    # then the audit line of the request, then the identity and its policy.
    auth.install(app)
    audit.install(app)
    errors.install(app)
    # /health at the root is what Caddy and make deploy probe; the versioned copy is the API.
    app.include_router(health.router)
    # Stored files at the root, for a deployment without a proxy serving /data (Cloud Run).
    app.include_router(files.router)
    for router in routers_for(settings.product):
        if settings.product == "api" and _has_writes(router):
            router = _reads_only(router)
        app.include_router(router, prefix="/api/v1")
    # The MCP server of the public library (Stage 5D): `/mcp` and the OAuth routes
    # (`/authorize`, `/token`, `/register`, `/.well-known/...`) at the root, behind the
    # API's own routes; its session manager runs for the life of the process.
    app.state.mcp = build_server(app.state)
    app.router.lifespan_context = _lifespan
    app.router.routes.extend(routes_of(app.state.mcp))
    return app


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with run_session_manager(app.state.mcp):
        yield


def _has_writes(router: APIRouter) -> bool:
    return any("GET" not in (route.methods or set()) for route in router.routes)  # type: ignore[attr-defined]


def _reads_only(router: APIRouter) -> APIRouter:
    """The GET routes of a router, for the intelligence product."""
    reads = APIRouter(tags=router.tags)
    reads.routes.extend(
        route
        for route in router.routes
        if "GET" in (route.methods or set())  # type: ignore[attr-defined]
    )
    return reads
