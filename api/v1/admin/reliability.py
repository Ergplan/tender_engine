"""The reliability dashboard's data: gold records scored against the candidates in review.

Guarded by the admin token in api/middleware/review_token.py; no login in phase 1.
"""

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import CatalogDep, ReviewStateDep, SessionDep, TenantDep
from evals.gold import load_all
from evals.report import Stability, TenderLine, prompt_comparison, stability, tender_lines, timing
from evals.runner import FieldScore, Summary, candidates_in_review, score_record, summarise
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


@router.get("/reliability", response_model=ReliabilityOut)
def get_reliability(
    session: SessionDep, review_state: ReviewStateDep, catalog: CatalogDep, tenant_id: TenantDep
) -> ReliabilityOut:
    """Accuracy per tender type and field, the reviewed tenders, and the stability bar."""
    records = load_all()
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
