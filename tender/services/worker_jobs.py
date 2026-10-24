"""What the tender layer hands to the worker: its job kinds and its step after validation."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
from sqlalchemy.orm import Session

from core.config import Settings
from core.llm.client import LLMClient
from core.schemas import SchemaRegistry
from core.services.extract import ExtractService
from core.services.review_state import ReviewStateService
from tender.services import amendment_map, classify, derive, freshness, rounds, summary
from tender.services.packs import Catalog
from tender.services.tenders import TenderService
from tender.services.tokens import TokenService

Handler = Callable[[Session, dict[str, Any]], None]


def tender_jobs(
    llm: LLMClient,
    catalog: Catalog,
    extract: ExtractService,
    schemas: SchemaRegistry,
    tenant_id: str,
    *,
    tenders_root: Path | None = None,
    freshness_interval_days: float = 0,
    freshness_transport: httpx2.BaseTransport | None = None,
) -> tuple[dict[str, Handler], Callable[[Session, str], None]]:
    """The handlers for `classify_type`, `amendment_plan`, `tender_summary`, `tender_derive`
    and `source_freshness`, and the function the worker calls after it has validated a run (it
    queues the summary and the derivation once a tender's runs are all in). The freshness
    check reads the manifests under `tenders_root` and queues itself again every
    `freshness_interval_days` (0: only when asked)."""
    mapper = amendment_map.AmendmentMapper(llm, catalog, extract, tenant_id)
    writer = summary_writer(llm, catalog, extract, schemas, tenant_id)
    deriver = derived_writer(catalog, extract, schemas, tenant_id)
    checker = freshness.FreshnessChecker(
        tenant_id,
        tenders_root=tenders_root or Path(Settings().tenders_root),
        transport=freshness_transport,
    )
    handlers = {
        **classify.job_handlers(classify.TypeClassifier(llm, tenant_id)),
        **amendment_map.job_handlers(mapper),
        **summary.job_handlers(writer),
        **derive.job_handlers(deriver),
        **freshness.job_handlers(checker, tenant_id, freshness_interval_days),
    }

    opener = rounds.RoundOpener(
        TenderService(catalog, extract, tenant_id), TokenService(tenant_id), tenant_id
    )

    def after_validation(session: Session, extraction_run_id: str) -> None:
        writer.after_validation(session, extraction_run_id)
        deriver.after_validation(session, extraction_run_id)
        opener.after_validation(session, extraction_run_id)

    return handlers, after_validation


def summary_writer(
    llm: LLMClient,
    catalog: Catalog,
    extract: ExtractService,
    schemas: SchemaRegistry,
    tenant_id: str,
) -> summary.SummaryWriter:
    return summary.SummaryWriter(
        llm,
        catalog,
        extract,
        TenderService(catalog, extract, tenant_id),
        ReviewStateService(schemas, tenant_id),
        schemas,
        tenant_id,
    )


def derived_writer(
    catalog: Catalog, extract: ExtractService, schemas: SchemaRegistry, tenant_id: str
) -> derive.DerivedWriter:
    return derive.DerivedWriter(
        catalog,
        extract,
        TenderService(catalog, extract, tenant_id),
        ReviewStateService(schemas, tenant_id),
        tenant_id,
    )
