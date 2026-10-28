"""What the tender layer hands to the worker: its job kinds and its step after validation."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
from sqlalchemy.orm import Session

from core.config import Settings
from core.llm.client import LLMClient
from core.models import ExtractionRun
from core.schemas import SchemaRegistry
from core.services import webhooks
from core.services.extract import ExtractService
from core.services.review_state import ReviewStateService
from tender.models import Tender
from tender.services import (
    amendment_map,
    classify,
    derive,
    freshness,
    rounds,
    submit,
    summary,
)
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
    webhook_transport: httpx2.BaseTransport | None = None,
) -> tuple[dict[str, Handler], Callable[[Session, str], None]]:
    """The handlers for `classify_type`, `amendment_plan`, `tender_summary`, `tender_derive`,
    `source_freshness`, `tender_extract` (Block 6: a submitted version read once parsed) and
    `webhook_deliver`, and the function the worker calls after it has validated a run (it
    queues the summary and the derivation once a tender's runs are all in, and then emits
    `extraction_done`). The freshness check reads the manifests under `tenders_root` and
    queues itself again every `freshness_interval_days` (0: only when asked)."""
    mapper = amendment_map.AmendmentMapper(llm, catalog, extract, tenant_id)
    writer = summary_writer(llm, catalog, extract, schemas, tenant_id)
    deriver = derived_writer(catalog, extract, schemas, tenant_id)
    checker = freshness.FreshnessChecker(
        tenant_id,
        tenders_root=tenders_root or Path(Settings().tenders_root),
        transport=freshness_transport,
    )
    tenders = TenderService(catalog, extract, tenant_id)
    handlers = {
        **classify.job_handlers(classify.TypeClassifier(llm, tenant_id)),
        **amendment_map.job_handlers(mapper),
        **summary.job_handlers(writer),
        **derive.job_handlers(deriver),
        **freshness.job_handlers(checker, tenant_id, freshness_interval_days),
        **submit.job_handlers(tenders, tenant_id),
        **webhooks.job_handlers(webhooks.Deliverer(tenant_id, webhook_transport)),
    }

    opener = rounds.RoundOpener(tenders, TokenService(tenant_id), tenant_id)

    def after_validation(session: Session, extraction_run_id: str) -> None:
        settled = writer.after_validation(session, extraction_run_id)
        deriver.after_validation(session, extraction_run_id)
        opener.after_validation(session, extraction_run_id)
        if settled:
            run = session.get(ExtractionRun, extraction_run_id)
            tender = session.get(Tender, run.object_id) if run else None
            if tender is not None:
                webhooks.emit(
                    session,
                    tenant_id=tenant_id,
                    event="extraction_done",
                    payload={
                        "tender_id": tender.id,
                        "slug": tender.slug,
                        "version_no": run.object_version if run else None,
                    },
                )
                session.commit()

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
