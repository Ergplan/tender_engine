"""The reliability program's routes, behind the admin token (api/middleware/review_token.py):
the dashboard's data, a gold record from a completed review, an evaluation, the feedback
report. The management commands (make gold, eval, feedback-report, report) do the same work
from the shell.
"""

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.deps import CatalogDep, ReviewStateDep, SessionDep, TenantDep, TendersDep
from api.middleware.errors import AppError
from core.llm.registry import UnregisteredPromptError
from core.models import ExtractionRun
from core.services.extract import ExtractionError
from evals import feedback_report
from evals.gold import GoldRecord, NoCompletedReview, build_gold, load_all, write_gold
from evals.report import (
    Stability,
    TenderLine,
    prompt_comparison,
    stability,
    tender_lines,
    timing,
    write_reports,
)
from evals.runner import (
    FieldScore,
    Summary,
    candidates_in_review,
    candidates_of_runs,
    queue_prompt_runs,
    score_record,
    summarise,
    write_results,
)
from tender.models import Tender

router = APIRouter(prefix="/admin", tags=["admin"])


class ReliabilityOut(BaseModel):
    generated_at: datetime
    tenders_in_set: dict[str, int]
    gold_records: int
    tenders: list[TenderLine]
    summary: Summary
    stability: Stability
    prompt_comparison: list[dict[str, Any]]


class GoldRequest(BaseModel):
    tender_id: str


class GoldOut(BaseModel):
    tender_id: str
    slug: str
    tender_type: str
    reviewed_version: int
    decided: int
    total: int
    path: str


class EvalRequest(BaseModel):
    prompt: str | None = Field(default=None, description="section/vN: read that section again")
    only: list[str] = Field(default_factory=list, description="tender slugs; empty means all")
    run_ids: list[str] = Field(
        default_factory=list,
        description="score the readings of these runs (from an earlier prompt evaluation)",
    )


class EvalOut(BaseModel):
    status: str
    queued: dict[str, list[str]]
    results_file: str | None
    summary: Summary | None


class FeedbackOut(BaseModel):
    corrections: int
    fields: int
    rows: list[feedback_report.FeedbackRow]
    markdown: str


@router.get("/reliability", response_model=ReliabilityOut)
def get_reliability(
    session: SessionDep, review_state: ReviewStateDep, catalog: CatalogDep, tenant_id: TenantDep
) -> ReliabilityOut:
    """Accuracy per tender type and field, the reviewed tenders, and the stability bar."""
    records = load_all(tenant_id)
    set_types = Counter(
        session.scalars(select(Tender.tender_type).where(Tender.tenant_id == tenant_id))
    )
    scores: list[FieldScore] = []
    timings = {}
    for record in records:
        found = candidates_in_review(session, review_state, record)
        scores += score_record(record, found, catalog, review_state.schemas)
        sitting = timing(session, tenant_id, record)
        if sitting is not None:
            timings[record.slug] = sitting
    summary = summarise(scores)
    return ReliabilityOut(
        generated_at=datetime.now(UTC),
        tenders_in_set=dict(set_types),
        gold_records=len(records),
        tenders=tender_lines(records, scores, timings),
        summary=summary,
        stability=stability(records, summary, scores, set_types),
        prompt_comparison=prompt_comparison(),
    )


@router.post("/gold", response_model=GoldOut, status_code=201)
def make_gold(
    body: GoldRequest,
    session: SessionDep,
    catalog: CatalogDep,
    review_state: ReviewStateDep,
    tenant_id: TenantDep,
) -> GoldOut:
    """A completed review becomes a gold record (the caller confirms it is trustworthy by
    calling this); the reliability report and the review log are written again."""
    tender = session.scalar(
        select(Tender).where(Tender.id == body.tender_id, Tender.tenant_id == tenant_id)
    )
    if tender is None:
        raise AppError("not_found", "no such tender")
    try:
        record = build_gold(session, catalog, tender)
    except NoCompletedReview as exc:
        raise AppError("validation_failed", str(exc)) from exc
    path = write_gold(record)
    write_reports(session, tenant_id, review_state.schemas, catalog, review_state)
    return GoldOut(
        tender_id=tender.id,
        slug=record.slug,
        tender_type=record.tender_type,
        reviewed_version=record.reviewed_version,
        decided=sum(1 for f in record.fields if f.decision),
        total=len(record.fields),
        path=str(path),
    )


@router.post("/evals", response_model=EvalOut, status_code=201)
def run_eval(
    body: EvalRequest,
    session: SessionDep,
    review_state: ReviewStateDep,
    catalog: CatalogDep,
    tenders: TendersDep,
    tenant_id: TenantDep,
) -> EvalOut:
    """Without a prompt: score every gold record against the readings in review and write a
    results file. With a prompt (section/vN): queue a reading of that section on every gold
    tender with that version and return the run ids; score those readings, and nothing
    else, by sending the run ids back once the runs have finished."""
    records = [r for r in load_all(tenant_id) if not body.only or r.slug in body.only]
    if not records:
        raise AppError("validation_failed", "no gold record to score")
    if body.prompt:
        if "/" not in body.prompt:
            raise AppError("validation_failed", "prompt must be section/vN")
        section, version = body.prompt.split("/", 1)
        try:
            queued = queue_prompt_runs(session, tenders, records, section, version)
        except (ExtractionError, UnregisteredPromptError, LookupError) as exc:
            raise AppError("validation_failed", str(exc)) from exc
        session.commit()
        return EvalOut(status="queued", queued=queued, results_file=None, summary=None)
    scores: list[FieldScore] = []
    sections: set[str] | None = None
    label = "latest"
    if body.run_ids:
        sections = {
            c.prompt_name.rsplit("/", 1)[-1]
            for c in candidates_of_runs(session, tenant_id, body.run_ids).values()
            if c.prompt_name
        }
        label = "runs"
    for record in records:
        found = (
            candidates_of_runs(
                session, tenant_id, _runs_of(session, tenant_id, record, body.run_ids)
            )
            if body.run_ids
            else candidates_in_review(session, review_state, record)
        )
        scores += score_record(record, found, catalog, review_state.schemas, sections)
    path, summary = write_results(scores, label=label)
    return EvalOut(status="scored", queued={}, results_file=str(path), summary=summary)


def _runs_of(
    session: SessionDep, tenant_id: str, record: GoldRecord, run_ids: list[str]
) -> list[str]:
    return list(
        session.scalars(
            select(ExtractionRun.id).where(
                ExtractionRun.tenant_id == tenant_id,
                ExtractionRun.id.in_(run_ids),
                ExtractionRun.object_type == "tender",
                ExtractionRun.object_id == record.tender_id,
            )
        )
    )


@router.get("/feedback", response_model=FeedbackOut)
def get_feedback(session: SessionDep, tenant_id: TenantDep) -> FeedbackOut:
    """The corrections of standing decisions, grouped, with the rendered report."""
    rows = feedback_report.load_feedback(session, tenant_id)
    return FeedbackOut(
        corrections=len(rows),
        fields=len({r.field_path for r in rows}),
        rows=rows,
        markdown=feedback_report.render(rows),
    )
