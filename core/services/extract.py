"""ExtractService: field groups -> page windows -> model call -> candidates with evidence.

Model output stops here, in the candidate table. Candidates are inserted once and never
updated (a database trigger allows only their status to change).
"""

import base64
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pymupdf
from pydantic import BaseModel, create_model
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.llm.client import LLMClient, LLMRequest, PdfPart, TextPart
from core.models import (
    Candidate,
    Document,
    EvidenceSpan,
    ExtractionRun,
    LLMCallLog,
    Page,
    Section,
)
from core.schemas import ExtractionSchema, FieldDef, FieldGroup, RoutingHints, SchemaRegistry
from core.schemas.types import JsonKind
from core.services import audit, jobs
from core.services.evidence import Located, PageText, locate
from core.services.section_map import normalise_kind
from core.storage import Storage

ACTOR = "extraction"
UNLOCATED_CONFIDENCE_CAP = 0.3
MAX_PDF_BYTES = 20 * 1024 * 1024
LIVE_STATUSES = ("raw", "validated", "needs_review", "not_found")
_PY_TYPES: dict[JsonKind, Any] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "string_list": list[str],
}


class EvidenceQuote(BaseModel):
    page_no: int
    quote: str


class ExtractionError(ValueError):
    """The run cannot be started: unparsed document, unknown schema or prompt."""


@dataclass
class _Draft:
    value: Any
    confidence: float
    rationale: str
    quotes: list[EvidenceQuote]
    chunk: list[int]
    call_log_id: str


def build_group_model(
    schema: ExtractionSchema, group: FieldGroup, schemas: SchemaRegistry
) -> type[BaseModel]:
    """The structured-output model for one group: every field REQUIRES value, confidence,
    rationale and evidence."""
    make = cast(Any, create_model)
    field_models: dict[JsonKind, type[BaseModel]] = {}
    properties: dict[str, Any] = {}
    for field in schema.fields_in(group.name):
        kind = schemas.value_types.get(field.value_type).json_kind
        if kind not in field_models:
            field_models[kind] = make(
                f"Extracted_{kind}",
                value=(_PY_TYPES[kind] | None, ...),
                confidence=(float, ...),
                rationale=(str, ...),
                evidence=(list[EvidenceQuote], ...),
            )
        properties[field.key] = (field_models[kind], ...)
    return cast(type[BaseModel], make(f"Extract_{group.name}", **properties))


def select_pages(
    routing: RoutingHints,
    sections: list[tuple[int, int, str, str]],
    page_texts: dict[int, str],
    *,
    max_pages: int,
    fallback_pages: int,
) -> list[int]:
    """Pages for a group: sections whose kind or heading the hints name; if none match,
    the pages that mention the keywords most; if still none, the opening pages.
    sections are (start_page, end_page, heading, kind)."""
    kinds = {normalise_kind(kind) for kind in routing.section_kinds}
    keywords = [keyword.lower() for keyword in routing.keywords if keyword.strip()]
    hits = {
        page_no: sum(text.lower().count(keyword) for keyword in keywords)
        for page_no, text in page_texts.items()
    }
    pages: set[int] = set()
    for start, end, heading, kind in sections:
        if kind in kinds or any(keyword in heading.lower() for keyword in keywords):
            pages.update(p for p in range(start, end + 1) if p in page_texts)
    if not pages:
        pages = {page_no for page_no, count in hits.items() if count > 0}
    if not pages:
        pages = set(sorted(page_texts)[:fallback_pages])
    if len(pages) > max_pages:
        ranked = sorted(pages, key=lambda page_no: (-hits.get(page_no, 0), page_no))
        pages = set(ranked[:max_pages])
    return sorted(pages)


def chunked(pages: list[int], size: int) -> Iterator[list[int]]:
    for start in range(0, len(pages), size):
        yield pages[start : start + size]


