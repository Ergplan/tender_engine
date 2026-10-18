"""Test harness: a throwaway schema per session, migrated from empty with Alembic.

Pattern adapted from tariff-oder tests/conftest.py (migrate a clean database per session),
changed to a per-session schema so the watcher and a manual run never collide.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.models import Base, Document, ExtractionRun
from core.schemas import SchemaRegistry
from core.services.approve import ApprovalService
from core.services.extract import ExtractService
from core.services.ingest import IngestService
from core.services.review_state import ReviewStateService
from core.storage import LocalStorage
from tender.services.packs import Catalog, load_catalog
from tender.services.tenders import TenderService
from tender.services.worker_jobs import tender_jobs
from tests.fixtures.llm import ScriptedSDK
from tests.fixtures.pdfs import make_pdf
from tests.fixtures.schemas import SCHEMA_NAME, SCHEMA_VERSION, make_registry
from worker.runner import Runner

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://tender:tender@db:5432/tender_ci"
)
# The app's own role (no ownership, bound by row-level security); the owner URL above runs
# the migrations and the clean-up.
TEST_APP_DATABASE_URL = os.environ.get(
    "TEST_APP_DATABASE_URL", "postgresql+psycopg://tender_app:tender_app@db:5432/tender_ci"
)


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Settings]:
    schema = f"test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_settings = Settings(
        _env_file=None,
        database_url=TEST_APP_DATABASE_URL,
        migration_database_url=TEST_DATABASE_URL,
        db_schema=schema,
        tenant_id="ergplan",
        data_dir=str(tmp_path_factory.mktemp("data")),
        anthropic_api_key="test-key-not-real",
        anthropic_model="claude-fable-5-1",
        # A batch run looks at its batch again at once; the scripted SDK ends it at once.
        llm_batch_poll_seconds=0,
    )
    config = Config("alembic.ini")
    config.attributes["settings"] = test_settings
    command.upgrade(config, "head")
    try:
        yield test_settings
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture(scope="session")
def session_factory(settings: Settings) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(settings)
    yield make_session_factory(engine, settings.tenant_id, read_tenants=("public",))
    engine.dispose()


@pytest.fixture()
def db(session_factory: sessionmaker[Session], settings: Settings) -> Iterator[Session]:
    """A session for the test. Every table except tenant is emptied afterwards.

    TRUNCATE is used because candidate, evidence_span and audit_log refuse DELETE.
    """
    with session_factory() as session:
        yield session
    # The clean-up is the owner's: TRUNCATE needs the table owner, and the app role is
    # bound by row-level security to one tenant.
    tables = ", ".join(f'"{name}"' for name in Base.metadata.tables if name != "tenant")
    with owner_engine(settings).connect() as cleanup:
        cleanup.execute(text(f"TRUNCATE {tables} CASCADE"))
        cleanup.execute(text("DELETE FROM tenant WHERE tenant_id NOT IN ('ergplan', 'public')"))
        cleanup.commit()


def owner_engine(settings: Settings) -> Engine:
    """The owner's connection to the test schema, for what the app role may not do."""
    return make_engine(settings.model_copy(update={"database_url": TEST_DATABASE_URL}))


def add_tenant(settings: Settings, tenant_id: str, name: str | None = None) -> None:
    """A second tenant for a test. The registry is written only in the system scope
    (sign-up, the operator), so a test adds one as the owner."""
    engine = owner_engine(settings)
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO tenant (tenant_id, name, created_by) VALUES (:id, :name, 'pytest') "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {"id": tenant_id, "name": name or tenant_id.title()},
        )
        conn.commit()
    engine.dispose()


@dataclass
class Pipeline:
    """Everything wired together the way the worker and API wire it, with a scripted model."""

    settings: Settings
    session_factory: sessionmaker[Session]
    storage: LocalStorage
    schemas: SchemaRegistry
    sdk: ScriptedSDK
    llm: LLMClient
    runner: Runner
    ingest: IngestService
    extract: ExtractService
    approvals: ApprovalService
    review_state: ReviewStateService
    catalog: Catalog
    tenders: TenderService

    def upload(
        self, db: Session, data: bytes | None = None, name: str = "contract.pdf"
    ) -> Document:
        document, _ = self.ingest.upload(
            db, filename=name, data=data if data is not None else make_pdf(), created_by="pytest"
        )
        return document

    def parsed_document(self, db: Session, data: bytes | None = None) -> Document:
        """Upload, parse and section-map a document."""
        document = self.upload(db, data)
        self.runner.run_until_idle()
        db.refresh(document)
        return document

    def start_run(self, db: Session, document: Document, **kwargs: Any) -> ExtractionRun:
        return self.extract.start_run(
            db,
            document_id=document.id,
            schema_name=SCHEMA_NAME,
            schema_version=SCHEMA_VERSION,
            prompt_version="v1",
            created_by="pytest",
            is_fixture=True,
            **kwargs,
        )

    def extracted_run(self, db: Session, data: bytes | None = None) -> ExtractionRun:
        """A document taken through the whole chain: parse, map, extract, validate."""
        run = self.start_run(db, self.parsed_document(db, data))
        self.runner.run_until_idle()
        db.refresh(run)
        return run


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    """The domain packs, compiled once for the whole test session."""
    return load_catalog()


@pytest.fixture()
def make_pipeline(
    settings: Settings,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    db: Session,
    catalog: Catalog,
) -> Callable[..., Pipeline]:
    def build(sdk: ScriptedSDK | None = None, **setting_overrides: Any) -> Pipeline:
        local = settings.model_copy(
            update={"data_dir": str(tmp_path / "data"), **setting_overrides}
        )
        storage = LocalStorage(local.data_dir)
        schemas = make_registry()
        catalog.register(schemas)
        sdk = sdk or ScriptedSDK()
        llm = LLMClient(local, session_factory, sdk=sdk.as_sdk(), prompt_roots=catalog.prompt_roots)
        extract = ExtractService(llm, storage, schemas, local)
        return Pipeline(
            settings=local,
            session_factory=session_factory,
            storage=storage,
            schemas=schemas,
            sdk=sdk,
            llm=llm,
            runner=Runner(
                local,
                session_factory,
                storage,
                schemas,
                llm,
                *tender_jobs(llm, catalog, extract, schemas, local.tenant_id),
            ),
            ingest=IngestService(storage, local.tenant_id),
            extract=extract,
            approvals=ApprovalService(schemas, local.tenant_id),
            review_state=ReviewStateService(schemas, local.tenant_id),
            catalog=catalog,
            tenders=TenderService(catalog, extract, local.tenant_id),
        )

    return build


@pytest.fixture()
def pipeline(make_pipeline: Callable[..., Pipeline]) -> Pipeline:
    return make_pipeline()
