"""Test harness: a throwaway schema per session, migrated from empty with Alembic.

Pattern adapted from tariff-oder tests/conftest.py (migrate a clean database per session),
changed to a per-session schema so the watcher and a manual run never collide.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.db import make_engine, make_session_factory
from core.models import LLMCallLog

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://tender:tender@db:5432/tender_ci"
)


@pytest.fixture(scope="session")
def settings() -> Iterator[Settings]:
    schema = f"test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_settings = Settings(
        _env_file=None,
        database_url=TEST_DATABASE_URL,
        db_schema=schema,
        tenant_id="ergplan",
        anthropic_api_key="test-key-not-real",
        anthropic_model="claude-fable-5-1",
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
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture()
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session for assertions; rows written by the test are removed afterwards."""
    with session_factory() as session:
        yield session
    with session_factory() as cleanup:
        cleanup.execute(delete(LLMCallLog))
        cleanup.commit()
