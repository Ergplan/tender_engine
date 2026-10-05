"""ExtractService: field groups -> page windows -> model call -> candidates with evidence.

Model output stops here, in the candidate table. Candidates are inserted once and never
updated (a database trigger allows only their status to change).

Groups whose windows overlap enough are read from one shared window, sent as a cached
prefix (core.services.extract_plan). The output schema is part of what the provider caches
ahead of the pages, so the calls on a shared window all carry one schema that fits any
group (SharedAnswer: a list of entries, one per field); the answer is then checked against
the group's own typed model, and a call whose answer does not pass is made again on its
own with that model. A run in batch mode
sends its calls through the batch API in two waves: first the calls that write each shared
window to the cache, then the calls that read it.
"""

import base64
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

import pymupdf
from pydantic import BaseModel, ValidationError, create_model
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.evidence import Located, Match, PageText, locate, resolve_pair
from core.llm.client import LLMClient, LLMRequest, LLMResponse, PdfPart, TextPart
from core.models import (
    Candidate,
    Document,
    EvidenceSpan,
    ExtractionRun,
    LLMBatch,
    LLMCallLog,
    Page,
    Section,
)
from core.models.extraction import RECORD_MODE, RUN_MODES
from core.schemas import ExtractionSchema, FieldDef, FieldGroup, RoutingHints, SchemaRegistry
from core.schemas.types import JsonKind
from core.services import audit, jobs
from core.services.extract_plan import SharedWindow, share_windows
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
class _Call:
    """One model call of a run: one group read from one chunk of its window."""

    window: SharedWindow
    group: FieldGroup
    chunk: list[int]
    request: LLMRequest[BaseModel]
    # The first call on a shared chunk writes it to the cache; the others read it.
    writes_cache: bool
    # The same call on its own: the group's own typed schema, nothing cached. Made when the
    # answer of a call on a shared window does not pass that schema.
    alone: LLMRequest[BaseModel]


@dataclass
class _Draft:
    value: Any
    confidence: float
    rationale: str
    # Each quote with its place in the model's evidence list, from 1.
    quotes: list[tuple[int, EvidenceQuote]]
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


class SharedEntry(BaseModel):
    key: str
    value: str | float | bool | list[str] | None
    confidence: float
    rationale: str
    evidence: list[EvidenceQuote]


class SharedAnswer(BaseModel):
    """The structured-output model of every call on a shared window, whatever its group:
    one entry per field asked for. A schema with each group's typed fields would differ
    from call to call and with it the cached prefix (and one schema holding all groups is
    too large for the provider to compile)."""

    fields: list[SharedEntry]


def typed_answer(answer: BaseModel, model: type[BaseModel]) -> BaseModel | None:
    """A SharedAnswer as the group's own model, or None when it is not a complete, well
    typed answer for the group: a field missing or given twice, or a value of the wrong
    kind. An entry whose key is no field of the group is dropped."""
    entries = getattr(answer, "fields", None)
    if not isinstance(entries, list):
        return None
    own = [entry for entry in entries if entry.key in model.model_fields]
    by_key = {entry.key: entry for entry in own}
    if len(by_key) != len(own) or set(by_key) != set(model.model_fields):
        return None
    try:
        return model.model_validate(
            {key: entry.model_dump(exclude={"key"}) for key, entry in by_key.items()}
        )
    except ValidationError:
        return None


