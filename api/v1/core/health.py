from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from api.deps import SessionDep, TenantDep
from api.middleware.errors import AppError
from api.v1.schemas.health import HealthResponse
from core.models import Tenant

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(session: SessionDep, tenant_id: TenantDep) -> HealthResponse:
    """Healthy means the database answers and the configured tenant row exists."""
    try:
        found = session.scalar(select(Tenant.tenant_id).where(Tenant.tenant_id == tenant_id))
    except SQLAlchemyError as exc:
        raise AppError("dependency_unavailable", "database is not reachable") from exc
    if found is None:
        raise AppError("dependency_unavailable", f"tenant {tenant_id!r} is not seeded")
    return HealthResponse(status="ok", tenant_id=found, database="ok")