class ExtractService:
    def __init__(
        self, llm: LLMClient, storage: Storage, schemas: SchemaRegistry, settings: Settings
    ) -> None:
        self._llm = llm
        self._storage = storage
        self._schemas = schemas
        self._settings = settings

    def start_run(
        self,
        session: Session,
        *,
        document_id: str,
        schema_name: str,
        schema_version: str,
        prompt_version: str,
        created_by: str,
        object_type: str = "document",
        object_id: str | None = None,
        object_version: int = 1,
        is_fixture: bool = False,
    ) -> ExtractionRun:
        """Create the run and enqueue it. Refuses unknown schemas and unregistered prompts."""
        tenant_id = self._settings.tenant_id
        document = session.scalar(
            select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
        )
        if document is None:
            raise LookupError(f"document {document_id} not found")
        if document.status != "parsed":
            raise ExtractionError(f"document is {document.status}, not parsed")
        has_sections = session.scalar(
            select(func.count())
            .select_from(Section)
            .where(Section.document_id == document.id, Section.tenant_id == tenant_id)
        )
        if not has_sections:
            raise ExtractionError("document has no section map yet")
        schema = self._schemas.get(schema_name, schema_version)
        for group in schema.groups:
            self._llm.prompt(group.prompt_name, prompt_version)
        run = ExtractionRun(
            tenant_id=tenant_id,
            created_by=created_by,
            document_id=document.id,
            object_type=object_type,
            object_id=object_id or document.id,
            object_version=object_version,
            schema_name=schema.name,
            schema_version=schema.version,
            prompt_version=prompt_version,
            model=self._llm.model,
            status="queued",
            is_fixture=is_fixture,
        )
        session.add(run)
        session.flush()
        jobs.enqueue(
            session,
            tenant_id=tenant_id,
            kind="extract",
            payload={"extraction_run_id": run.id},
            created_by=created_by,
        )
        session.commit()
        return run

    def extract(self, session: Session, extraction_run_id: str) -> ExtractionRun:
        """Run every field group. Commits per group, so a retry resumes where it stopped."""
        tenant_id = self._settings.tenant_id
        run = session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.id == extraction_run_id, ExtractionRun.tenant_id == tenant_id
            )
        )
        if run is None:
            raise LookupError(f"extraction run {extraction_run_id} not found")
        if run.status in ("extracted", "validated"):
            return run
        run.status = "running"
        run.error = None
        run.started_at = run.started_at or datetime.now(UTC)
        session.commit()

        document = session.scalars(
            select(Document).where(Document.id == run.document_id, Document.tenant_id == tenant_id)
        ).one()
        schema = self._schemas.get(run.schema_name, run.schema_version)
        page_texts = {
            page_no: text
            for page_no, text in session.execute(
                select(Page.page_no, Page.text).where(
                    Page.document_id == document.id, Page.tenant_id == tenant_id
                )
            )
        }
        sections = [
            (start, end, heading, kind)
            for start, end, heading, kind in session.execute(
                select(Section.start_page, Section.end_page, Section.heading, Section.kind)
                .where(Section.document_id == document.id, Section.tenant_id == tenant_id)
                .order_by(Section.start_page)
            )
        ]
        pdf = self._storage.get(document.storage_path)
        pages = _PageCache(session, document.id, tenant_id)

        for group in schema.groups:
            fields = schema.fields_in(group.name)
            done = set(
                session.scalars(
                    select(Candidate.field_path).where(
                        Candidate.extraction_run_id == run.id,
                        Candidate.tenant_id == tenant_id,
                        Candidate.field_path.in_([field.path for field in fields]),
                    )
                )
            )
            if done == {field.path for field in fields}:
                continue
            window = select_pages(
                group.routing,
                sections,
                page_texts,
                max_pages=self._settings.extract_max_pages_per_group,
                fallback_pages=self._settings.extract_max_pages_per_call,
            )
            drafts: dict[str, list[_Draft]] = {field.path: [] for field in fields}
            not_found: dict[str, list[str]] = {field.path: [] for field in fields}
            model = build_group_model(schema, group, self._schemas)
            for chunk, pdf_b64 in self._windows(pdf, window):
                response = self._llm.call(
                    LLMRequest[BaseModel](
                        prompt_name=group.prompt_name,
                        prompt_version=run.prompt_version,
                        content=[
                            PdfPart(data_b64=pdf_b64, title=document.filename),
                            TextPart(text=_instructions(document, schema, group, fields, chunk)),
                        ],
                        response_model=model,
                        created_by=ACTOR,
                        is_fixture=run.is_fixture,
                        extraction_run_id=run.id,
                        output_schema_name=f"{schema.name}:{schema.version}:{group.name}",
                    )
                )
                for field in fields:
                    item = getattr(response.parsed, field.key)
                    if item.value is None:
                        not_found[field.path].append(item.rationale)
                    else:
                        quotes = [quote for quote in item.evidence if quote.quote.strip()]
                        drafts[field.path].append(
                            _Draft(
                                value=item.value,
                                confidence=min(max(float(item.confidence), 0.0), 1.0),
                                rationale=item.rationale,
                                quotes=quotes,
                                chunk=chunk,
                                call_log_id=response.call_log_id,
                            )
                        )
            for field in fields:
                if field.path in done:
                    continue
                self._insert_field(
                    session,
                    run,
                    group,
                    field,
                    drafts[field.path],
                    not_found[field.path],
                    window,
                    pages,
                )
            session.commit()

        self._supersede_earlier_runs(session, run)
        tokens_in, tokens_out = session.execute(
            select(
                func.coalesce(func.sum(LLMCallLog.tokens_in), 0),
                func.coalesce(func.sum(LLMCallLog.tokens_out), 0),
            ).where(LLMCallLog.extraction_run_id == run.id, LLMCallLog.tenant_id == tenant_id)
        ).one()
        run.token_in, run.token_out = int(tokens_in), int(tokens_out)
        run.cost_usd = Decimal(
            str(
                round(
                    tokens_in / 1e6 * self._settings.llm_price_in_per_mtok
                    + tokens_out / 1e6 * self._settings.llm_price_out_per_mtok,
                    4,
                )
            )
        )
        run.status = "extracted"
        jobs.enqueue(
            session,
            tenant_id=run.tenant_id,
            kind="validate",
            payload={"extraction_run_id": run.id},
            created_by=ACTOR,
        )
        session.commit()
        return run

    def _windows(self, pdf: bytes, window: list[int]) -> Iterator[tuple[list[int], str]]:
        """Page chunks of at most the per-call cap, each as a base64 PDF of those pages.
        A chunk whose PDF is too large for one request is halved."""
        pending = list(chunked(window, self._settings.extract_max_pages_per_call))
        with pymupdf.open(stream=pdf, filetype="pdf") as source:  # type: ignore[no-untyped-call]
            while pending:
                chunk = pending.pop(0)
                data = _sub_pdf(source, chunk)
                if len(data) > MAX_PDF_BYTES and len(chunk) > 1:
                    half = len(chunk) // 2
                    pending[:0] = [chunk[:half], chunk[half:]]
                    continue
                yield chunk, base64.standard_b64encode(data).decode("ascii")

    def _insert_field(
        self,
        session: Session,
        run: ExtractionRun,
        group: FieldGroup,
        field: FieldDef,
        drafts: list[_Draft],
        not_found: list[str],
        window: list[int],
        pages: "_PageCache",
    ) -> None:
        if not drafts:
            rationale = not_found[0] if not_found else "The model returned no value."
            self._add_candidate(
                session, run, group, field, None, 0.0, rationale, "not_found", window, None, []
            )
            return
        for draft in drafts:
            spans = [
                self._resolve(quote, draft.chunk, run.document_id, pages) for quote in draft.quotes
            ]
            if not spans:
                status, confidence = "rejected", draft.confidence
            else:
                status = "raw"
                located = any(span["char_start"] is not None for span in spans)
                confidence = (
                    draft.confidence if located else min(draft.confidence, UNLOCATED_CONFIDENCE_CAP)
                )
            self._add_candidate(
                session,
                run,
                group,
                field,
                draft.value,
                confidence,
                draft.rationale,
                status,
                draft.chunk,
                draft.call_log_id,
                spans,
            )

    def _add_candidate(
        self,
        session: Session,
        run: ExtractionRun,
        group: FieldGroup,
        field: FieldDef,
        value: Any,
        confidence: float,
        rationale: str,
        status: str,
        window: list[int],
        call_log_id: str | None,
        spans: list[dict[str, Any]],
    ) -> None:
        if status == "raw" and not spans:
            raise AssertionError("a reviewable candidate must carry evidence")
        candidate = Candidate(
            tenant_id=run.tenant_id,
            created_by=ACTOR,
            extraction_run_id=run.id,
            field_path=field.path,
            value=value,
            value_type=field.value_type,
            confidence=confidence,
            rationale=rationale,
            status=status,
            prompt_name=group.prompt_name,
            prompt_version=run.prompt_version,
            llm_call_log_id=call_log_id,
            window_pages=window,
        )
        session.add(candidate)
        session.flush()
        for span in spans:
            session.add(
                EvidenceSpan(
                    tenant_id=run.tenant_id,
                    created_by=ACTOR,
                    candidate_id=candidate.id,
                    document_id=run.document_id,
                    **span,
                )
            )
        audit.record(
            session,
            tenant_id=run.tenant_id,
            actor=ACTOR,
            action="insert",
            table_name="candidate",
            row_id=candidate.id,
            after={
                "extraction_run_id": run.id,
                "field_path": field.path,
                "value": value,
                "confidence": confidence,
                "status": status,
                "evidence_spans": len(spans),
            },
        )

    def _resolve(
        self, quote: EvidenceQuote, chunk: list[int], document_id: str, pages: "_PageCache"
    ) -> dict[str, Any]:
        """Locate the quote: stated page, then adjacent pages, then the rest of the window."""
        threshold = self._settings.evidence_match_threshold
        in_range = 1 <= quote.page_no <= len(chunk)
        stated = chunk[quote.page_no - 1] if in_range else chunk[0]
        order: list[tuple[str, list[int]]] = [
            ("stated_page", [stated] if in_range else []),
            ("adjacent_page", [stated - 1, stated + 1] if in_range else []),
            ("window_page", [page_no for page_no in chunk if page_no != stated or not in_range]),
        ]
        tried: set[int] = set()
        for resolution, candidates in order:
            best: Located | None = None
            for page_no in candidates:
                if page_no in tried:
                    continue
                tried.add(page_no)
                page = pages.get(page_no)
                found = locate(quote.quote, page, threshold) if page else None
                if found and (best is None or found.score > best.score):
                    best = found
            if best is not None:
                return {
                    "page_no": best.page_no,
                    "stated_page_no": stated,
                    "bbox": best.bbox,
                    "char_start": best.char_start,
                    "char_end": best.char_end,
                    "quote": quote.quote,
                    "resolution": resolution,
                    "match_score": best.score,
                }
        return {
            "page_no": stated,
            "stated_page_no": stated,
            "bbox": None,
            "char_start": None,
            "char_end": None,
            "quote": quote.quote,
            "resolution": "unresolved",
            "match_score": None,
        }

    def _supersede_earlier_runs(self, session: Session, run: ExtractionRun) -> None:
        """The newest run of an object keeps the live candidates. A run that finishes
        supersedes the candidates of runs started before it; if a run started after it
        has already finished, this run's own candidates are superseded instead."""
        same_object = (
            ExtractionRun.tenant_id == run.tenant_id,
            ExtractionRun.object_type == run.object_type,
            ExtractionRun.object_id == run.object_id,
            ExtractionRun.object_version == run.object_version,
            ExtractionRun.schema_name == run.schema_name,
            ExtractionRun.id != run.id,
        )
        newer_finished = session.scalar(
            select(ExtractionRun.id)
            .where(
                *same_object,
                ExtractionRun.created_at > run.created_at,
                ExtractionRun.status.in_(("extracted", "validated")),
            )
            .limit(1)
        )
        if newer_finished is not None:
            outdated = session.scalars(
                select(Candidate).where(
                    Candidate.extraction_run_id == run.id,
                    Candidate.tenant_id == run.tenant_id,
                    Candidate.status.in_(LIVE_STATUSES),
                )
            )
        else:
            outdated = session.scalars(
                select(Candidate)
                .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
                .where(
                    *same_object,
                    ExtractionRun.created_at <= run.created_at,
                    Candidate.tenant_id == run.tenant_id,
                    Candidate.status.in_(LIVE_STATUSES),
                )
            )
        superseded_by = newer_finished or run.id
        for candidate in outdated:
            before = candidate.status
            candidate.status = "superseded"
            audit.record(
                session,
                tenant_id=run.tenant_id,
                actor=ACTOR,
                action="status_change",
                table_name="candidate",
                row_id=candidate.id,
                before={"status": before},
                after={"status": "superseded", "superseded_by_run": superseded_by},
            )