def select_pages(
    routing: RoutingHints,
    sections: list[tuple[int, int, str, str]],
    page_texts: dict[int, str],
    *,
    max_pages: int,
    fallback_pages: int,
    keyword_pages: int = 0,
) -> list[int]:
    """Pages for a group: sections whose kind or heading the hints name, plus up to
    `keyword_pages` pages outside them, taken keyword by keyword in turn (each keyword's
    best page first), so the choice does not hang on how the section map happened to label
    a clause and a frequent keyword cannot crowd out a rare one. If no section matches,
    every page that mentions a keyword; if still none, the opening pages.
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
    else:
        pages.update(_keyword_pages(keywords, page_texts, pages, keyword_pages))
    if not pages:
        pages = set(sorted(page_texts)[:fallback_pages])
    if len(pages) > max_pages:
        ranked = sorted(pages, key=lambda page_no: (-hits.get(page_no, 0), page_no))
        pages = set(ranked[:max_pages])
    return sorted(pages)


def _keyword_pages(
    keywords: list[str], page_texts: dict[int, str], taken: set[int], budget: int
) -> list[int]:
    """Up to `budget` pages not yet taken: round-robin over the keywords, each giving its
    pages in order of most mentions."""
    ranked = []
    for keyword in keywords:
        counts = {page_no: text.lower().count(keyword) for page_no, text in page_texts.items()}
        ranked.append(
            sorted(
                (page_no for page_no, count in counts.items() if count > 0),
                key=lambda page_no, counts=counts: (-counts[page_no], page_no),  # type: ignore[misc]
            )
        )
    chosen: list[int] = []
    for rank in range(max((len(pages) for pages in ranked), default=0)):
        for pages in ranked:
            if len(chosen) >= budget:
                return chosen
            if rank < len(pages) and pages[rank] not in taken and pages[rank] not in chosen:
                chosen.append(pages[rank])
    return chosen


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
        groups: list[str] | None = None,
        is_fixture: bool = False,
        mode: str = "sync",
    ) -> ExtractionRun:
        """Create the run and enqueue it. Refuses unknown schemas and unregistered prompts.
        `groups` limits the run to those field groups of the schema. `mode` is "sync" (the
        worker makes each call and waits) or "batch" (the calls go through the batch API,
        at half the price, for a run nobody waits for)."""
        if mode not in RUN_MODES:
            raise ExtractionError(f"unknown mode {mode!r}; one of {list(RUN_MODES)}")
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
        if groups is not None:
            unknown = sorted(set(groups) - {group.name for group in schema.groups})
            if unknown or not groups:
                raise ExtractionError(f"schema {schema.name} has no group(s) {unknown}")
        for group in _run_groups(schema, groups):
            self._llm.prompt(group.prompt_name, group.prompt_version or prompt_version)
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
            groups=sorted(set(groups)) if groups is not None else None,
            model=self._llm.model,
            status="queued",
            is_fixture=is_fixture,
            mode=mode,
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
        """Run every field group. Commits per shared window, and a call the run has
        already paid for is read from the log, so a retry resumes where it stopped. A
        batch run returns while its batch is being worked on, with a job queued to look
        again; it is then still `running`."""
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
        pages = _PageCache(session, document.id, tenant_id)
        calls = self._plan_calls(session, run, document, schema)

        if run.mode == "batch" and not self._batches_done(session, run, calls):
            jobs.enqueue(
                session,
                tenant_id=tenant_id,
                kind="extract",
                payload={"extraction_run_id": run.id},
                created_by=ACTOR,
                delay_seconds=self._settings.llm_batch_poll_seconds,
            )
            session.commit()
            return run

        position = 0
        while position < len(calls):
            window = calls[position].window
            answers: list[tuple[_Call, BaseModel, str]] = []
            while position < len(calls) and calls[position].window is window:
                call = calls[position]
                answers.append((call, *self._answer(call)))
                position += 1
            for name in window.groups:
                group = next(g for g in schema.groups if g.name == name)
                fields = schema.fields_in(name)
                drafts: dict[str, list[_Draft]] = {field.path: [] for field in fields}
                not_found: dict[str, list[str]] = {field.path: [] for field in fields}
                for call, parsed, call_log_id in answers:
                    if call.group.name != name:
                        continue
                    for field in fields:
                        item = getattr(parsed, field.key)
                        if item.value is None:
                            not_found[field.path].append(item.rationale)
                        else:
                            quotes = [
                                (place, quote)
                                for place, quote in enumerate(item.evidence, start=1)
                                if quote.quote.strip()
                            ]
                            drafts[field.path].append(
                                _Draft(
                                    value=item.value,
                                    confidence=min(max(float(item.confidence), 0.0), 1.0),
                                    rationale=item.rationale,
                                    quotes=quotes,
                                    chunk=call.chunk,
                                    call_log_id=call_log_id,
                                )
                            )
                done = self._done_fields(session, run, fields)
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
                        list(window.pages),
                        pages,
                    )
            session.commit()

        self._supersede_earlier_runs(session, run)
        tokens_in, tokens_cached, tokens_out, cost = session.execute(
            select(
                func.coalesce(
                    func.sum(
                        LLMCallLog.tokens_in
                        + LLMCallLog.cache_write_tokens
                        + LLMCallLog.cache_read_tokens
                    ),
                    0,
                ),
                func.coalesce(func.sum(LLMCallLog.cache_read_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.tokens_out), 0),
                func.coalesce(func.sum(LLMCallLog.cost_usd), 0),
            ).where(LLMCallLog.extraction_run_id == run.id, LLMCallLog.tenant_id == tenant_id)
        ).one()
        run.token_in, run.token_cached, run.token_out = (
            int(tokens_in),
            int(tokens_cached),
            int(tokens_out),
        )
        run.cost_usd = Decimal(cost).quantize(Decimal("0.0001"))
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

    def _answer(self, call: _Call) -> tuple[BaseModel, str]:
        """The group's answer for one call and the id of the call log row it came from:
        read from the log when the run already has it, asked for otherwise. A call on a
        shared window whose answer is not a complete, well typed answer for the group is
        made again on its own, with the group's typed model."""
        response: LLMResponse[BaseModel] = self._llm.logged(call.request) or self._llm.call(
            call.request
        )
        if not call.window.shared:
            return response.parsed, response.call_log_id
        typed = typed_answer(response.parsed, call.alone.response_model)
        if typed is None:
            response = self._llm.logged(call.alone) or self._llm.call(call.alone)
            return response.parsed, response.call_log_id
        return typed, response.call_log_id

    def _done_fields(
        self, session: Session, run: ExtractionRun, fields: list[FieldDef]
    ) -> set[str]:
        return set(
            session.scalars(
                select(Candidate.field_path).where(
                    Candidate.extraction_run_id == run.id,
                    Candidate.tenant_id == run.tenant_id,
                    Candidate.field_path.in_([field.path for field in fields]),
                )
            )
        )

    def _plan_calls(
        self, session: Session, run: ExtractionRun, document: Document, schema: ExtractionSchema
    ) -> list[_Call]:
        """Every call the run still has to make, in the order they are made: window by
        window, chunk by chunk, and within a chunk group by group, so that the calls which
        share a chunk follow each other while it is in the cache. The windows depend only
        on the document, the schema and the settings, so they are the same on every
        attempt; windows whose groups already have candidates are left out."""
        done: set[str] = set()
        groups: dict[str, FieldGroup] = {}
        for group in _run_groups(schema, run.groups):
            fields = schema.fields_in(group.name)
            if self._done_fields(session, run, fields) == {field.path for field in fields}:
                done.add(group.name)
            groups[group.name] = group
        batch = run.mode == "batch"
        _, plan = self.plan_windows(session, document, schema, list(groups), batch=batch)
        pdf = self._storage.get(document.storage_path)
        calls: list[_Call] = []
        for window in plan:
            # A window's groups are committed together, so they are all done or none is.
            if done.issuperset(window.groups):
                continue
            for chunk, pdf_b64 in self._windows(pdf, list(window.pages)):
                part = PdfPart(data_b64=pdf_b64, title=document.filename)
                for index, name in enumerate(window.groups):
                    alone = self._request(run, document, schema, groups[name], chunk, part)
                    calls.append(
                        _Call(
                            window=window,
                            group=groups[name],
                            chunk=chunk,
                            writes_cache=index == 0,
                            alone=alone,
                            request=self._request(
                                run,
                                document,
                                schema,
                                groups[name],
                                chunk,
                                part,
                                shared=True,
                                cache_ttl="1h" if batch else "5m",
                            )
                            if window.shared
                            else alone,
                        )
                    )
        return calls

    def _request(
        self,
        run: ExtractionRun,
        document: Document,
        schema: ExtractionSchema,
        group: FieldGroup,
        chunk: list[int],
        part: PdfPart,
        *,
        shared: bool = False,
        cache_ttl: Literal["5m", "1h"] = "5m",
    ) -> LLMRequest[BaseModel]:
        """The call for one group on one chunk. With `shared`, the call on a shared window:
        the schema every group uses and the pages as a cached prefix."""
        fields = schema.fields_in(group.name)
        return LLMRequest[BaseModel](
            prompt_name=group.prompt_name,
            prompt_version=group.prompt_version or run.prompt_version,
            content=[
                part,
                TextPart(text=_instructions(document, schema, group, fields, chunk, shared)),
            ],
            response_model=SharedAnswer
            if shared
            else build_group_model(schema, group, self._schemas),
            created_by=ACTOR,
            is_fixture=run.is_fixture,
            extraction_run_id=run.id,
            output_schema_name=f"{schema.name}:{schema.version}:{group.name}",
            cache_documents=shared,
            cache_ttl=cache_ttl,
        )

    def plan_windows(
        self,
        session: Session,
        document: Document,
        schema: ExtractionSchema,
        group_names: list[str],
        *,
        batch: bool = False,
    ) -> tuple[dict[str, list[int]], list[SharedWindow]]:
        """The window each of the groups would get on its own, and the windows they are
        actually read from once groups share. No model call, nothing written."""
        tenant_id = document.tenant_id
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
        settings = self._settings
        caps = {
            group.name: min(
                group.max_pages or settings.extract_max_pages_per_group,
                settings.extract_max_pages_per_group,
            )
            for group in schema.groups
            if group.name in group_names
        }
        windows = {
            group.name: select_pages(
                group.routing,
                sections,
                page_texts,
                max_pages=caps[group.name],
                fallback_pages=settings.extract_max_pages_per_call,
                keyword_pages=settings.extract_keyword_pages,
            )
            for group in schema.groups
            if group.name in group_names
        }
        if not settings.extract_share_windows:
            return windows, [
                SharedWindow(groups=(name,), pages=tuple(pages))
                for name, pages in windows.items()
                if pages
            ]
        return windows, share_windows(
            windows,
            max_pages=settings.extract_max_pages_per_group,
            caps=caps,
            pages_per_call=settings.extract_max_pages_per_call,
            # A batch run keeps a window in the cache for an hour, between its waves.
            cache_write_factor=settings.llm_cache_write_1h_factor
            if batch
            else settings.llm_cache_write_factor,
            cache_read_factor=settings.llm_cache_read_factor,
            call_overhead_pages=settings.extract_call_overhead_pages,
        )

    def _batches_done(self, session: Session, run: ExtractionRun, calls: list[_Call]) -> bool:
        """Move a batch run one step on. False while a batch is being worked on. True once
        both waves are collected (or nothing is left to send): what the batches did not
        answer is then called directly."""
        requests = [call.request for call in calls]
        batches = list(
            session.scalars(
                select(LLMBatch)
                .where(LLMBatch.extraction_run_id == run.id, LLMBatch.tenant_id == run.tenant_id)
                .order_by(LLMBatch.created_at)
            )
        )
        for batch in batches:
            if batch.status != "collected" and not self._llm.collect_batch(batch.id, requests):
                return False
        waves = max((batch.wave for batch in batches), default=0)
        if waves >= 2:
            return True
        pending = [call for call in calls if self._llm.logged(call.request) is None]
        if waves == 0:
            first = [c for c in pending if c.writes_cache or not c.window.shared]
            if first:
                self._llm.submit_batch(
                    [c.request for c in first],
                    created_by=ACTOR,
                    extraction_run_id=run.id,
                    wave=1,
                )
                return False
        second = [c for c in pending if c.window.shared and not c.writes_cache]
        if second:
            self._llm.submit_batch(
                [c.request for c in second], created_by=ACTOR, extraction_run_id=run.id, wave=2
            )
            return False
        return True

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
                {**self._resolve(quote, draft.chunk, run.document_id, pages), "ordinal": place}
                for place, quote in draft.quotes
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

    def record_candidate(
        self,
        session: Session,
        run: ExtractionRun,
        field_path: str,
        *,
        value: Any,
        confidence: float,
        rationale: str,
        spans: list[dict[str, Any]],
        call_log_id: str,
        prompt_name: str,
        prompt_version: str,
    ) -> Candidate:
        """Insert the candidate of a run that was written from the object's record rather
        than read from pages (run.mode "record"). Its evidence spans are inherited: each
        names its own document and is already located. The same insert, audit line and
        refusal of a candidate without evidence as for any other candidate."""
        if run.mode != RECORD_MODE:
            raise ExtractionError("only a record run takes a candidate written from the record")
        if not spans or any(span.get("char_start") is None for span in spans):
            raise ExtractionError("a candidate written from the record needs located evidence")
        schema = self._schemas.get(run.schema_name, run.schema_version)
        field = schema.field(field_path)
        group = next(group for group in schema.groups if group.name == field.group)
        return self._add_candidate(
            session,
            run,
            group,
            field,
            value,
            min(max(float(confidence), 0.0), 1.0),
            rationale,
            "raw",
            [],
            call_log_id,
            spans,
            prompt=(prompt_name, prompt_version),
        )

    def supersede(self, session: Session, candidate: Candidate, by_run: ExtractionRun) -> None:
        """Take a live candidate out of review because `by_run` replaces it. Audited."""
        if candidate.status not in LIVE_STATUSES:
            return
        before = candidate.status
        candidate.status = "superseded"
        audit.record(
            session,
            tenant_id=candidate.tenant_id,
            actor=ACTOR,
            action="status_change",
            table_name="candidate",
            row_id=candidate.id,
            before={"status": before},
            after={"status": "superseded", "superseded_by_run": by_run.id},
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
        prompt: tuple[str, str] | None = None,
    ) -> Candidate:
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
            prompt_name=prompt[0] if prompt else group.prompt_name,
            prompt_version=prompt[1] if prompt else group.prompt_version or run.prompt_version,
            llm_call_log_id=call_log_id,
            window_pages=window,
        )
        session.add(candidate)
        session.flush()
        for span in spans:
            # A span read from the run's document; an inherited one names its own.
            session.add(
                EvidenceSpan(
                    tenant_id=run.tenant_id,
                    created_by=ACTOR,
                    candidate_id=candidate.id,
                    **{"document_id": run.document_id, **span},
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
        return candidate

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
                    "match_method": best.method,
                }
        # Last: a quote that runs from the foot of one page onto the head of the next.
        if in_range:
            for first_no in (stated, stated - 1):
                first, second = pages.get(first_no), pages.get(first_no + 1)
                across = (
                    resolve_pair(quote.quote, first, second, threshold)
                    if first and second
                    else None
                )
                if isinstance(across, Match):
                    return {
                        "page_no": across.page_no,
                        "stated_page_no": stated,
                        "bbox": across.bbox,
                        "char_start": across.char_start,
                        "char_end": across.char_end,
                        "quote": quote.quote,
                        "resolution": "stated_page"
                        if across.page_no == stated
                        else "adjacent_page",
                        "match_score": across.score,
                        "match_method": across.method,
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
            "match_method": None,
        }

    def _supersede_earlier_runs(self, session: Session, run: ExtractionRun) -> None:
        """For each field and document, the newest run keeps the live candidates. A run that
        finishes supersedes the candidates that runs started before it produced from the
        same document for the fields it covers; where a run started after it has already
        finished for a field, this run's own candidates for that field are superseded
        instead. Candidates from the object's other documents are left alone."""
        schema = self._schemas.get(run.schema_name, run.schema_version)
        mine = _run_fields(schema, run.groups)
        others = list(
            session.scalars(
                select(ExtractionRun).where(
                    ExtractionRun.tenant_id == run.tenant_id,
                    ExtractionRun.object_type == run.object_type,
                    ExtractionRun.object_id == run.object_id,
                    ExtractionRun.object_version == run.object_version,
                    ExtractionRun.schema_name == run.schema_name,
                    ExtractionRun.document_id == run.document_id,
                    ExtractionRun.id != run.id,
                )
            )
        )
        lost: dict[str, str] = {}
        for other in others:
            if other.created_at > run.created_at and other.status in ("extracted", "validated"):
                for path in mine & _run_fields(schema, other.groups):
                    lost.setdefault(path, other.id)
        outdated: list[tuple[Candidate, str]] = []
        if lost:
            outdated += [
                (candidate, lost[candidate.field_path])
                for candidate in session.scalars(
                    select(Candidate).where(
                        Candidate.extraction_run_id == run.id,
                        Candidate.tenant_id == run.tenant_id,
                        Candidate.field_path.in_(lost),
                        Candidate.status.in_(LIVE_STATUSES),
                    )
                )
            ]
        earlier = [other.id for other in others if other.created_at <= run.created_at]
        if earlier:
            outdated += [
                (candidate, lost.get(candidate.field_path, run.id))
                for candidate in session.scalars(
                    select(Candidate).where(
                        Candidate.extraction_run_id.in_(earlier),
                        Candidate.tenant_id == run.tenant_id,
                        Candidate.field_path.in_(mine),
                        Candidate.status.in_(LIVE_STATUSES),
                    )
                )
            ]
        for candidate, superseded_by in outdated:
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


def _run_groups(schema: ExtractionSchema, groups: list[str] | None) -> list[FieldGroup]:
    return [group for group in schema.groups if groups is None or group.name in groups]


def _run_fields(schema: ExtractionSchema, groups: list[str] | None) -> set[str]:
    return {field.path for field in schema.fields if groups is None or field.group in groups}


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
    """A PDF holding exactly the given 1-based pages, in order. The same pages always give
    the same bytes (no fresh file id): the prompt cache and the call log both recognise a
    window by its bytes."""
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
        return cast(bytes, out.tobytes(garbage=3, deflate=True, no_new_id=True))
    finally:
        out.close()


def _instructions(
    document: Document,
    schema: ExtractionSchema,
    group: FieldGroup,
    fields: list[FieldDef],
    chunk: list[int],
    shared: bool = False,
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
        + (
            "\n\nReturn one entry in `fields` for every field listed above, with its `key` "
            "exactly as written there. Give each value in the kind its type calls for: text, "
            "dates and choices as a string, numbers as a number, yes or no as true or false, "
            "lists as a list of strings, and null when these pages do not state it."
            if shared
            else ""
        )
    )
