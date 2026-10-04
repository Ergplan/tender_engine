"""Engine and session factories. Built once per process by the app or worker and passed down."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings


def make_engine(settings: Settings) -> Engine:
    """Create the engine. When db_schema is set, every connection uses it as search_path."""
    connect_args: dict[str, str] = {}
    if settings.db_schema:
        connect_args["options"] = f"-csearch_path={settings.db_schema}"
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
