"""Engine and session factories. Built once per process by the app or worker and passed down.

Since Stage 5C every table with a tenant_id is under row-level security (migration 0018):
a session sees and writes only the tenant it is scoped to, whatever the service layer
asks for. The scope is a Postgres setting (`app.tenant_id`, and `app.read_tenants` for
the tenants it may read besides its own, `public` from Stage 5D) set with SET LOCAL at the
start of every transaction from `session.info`. A session factory carries the process's
tenant; the API sets the request's principal's tenant on the request session before its
first statement (`set_tenant`). `SYSTEM_TENANT` ("*") is the scope of the few steps that
must look across tenants before a tenant is known (resolving a login, a review link or an
API key); nothing else uses it.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings

SYSTEM_TENANT = "*"
TENANT_KEY = "tenant_id"
READ_TENANTS_KEY = "read_tenants"


def make_engine(settings: Settings) -> Engine:
    """Create the engine. When db_schema is set, every connection uses it as search_path."""
    connect_args: dict[str, str] = {}
    if settings.db_schema:
        connect_args["options"] = f"-csearch_path={settings.db_schema}"
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


def make_session_factory(
    engine: Engine,
    tenant_id: str | None = None,
    *,
    read_tenants: Sequence[str] = (),
) -> sessionmaker[Session]:
    """Sessions scoped to `tenant_id` (and reading `read_tenants` besides). A factory made
    without a tenant gives sessions that see no tenant-scoped row until `set_tenant`."""
    info: dict[str, Any] = {TENANT_KEY: tenant_id, READ_TENANTS_KEY: tuple(read_tenants)}
    return sessionmaker(bind=engine, expire_on_commit=False, info=info)


def set_tenant(session: Session, tenant_id: str | None, read_tenants: Sequence[str] = ()) -> None:
    """Scope a session to a tenant: for the transactions to come, and for the one under
    way if there is one."""
    session.info[TENANT_KEY] = tenant_id
    session.info[READ_TENANTS_KEY] = tuple(read_tenants)
    if session.in_transaction():
        _apply(session.connection(), tenant_id, tuple(read_tenants))


def _apply(connection: Any, tenant_id: str | None, read_tenants: tuple[str, ...]) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"),
        {"tenant": tenant_id or ""},
    )
    connection.execute(
        text("SELECT set_config('app.read_tenants', :tenants, true)"),
        {"tenants": ",".join(read_tenants)},
    )


@event.listens_for(Session, "after_begin")
def _scope_transaction(session: Session, transaction: Any, connection: Any) -> None:
    """Every transaction starts by telling Postgres whose rows it may touch."""
    if TENANT_KEY not in session.info:
        return
    _apply(connection, session.info.get(TENANT_KEY), tuple(session.info.get(READ_TENANTS_KEY, ())))
