"""What the tender layer hands to the worker: its job kinds and its step after validation."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from core.llm.client import LLMClient
from core.schemas import SchemaRegistry
from core.services.extract import ExtractService
from core.services.review_state import ReviewStateService
from tender.services import amendment_map, derive, summary
from tender.services.packs import Catalog
from tender.services.tenders import TenderService

Handler = Callable[[Session, dict[str, Any]], None]


def tender_jobs(
    llm: LLMClient,
    catalog: Catalog,
    extract: ExtractService,
    schemas: SchemaRegistry,
    tenant_id: str,
) -> tuple[dict[str, Handler], Callable[[Session, str], None]]:
    """The handlers for `amendment_plan`, `tender_summary` and `tender_derive`, and the
    function the worker calls after it has validated a run (it queues the summary and the
    derivation once a tender's runs are all in)."""
    mapper = amendment_map.AmendmentMapper(llm, catalog, extract, tenant_id)
    writer = summary_writer(llm, catalog, extract, schemas, tenant_id)
    deriver = derived_writer(catalog, extract, schemas, tenant_id)
    handlers = {
        **amendment_map.job_handlers(mapper),
        **summary.job_handlers(writer),
        **derive.job_handlers(deriver),
    }

    def after_validation(session: Session, extraction_run_id: str) -> None:
        writer.after_validation(session, extraction_run_id)
        deriver.after_validation(session, extraction_run_id)

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
