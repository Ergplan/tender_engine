"""Fixtures for the MCP server: a public-library tender reviewed to completion, an own
tender, principals of a free tenant and of the enterprise tenant, and the server built
over a state like the API's."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.models import Tenant
from core.retrieval import ChunkIndexer, ChunkStores, Retriever, make_embedders
from core.services.approve import ApprovalService
from core.services.extract import ExtractService
from core.services.identity import IdentityService, Principal
from core.services.ingest import IngestService
from core.services.review_state import ReviewStateService
from core.storage import LocalStorage
from mcpserver.server import build_server
from mcpserver.tools import ToolContext
from tender.models import Tender
from tender.services.ask import AskService
from tender.services.packs import Catalog
from tender.services.retrieval_meta import chunk_meta
from tender.services.submit import Fetcher, SubmitService
from tender.services.tenders import TenderService
from tender.services.tokens import TokenService
from tender.services.worker_jobs import tender_jobs
from tests.conftest import Pipeline, add_tenant, owner_engine
from tests.fixtures.llm import ScriptedSDK
from tests.fixtures.schemas import make_registry
from tests.tender.test_rounds import reviewed_tender
from worker.runner import Runner


def pipeline_for(
    tenant_id: str, settings: Settings, catalog: Catalog, data_dir: str
) -> tuple[Pipeline, sessionmaker[Session]]:
    """A pipeline whose every service and session is scoped to `tenant_id`."""
    local = settings.model_copy(update={"tenant_id": tenant_id, "data_dir": data_dir})
    factory = make_session_factory(make_engine(local), tenant_id, read_tenants=("public",))
    storage = LocalStorage(local.data_dir)
    schemas = make_registry()
    catalog.register(schemas)
    sdk = ScriptedSDK()
    llm = LLMClient(local, factory, sdk=sdk.as_sdk(), prompt_roots=catalog.prompt_roots)
    extract = ExtractService(llm, storage, schemas, local)
    # Retrieval as the app's pipeline fixture builds it: keyword search alone, no network.
    local = local.model_copy(update={"embeddings_provider": "none"})
    embedders = make_embedders(local)
    store = ChunkStores(local).for_tenant(local.tenant_id)
    indexer = ChunkIndexer(store, embedders, local, meta_for=chunk_meta)
    tenders = TenderService(catalog, extract, tenant_id)
    pipeline = Pipeline(
        settings=local,
        session_factory=factory,
        storage=storage,
        schemas=schemas,
        sdk=sdk,
        llm=llm,
        runner=Runner(
            local,
            factory,
            storage,
            schemas,
            llm,
            *tender_jobs(llm, catalog, extract, schemas, tenant_id),
            indexer,
        ),
        ingest=IngestService(storage, tenant_id),
        extract=extract,
        approvals=ApprovalService(schemas, tenant_id),
        review_state=ReviewStateService(schemas, tenant_id),
        catalog=catalog,
        tenders=tenders,
        store=store,
        indexer=indexer,
        ask=AskService(llm, catalog, schemas, tenders, Retriever(store, embedders, top_k=6), local),
    )
    return pipeline, factory


@pytest.fixture()
def library(
    pipeline: Pipeline, settings: Settings, catalog: Catalog, db: Session
) -> Iterator[tuple[Pipeline, Session, str]]:
    """The public library with one tender reviewed to completion (the fixture RfS). The
    files live in the same store as the enterprise tenant's, as in the deployment."""
    public, factory = pipeline_for("public", settings, catalog, pipeline.settings.data_dir)
    with factory() as public_db:
        tender_id, _ = reviewed_tender(public, public_db)
        public_db.commit()
        yield public, public_db, tender_id


@pytest.fixture()
def own_tender(pipeline: Pipeline, db: Session) -> str:
    """A tender of the enterprise tenant (ergplan), reviewed to completion."""
    tender_id, _ = reviewed_tender(pipeline, db)
    return tender_id


@pytest.fixture()
def free_principal(settings: Settings, db: Session) -> Principal:
    """An API key of a free-plan tenant: reads the library only."""
    add_tenant(settings, "freeco", "Free Co")
    with owner_engine(settings).connect() as conn:
        from sqlalchemy import text

        conn.execute(text("UPDATE tenant SET plan = 'free' WHERE tenant_id = 'freeco'"))
        conn.commit()
    identity = IdentityService(settings)
    with make_session_factory(make_engine(settings), "freeco")() as theirs:
        key, raw = identity.create_api_key(
            theirs, "freeco", "free key", ["public:read"], created_by="freeco"
        )
        principal = identity.resolve_api_key(theirs, raw)
    assert principal is not None
    return principal


@pytest.fixture()
def enterprise_principal(settings: Settings, db: Session) -> Principal:
    identity = IdentityService(settings)
    key, raw = identity.create_api_key(
        db, "ergplan", "enterprise key", ["own:read", "public:read"], created_by="pytest"
    )
    principal = identity.resolve_api_key(db, raw)
    assert principal is not None
    return principal


@pytest.fixture()
def state(pipeline: Pipeline, settings: Settings, tmp_path: Any) -> SimpleNamespace:
    """What the API's app.state gives the server."""
    return SimpleNamespace(
        settings=pipeline.settings.model_copy(
            update={"results_root": str(tmp_path / "results"), "session_secret": "s" * 32}
        ),
        session_factory=pipeline.session_factory,
        identity=IdentityService(pipeline.settings),
        catalog=pipeline.catalog,
        llm=pipeline.llm,
        storage=pipeline.storage,
        schemas=pipeline.schemas,
        tenders=pipeline.tenders,
    )


def context_for(state: SimpleNamespace, session: Session, principal: Principal) -> ToolContext:
    tenant_id = principal.tenant_id
    return ToolContext(
        session=session,
        principal=principal,
        settings=state.settings,
        catalog=state.catalog,
        identity=state.identity,
        tenders=state.tenders,
        storage=state.storage,
        results_root=None,
        # Block 6 c: submissions fetch from `state.submit_transport` when a test sets one.
        submit=SubmitService(
            state.tenders,
            IngestService(state.storage, tenant_id),
            tenant_id,
            fetcher=Fetcher(transport=getattr(state, "submit_transport", None)),
        ),
        tokens=TokenService(tenant_id),
    )


def server_for(state: SimpleNamespace, principal: Principal | None = None) -> Any:
    return build_server(state, principal_for_tests=principal, with_auth=principal is None)


def tender_slug_or_id(session: Session, tender_id: str) -> str:
    row = session.scalar(select(Tender).where(Tender.id == tender_id))
    assert row is not None
    return row.slug or row.id


__all__ = ["Tenant"]