class _PageCache:
    """Loads page text and character boxes on demand; a run touches few pages per field."""

    def __init__(self, session: Session, document_id: str, tenant_id: str) -> None:
        self._session = session
        self._document_id = document_id
        self._tenant_id = tenant_id
        self._pages: dict[int, PageText | None] = {}

    def get(self, page_no: int) -> PageText | None:
        if page_no not in self._pages:
            row = self._session.execute(
                select(Page.text, Page.char_boxes, Page.has_text_layer).where(
                    Page.document_id == self._document_id,
                    Page.tenant_id == self._tenant_id,
                    Page.page_no == page_no,
                )
            ).one_or_none()
            self._pages[page_no] = (
                None
                if row is None
                else PageText(
                    page_no=page_no, text=row[0], char_boxes=row[1], has_text_layer=row[2]
                )
            )
        return self._pages[page_no]


def _sub_pdf(source: Any, pages: list[int]) -> bytes:
    """A PDF holding exactly the given 1-based pages, in order."""
    out: Any = pymupdf.open()  # type: ignore[no-untyped-call]
    try:
        start = previous = pages[0]
        for page_no in [*pages[1:], None]:
            if page_no is not None and page_no == previous + 1:
                previous = page_no
                continue
            out.insert_pdf(source, from_page=start - 1, to_page=previous - 1)
            if page_no is not None:
                start = previous = page_no
        return cast(bytes, out.tobytes(garbage=3, deflate=True))
    finally:
        out.close()


def _instructions(
    document: Document,
    schema: ExtractionSchema,
    group: FieldGroup,
    fields: list[FieldDef],
    chunk: list[int],
) -> str:
    mapping = "\n".join(
        f"attached page {position} = document page {page_no}"
        for position, page_no in enumerate(chunk, start=1)
    )
    lines = []
    for field in fields:
        parts = [f"- `{field.key}`: {field.label}. Type: {field.value_type}"]
        if field.unit:
            parts.append(f"unit: {field.unit}")
        if field.enum_values:
            parts.append(f"one of: {', '.join(field.enum_values)}")
        if field.help_text:
            parts.append(field.help_text)
        lines.append("; ".join(parts))
    guidance = f"\nGuidance for this group:\n{group.guidance.strip()}\n" if group.guidance else ""
    return (
        f"Document: {document.filename}\n"
        f"The attached PDF holds {len(chunk)} of its pages.\n{mapping}\n\n"
        f"Extract the fields of group `{group.name}` (schema {schema.name} {schema.version}):\n"
        + "\n".join(lines)
        + f"\n{guidance}\n"
        "In evidence, page_no is the attached page position (1 to "
        f"{len(chunk)}), not the document page number."
    )
