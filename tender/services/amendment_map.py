"""Second opinion on which sections an amending document touches.

`versioning.plan_groups` decides by keywords. Keywords miss a change phrased unusually, and
a missed corrigendum is the most expensive error this system can make. So when keywords
select no section, or the document is longer than AMENDMENT_MAP_PAGE_THRESHOLD pages, the
amending document is mapped in full by the model against the tender's sections (one
text-only call), and the document is read for the union of both answers. Every amendment
where the two methods disagree is recorded in the audit log and logged.
"""

import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.llm.client import LLMClient, LLMRequest, TextPart
from core.models import AuditLog, Document, Page, Section
from core.services import audit
from core.services.extract import ExtractService
from tender.models import Tender, TenderVersion, TenderVersionDocument
from tender.services.packs import Catalog, CompiledType
from tender.services.tenders import JOB_KIND
from tender.services.versioning import plan_groups

log = logging.getLogger("tender.amendment_map")
PROMPT_NAME = "amendment_map"
ACTION = "amendment_routing"
ACTOR = "amendment_map"


class MappedChange(BaseModel):
    clause: str
    section: str
    summary: str
    page_no: int


class AmendmentMapOutput(BaseModel):
    changes: list[MappedChange]


class AmendmentMapper:
    def __init__(
        self, llm: LLMClient, catalog: Catalog, extract: ExtractService, tenant_id: str
    ) -> None:
        self._llm = llm
        self._catalog = catalog
        self._extract = extract
        self._tenant_id = tenant_id

    def map_changes(
        self,
        session: Session,
        compiled: CompiledType,
        document: Document,
        base: Document | None,
        prompt_version: str = "v1",
        is_fixture: bool = False,
    ) -> list[MappedChange]:
        """One model call over the whole amending document. Changes that name a section
        the schema does not have, or the summary section, are dropped."""
        pages = session.execute(
            select(Page.page_no, Page.text)
            .where(Page.document_id == document.id, Page.tenant_id == self._tenant_id)
            .order_by(Page.page_no)
        ).all()
        sections = "\n".join(
            f"- `{section.name}` ({section.label}): "
            + ", ".join(field.label for field in compiled.fields if field.section == section.name)
            for section in compiled.sections
            if section.name != "summary"
        )
        base_map = ""
        if base is not None:
            rows = session.execute(
                select(Section.start_page, Section.end_page, Section.heading, Section.kind)
                .where(Section.document_id == base.id, Section.tenant_id == self._tenant_id)
                .order_by(Section.start_page)
            ).all()
            base_map = "\n".join(
                f"- pages {start} to {end}: {heading} [{kind}]"
                for start, end, heading, kind in rows
            )
        text = "\n\n".join(f"=== page {page_no} ===\n{body}" for page_no, body in pages)
        prompt = (
            f"Schema sections of this tender ({compiled.schema.name}):\n{sections}\n\n"
            f"Section map of the base tender document:\n{base_map or '(none)'}\n\n"
            f"Amending document: {document.filename}, {len(pages)} page(s)\n\n{text}"
        )
        response = self._llm.call(
            LLMRequest[AmendmentMapOutput](
                prompt_name=PROMPT_NAME,
                prompt_version=prompt_version,
                content=[TextPart(text=prompt)],
                response_model=AmendmentMapOutput,
                created_by=ACTOR,
                is_fixture=is_fixture,
            )
        )
        known = {section.name for section in compiled.sections} - {"summary"}
        return [change for change in response.parsed.changes if change.section in known]

    def plan(
        self,
        session: Session,
        *,
        tender_id: str,
        version_no: int,
        document_id: str,
        prompt_version: str = "v1",
        created_by: str = ACTOR,
        start_runs: bool | str = True,
        is_fixture: bool = False,
    ) -> dict[str, Any]:
        """Compare the keyword answer with the full map for one amending document, record
        the comparison, and queue an extraction run: of the union of both (start_runs true
        or "union"), of the sections only the map found ("missing", for a document that
        was already read for its keyword sections), or none (false or "none"). Returns the
        recorded comparison."""
        tender = session.scalars(
            select(Tender).where(Tender.id == tender_id, Tender.tenant_id == self._tenant_id)
        ).one()
        compiled = self._catalog.get(tender.tender_type)
        version = session.scalars(
            select(TenderVersion).where(
                TenderVersion.tender_id == tender.id,
                TenderVersion.version_no == version_no,
                TenderVersion.tenant_id == self._tenant_id,
            )
        ).one()
        document, role = session.execute(
            select(Document, TenderVersionDocument.role)
            .join(TenderVersionDocument, TenderVersionDocument.document_id == Document.id)
            .where(
                TenderVersionDocument.tender_version_id == version.id,
                TenderVersionDocument.tenant_id == self._tenant_id,
                Document.id == document_id,
                Document.tenant_id == self._tenant_id,
            )
        ).one()
        base = session.scalar(
            select(Document)
            .join(TenderVersionDocument, TenderVersionDocument.document_id == Document.id)
            .join(TenderVersion, TenderVersion.id == TenderVersionDocument.tender_version_id)
            .where(
                TenderVersion.tender_id == tender.id,
                TenderVersion.version_no == 1,
                TenderVersion.tenant_id == self._tenant_id,
                Document.tenant_id == self._tenant_id,
            )
            .order_by(TenderVersionDocument.created_at, TenderVersionDocument.id)
            .limit(1)
        )
        page_texts = list(
            session.scalars(
                select(Page.text)
                .where(Page.document_id == document.id, Page.tenant_id == self._tenant_id)
                .order_by(Page.page_no)
            )
        )
        by_keywords = plan_groups(compiled, version_no=version_no, role=role, page_texts=page_texts)
        changes = self.map_changes(
            session, compiled, document, base, prompt_version, is_fixture=is_fixture
        )
        order = [section.name for section in compiled.sections]
        by_map = sorted({change.section for change in changes}, key=order.index)
        union = sorted(set(by_keywords) | set(by_map), key=order.index)
        mode = {True: "union", False: "none"}.get(start_runs, start_runs)  # type: ignore[arg-type]
        to_read = {"union": union, "missing": [g for g in by_map if g not in by_keywords]}.get(
            str(mode), []
        )
        comparison = {
            "document_id": document.id,
            "filename": document.filename,
            "pages": document.page_count,
            "by_keywords": by_keywords,
            "by_map": by_map,
            "only_keywords": [name for name in by_keywords if name not in by_map],
            "only_map": [name for name in by_map if name not in by_keywords],
            "agree": set(by_keywords) == set(by_map),
            "changes": [change.model_dump() for change in changes],
            "extracted": to_read or None,
        }
        audit.record(
            session,
            tenant_id=self._tenant_id,
            actor=created_by,
            action=ACTION,
            table_name="tender_version",
            row_id=version.id,
            after=comparison,
        )
        session.commit()
        if not comparison["agree"]:
            log.warning(
                "amendment routing disagrees for %s v%s %s: keywords only %s, map only %s",
                tender.slug or tender.id,
                version_no,
                document.filename,
                comparison["only_keywords"],
                comparison["only_map"],
            )
        if to_read:
            self._extract.start_run(
                session,
                document_id=document.id,
                schema_name=compiled.schema.name,
                schema_version=compiled.schema.version,
                prompt_version=prompt_version,
                created_by=created_by,
                object_type="tender",
                object_id=tender.id,
                object_version=version_no,
                groups=to_read,
                is_fixture=is_fixture,
            )
        return comparison


def job_handlers(mapper: AmendmentMapper) -> dict[str, Callable[[Session, dict[str, Any]], None]]:
    """The job kinds the worker runs for the tender layer."""

    def amendment_plan(session: Session, payload: dict[str, Any]) -> None:
        mapper.plan(
            session,
            tender_id=payload["tender_id"],
            version_no=payload["version_no"],
            document_id=payload["document_id"],
            prompt_version=payload.get("prompt_version", "v1"),
            created_by=payload.get("created_by", ACTOR),
            start_runs=payload.get("start_runs", True),
            is_fixture=payload.get("is_fixture", False),
        )

    return {JOB_KIND: amendment_plan}


def routing_records(session: Session, tenant_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Every recorded comparison, oldest first, as (tender_version id, comparison)."""
    rows = session.scalars(
        select(AuditLog)
        .where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.table_name == "tender_version",
            AuditLog.action == ACTION,
        )
        .order_by(AuditLog.at, AuditLog.id)
    )
    return [(row.row_id, dict(row.after or {})) for row in rows]
