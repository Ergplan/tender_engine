"""The three-way comparison (Stage 5B) as API operations, behind the admin token: run it
(THREEWAY-REPORT.md, the results file and the review emphasis file are written) and read
the latest result. `make threeway` is the shell equivalent."""

import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.deps import CatalogDep, ReviewStateDep, SessionDep, SettingsDep, TenantDep
from api.middleware.errors import AppError
from evals.runner import RESULTS_ROOT
from evals.threeway import ThreeWaySummary, write_threeway

router = APIRouter(prefix="/admin", tags=["admin"])


class ThreeWayRequest(BaseModel):
    only: list[str] = Field(default_factory=list, description="tender slugs; empty means all")


class ThreeWayOut(BaseModel):
    summary: ThreeWaySummary
    report: str
    results_file: str | None


def results_root(settings: SettingsDep) -> Path:
    return Path(settings.results_root) if settings.results_root else RESULTS_ROOT


@router.post("/threeway", response_model=ThreeWayOut, status_code=201)
def run_threeway(
    body: ThreeWayRequest,
    session: SessionDep,
    review_state: ReviewStateDep,
    catalog: CatalogDep,
    tenant_id: TenantDep,
    settings: SettingsDep,
) -> ThreeWayOut:
    """Compare reviewer, engine and agent on every gold field (the latest finished agent
    pass at the reviewed version); write THREEWAY-REPORT.md, a results file and the review
    emphasis file. A gold tender without an agent pass is listed and left out."""
    root = results_root(settings)
    summary, out = write_threeway(
        session,
        tenant_id,
        review_state.schemas,
        catalog,
        review_state,
        only=set(body.only) or None,
        results_root=root,
    )
    return ThreeWayOut(summary=summary, report=str(out), results_file=_latest(root, tenant_id))


@router.get("/threeway", response_model=ThreeWayOut)
def get_threeway(tenant_id: TenantDep, settings: SettingsDep) -> ThreeWayOut:
    """The latest comparison made for the tenant, from its results file."""
    root = results_root(settings)
    latest = _latest(root, tenant_id)
    if latest is None:
        raise AppError("not_found", "no three-way comparison has been made yet")
    data = json.loads(Path(latest).read_text(encoding="utf-8"))
    from evals.threeway import DEFAULT_OUT

    return ThreeWayOut(
        summary=ThreeWaySummary.model_validate(data["summary"]),
        report=str(DEFAULT_OUT),
        results_file=latest,
    )


def _latest(root: Path, tenant_id: str) -> str | None:
    files = sorted(root.glob(f"*-threeway-{tenant_id}.json")) if root.is_dir() else []
    return str(files[-1]) if files else None
