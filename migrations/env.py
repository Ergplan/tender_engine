"""Alembic environment. The database comes from Settings; tests pass their own in attributes."""

from logging.config import fileConfig

from alembic import context

import tender.models  # noqa: F401  (registers the tender tables on Base.metadata)
from core.config import Settings
from core.db import make_engine
from core.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings: Settings = config.attributes.get("settings") or Settings()
engine = make_engine(settings)

with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
