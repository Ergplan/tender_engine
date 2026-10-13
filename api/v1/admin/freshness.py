"""The corpus freshness check, behind the admin token: the last comparison of every
tender's source page with the documents held, and a check on demand (queued for the
worker; nothing is ingested by it). The management command `ingest_tenders freshness` does
the same from the shell and writes `docs/reports/FRESHNESS-REPORT.md`.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import ActorDep, SessionDep, SettingsDep, TenantDep
from core.services import jobs
from tender.services.freshness import JOB_KIND, SourceCheck, latest

router = APIRouter(prefix="/admin", tags=["admin"])


class FreshnessOut(BaseModel):
    generated_at: datetime
    interval_days: float
    checks: list[SourceCheck]
    stale: int


class FreshnessQueued(BaseModel):
    job_id: str


@router.get("/freshness", response_model=FreshnessOut)
def get_freshness(session: SessionDep, tenant: TenantDep, settings: SettingsDep) -> FreshnessOut:
    checks = latest(session, tenant)
    return FreshnessOut(
        generated_at=datetime.now(UTC),
        interval_days=settings.freshness_interval_days,
        checks=checks,
        stale=sum(1 for check in checks if check.stale),
    )


@router.post("/freshness", response_model=FreshnessQueued, status_code=202)
def run_freshness(session: SessionDep, tenant: TenantDep, actor: ActorDep) -> FreshnessQueued:
    """Queue one check of every tender now. It does not move the weekly schedule."""
    job = jobs.enqueue(
        session,
        tenant_id=tenant,
        kind=JOB_KIND,
        payload={"repeat": False, "created_by": actor},
        created_by=actor,
    )
    session.commit()
    return FreshnessQueued(job_id=job.id)
