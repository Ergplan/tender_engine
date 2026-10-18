"""The agent's three tools and the judge of its findings.

`Harness` holds the state of one pass: which pages the agent has read, and the findings
it has submitted. The tools are plain methods, so tests drive them directly; `sdk_driver`
wraps them for the OpenAI Agents SDK and runs the loop. A finding is accepted only when
every quote it cites is located, by the same resolver core uses (`core.evidence.locate`),
on the page it names, and that page was read through `read_pages` first. A rejected
attempt is kept with its reason. Nothing here touches candidate or canonical_fact.
"""

import base64
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from agents import (
    Agent,
    ModelSettings,
    RunConfig,
    Runner,
    ToolOutputImage,
    ToolOutputText,
    function_tool,
)
from agents.exceptions import AgentsException, MaxTurnsExceeded
from agents.models.interface import ModelProvider
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from agent.inputs import PassInputs, describe
from agent.models import AgentFinding, AgentRun
from core.config import Settings
from core.evidence import PageText, locate
from core.llm.agent_calls import AgentCallLogger, LoggedProvider, openai_provider
from core.llm.registry import Prompt
from core.models import LLMCallLog, Page
from core.schemas import SchemaRegistry
from core.services import audit
from core.storage import Storage

ACTOR = "agent_pass"
SNIPPET_CHARS = 160
MAX_SEARCH_HITS = 20


class Quote(BaseModel):
    """One piece of evidence as the agent cites it."""

    document_no: int
    page_no: int
    quote: str


@dataclass
class RunOutcome:
    """How the agent loop ended."""

    final_output: str = ""
    # The loop stopped before the agent finished: the turn limit, or a model error after
    # some turns. The findings made so far stand.
    stopped: str | None = None


Driver = Callable[["Harness", str, str], RunOutcome]


@dataclass
class _PageRow:
    text: PageText
    render_path: str


@dataclass
class Harness:
    session: Session
    settings: Settings
    schemas: SchemaRegistry
    storage: Storage
    run: AgentRun
    inputs: PassInputs
    read: dict[int, set[int]] = field(default_factory=dict)
    attempts: int = 0
    # Per field, the id of the finding that currently stands (accepted, not_found or
    # withdrawn).
    standing: dict[str, str] = field(default_factory=dict)
    _pages: dict[tuple[int, int], _PageRow | None] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- tools ---------------------------------------------------------------------------

    def read_pages(
        self, document_no: int, page_nos: list[int], images: bool = False
    ) -> list[ToolOutputText | ToolOutputImage]:
        """The text of the pages (and their images when asked for, or when a page has no
        text layer). Marks them read."""
        with self._lock:
            document = self.inputs.document(document_no)
            if document is None:
                return [ToolOutputText(text=self._no_document(document_no))]
            wanted = [p for p in dict.fromkeys(page_nos) if 1 <= p <= document.page_count]
            unknown = [p for p in page_nos if p not in wanted]
            cap = self.settings.agent_max_pages_per_read
            out: list[ToolOutputText | ToolOutputImage] = []
            if unknown:
                out.append(
                    ToolOutputText(
                        text=f"Document {document_no} has pages 1 to {document.page_count}; "
                        f"{unknown} do not exist."
                    )
                )
            if len(wanted) > cap:
                out.append(
                    ToolOutputText(
                        text=f"At most {cap} pages per call: reading {wanted[:cap]}; ask again "
                        f"for {wanted[cap:]}."
                    )
                )
                wanted = wanted[:cap]
            for page_no in wanted:
                row = self._page(document_no, page_no)
                if row is None:
                    out.append(
                        ToolOutputText(text=f"Document {document_no} page {page_no}: not parsed.")
                    )
                    continue
                self.read.setdefault(document_no, set()).add(page_no)
                text = row.text.text.strip()
                if row.text.has_text_layer:
                    out.append(
                        ToolOutputText(
                            text=f"=== Document {document_no}, page {page_no} ===\n{text}"
                        )
                    )
                else:
                    out.append(
                        ToolOutputText(
                            text=f"=== Document {document_no}, page {page_no} === (no text "
                            "layer: a scanned page; evidence cannot be located on it, so a "
                            "value from it must be cited from another page that states it)"
                        )
                    )
                if (images or not row.text.has_text_layer) and self.settings.agent_page_images:
                    png = self.storage.get(row.render_path)
                    out.append(
                        ToolOutputImage(
                            image_url="data:image/png;base64,"
                            + base64.standard_b64encode(png).decode(),
                            detail="auto",
                        )
                    )
            self._record_pages_read()
            return out

    def search_text(self, query: str, document_no: int | None = None) -> str:
        """Pages on which the phrase occurs (case-insensitive), with a snippet each, over
        every page of the documents or of one document."""
        needle = " ".join(query.split()).lower()
        if len(needle) < 3:
            return "Give a phrase of at least three characters."
        documents = [
            d for d in self.inputs.documents if document_no is None or d.number == document_no
        ]
        if not documents:
            return self._no_document(document_no or 0)
        hits: list[str] = []
        with self._lock:
            for document in documents:
                rows = self.session.execute(
                    select(Page.page_no, Page.text)
                    .where(
                        Page.document_id == document.document_id,
                        Page.tenant_id == self.run.tenant_id,
                    )
                    .order_by(Page.page_no)
                )
                for page_no, text in rows:
                    flat = " ".join(text.split())
                    at = flat.lower().find(needle)
                    if at < 0:
                        continue
                    start = max(0, at - SNIPPET_CHARS // 2)
                    snippet = flat[start : at + len(needle) + SNIPPET_CHARS // 2]
                    hits.append(f"Document {document.number} page {page_no}: …{snippet}…")
                    if len(hits) >= MAX_SEARCH_HITS:
                        break
                if len(hits) >= MAX_SEARCH_HITS:
                    hits.append(f"(first {MAX_SEARCH_HITS} hits; narrow the phrase for more)")
                    break
        if not hits:
            return f"No page contains {query!r}."
        return "\n".join(hits)

    def submit_finding(
        self,
        field_path: str,
        value: str,
        confidence: float,
        rationale: str,
        evidence: list[Quote],
    ) -> str:
        """Judge and record one finding. Returns what the agent is told."""
        with self._lock:
            self.attempts += 1
            definition = self.inputs.field(field_path)
            if definition is None:
                return self._reject(
                    field_path, None, confidence, rationale, [], "unknown field path"
                )
            raw = _parse_value(value)
            spans = [self._span(q) for q in evidence]
            if not self.read:
                # The brief's rule: read before any finding, an abstention included.
                return self._reject(
                    field_path,
                    raw,
                    confidence,
                    rationale,
                    spans,
                    "no page has been read yet: call read_pages before submitting a finding",
                )
            if not 0 <= confidence <= 1:
                return self._reject(
                    field_path, raw, confidence, rationale, spans, "confidence must be 0 to 1"
                )
            if not rationale.strip():
                return self._reject(field_path, raw, confidence, rationale, spans, "no rationale")
            for q, span in zip(evidence, spans, strict=True):
                if span["document_id"] is None:
                    return self._reject(
                        field_path,
                        raw,
                        confidence,
                        rationale,
                        spans,
                        f"document {q.document_no} page {q.page_no} does not exist",
                    )
                if q.page_no not in self.read.get(q.document_no, set()):
                    return self._reject(
                        field_path,
                        raw,
                        confidence,
                        rationale,
                        spans,
                        f"document {q.document_no} page {q.page_no} was not read: call "
                        "read_pages before citing a page",
                    )
                if span["char_start"] is None:
                    return self._reject(
                        field_path,
                        raw,
                        confidence,
                        rationale,
                        spans,
                        f"the quote was not found on document {q.document_no} page "
                        f"{q.page_no}: copy it verbatim from the page text, or cite the page "
                        "that holds it",
                    )
            if raw is None:
                status = "withdrawn" if spans else "not_found"
                finding = self._record(
                    field_path, None, definition.value_type, confidence, rationale, status, spans
                )
                self._stand(field_path, finding)
                told = (
                    "recorded as withdrawn (null with the removing words as evidence)"
                    if spans
                    else "recorded as not found"
                )
                return f"{field_path}: {told}."
            if not spans:
                return self._reject(
                    field_path, raw, confidence, rationale, [], "a value needs evidence"
                )
            try:
                coerced = self.schemas.value_types.coerce(raw, definition)
            except ValueError as exc:
                return self._reject(field_path, raw, confidence, rationale, spans, str(exc))
            finding = self._record(
                field_path, coerced, definition.value_type, confidence, rationale, "accepted", spans
            )
            self._stand(field_path, finding)
            where = ", ".join(f"document {s['document_no']} page {s['page_no']}" for s in spans)
            return f"{field_path}: accepted, {json.dumps(coerced)} with evidence on {where}."

    # -- what the pass tells the caller --------------------------------------------------

    def unsubmitted(self) -> list[str]:
        return [path for path in self.inputs.field_paths if path not in self.standing]

    def finish(self, status: str, error: str | None = None) -> AgentRun:
        """Close the run: its status, turns, tokens and cost from its logged calls."""
        run = self.run
        totals = self.session.execute(
            select(
                func.count(LLMCallLog.id),
                func.coalesce(func.sum(LLMCallLog.tokens_in), 0),
                func.coalesce(func.sum(LLMCallLog.cache_read_tokens), 0),
                func.coalesce(func.sum(LLMCallLog.tokens_out), 0),
                func.coalesce(func.sum(LLMCallLog.cost_usd), 0),
            ).where(
                LLMCallLog.agent_run_id == run.id,
                LLMCallLog.tenant_id == run.tenant_id,
                LLMCallLog.status == "ok",
            )
        ).one()
        run.turns = int(totals[0])
        run.tokens_in = int(totals[1]) + int(totals[2])
        run.tokens_cached = int(totals[2])
        run.tokens_out = int(totals[3])
        run.cost_usd = Decimal(totals[4]).quantize(Decimal("0.0001"))
        run.status = status
        run.error = error
        run.finished_at = datetime.now(UTC)
        run.pages_read = {str(no): sorted(pages) for no, pages in sorted(self.read.items())}
        audit.record(
            self.session,
            tenant_id=run.tenant_id,
            actor=ACTOR,
            action="finish",
            table_name="agent_run",
            row_id=run.id,
            before={"status": "running"},
            after={
                "status": status,
                "error": error,
                "turns": run.turns,
                "cost_usd": str(run.cost_usd),
                "findings": len(self.standing),
                "unsubmitted": self.unsubmitted(),
            },
        )
        self.session.commit()
        return run

    # -- internals -----------------------------------------------------------------------

    def _no_document(self, document_no: int) -> str:
        numbers = ", ".join(str(d.number) for d in self.inputs.documents)
        return f"There is no document {document_no}; the documents are {numbers}."

    def _page(self, document_no: int, page_no: int) -> _PageRow | None:
        key = (document_no, page_no)
        if key not in self._pages:
            document = self.inputs.document(document_no)
            row = (
                self.session.execute(
                    select(Page.text, Page.char_boxes, Page.has_text_layer, Page.render_path).where(
                        Page.document_id == document.document_id,
                        Page.tenant_id == self.run.tenant_id,
                        Page.page_no == page_no,
                    )
                ).one_or_none()
                if document is not None
                else None
            )
            self._pages[key] = (
                None
                if row is None
                else _PageRow(
                    text=PageText(
                        page_no=page_no, text=row[0], char_boxes=row[1], has_text_layer=row[2]
                    ),
                    render_path=row[3],
                )
            )
        return self._pages[key]

    def _span(self, quote: Quote) -> dict[str, Any]:
        """The quote as cited, located on the cited page where it can be."""
        document = self.inputs.document(quote.document_no)
        span: dict[str, Any] = {
            "document_id": document.document_id if document else None,
            "document_no": quote.document_no,
            "page_no": quote.page_no,
            "quote": quote.quote,
            "char_start": None,
            "char_end": None,
            "bbox": None,
            "match_score": None,
            "match_method": None,
        }
        row = self._page(quote.document_no, quote.page_no) if document else None
        if row is None:
            span["document_id"] = None
            return span
        found = locate(quote.quote, row.text, self.settings.evidence_match_threshold)
        if found is not None:
            span.update(
                char_start=found.char_start,
                char_end=found.char_end,
                bbox=found.bbox,
                match_score=found.score,
                match_method=found.method,
            )
        return span

    def _reject(
        self,
        field_path: str,
        raw: Any,
        confidence: float,
        rationale: str,
        spans: list[dict[str, Any]],
        reason: str,
    ) -> str:
        definition = self.inputs.field(field_path)
        self._record(
            field_path,
            raw,
            definition.value_type if definition else "unknown",
            confidence,
            rationale,
            "rejected",
            spans,
            reason=reason,
        )
        return f"{field_path}: rejected — {reason}."

    def _record(
        self,
        field_path: str,
        value: Any,
        value_type: str,
        confidence: float,
        rationale: str,
        status: str,
        spans: list[dict[str, Any]],
        reason: str | None = None,
    ) -> AgentFinding:
        finding = AgentFinding(
            tenant_id=self.run.tenant_id,
            created_by=ACTOR,
            agent_run_id=self.run.id,
            ordinal=self.attempts,
            field_path=field_path,
            value=value,
            value_type=value_type,
            confidence=max(0.0, min(1.0, confidence)),
            rationale=rationale,
            status=status,
            reason=reason,
            evidence=spans,
        )
        self.session.add(finding)
        self.session.flush()
        audit.record(
            self.session,
            tenant_id=self.run.tenant_id,
            actor=ACTOR,
            action="insert",
            table_name="agent_finding",
            row_id=finding.id,
            after={
                "agent_run_id": self.run.id,
                "field_path": field_path,
                "value": value,
                "status": status,
                "reason": reason,
                "evidence": len(spans),
            },
        )
        self.session.commit()
        return finding

    def _stand(self, field_path: str, finding: AgentFinding) -> None:
        earlier_id = self.standing.get(field_path)
        if earlier_id is not None:
            earlier = self.session.scalar(
                select(AgentFinding).where(
                    AgentFinding.id == earlier_id, AgentFinding.tenant_id == self.run.tenant_id
                )
            )
            if earlier is not None and earlier.status != "superseded":
                before = earlier.status
                earlier.status = "superseded"
                audit.record(
                    self.session,
                    tenant_id=self.run.tenant_id,
                    actor=ACTOR,
                    action="status_change",
                    table_name="agent_finding",
                    row_id=earlier.id,
                    before={"status": before},
                    after={"status": "superseded", "superseded_by": finding.id},
                )
                self.session.commit()
        self.standing[field_path] = finding.id

    def _record_pages_read(self) -> None:
        self.run.pages_read = {str(no): sorted(pages) for no, pages in sorted(self.read.items())}
        self.session.commit()


def _parse_value(value: str) -> Any:
    """The value as JSON text; a bare string that is not JSON is the string itself."""
    text = value.strip()
    if text == "":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


# -- the SDK driver ----------------------------------------------------------------------


def sdk_tools(harness: Harness) -> list[Any]:
    """The three tools as the SDK sees them, closing over the harness."""

    @function_tool
    def read_pages(
        document_no: int, page_nos: list[int], images: bool = False
    ) -> list[ToolOutputText | ToolOutputImage]:
        """Read pages of a document: their text, and their images when `images` is true
        (or when a page has no text layer). You must read a page before you cite it.

        Args:
            document_no: The document's number as listed in the brief.
            page_nos: Page positions in that document, from 1 (not printed page numbers).
            images: Also return each page as an image (for tables and garbled text).
        """
        return harness.read_pages(document_no, page_nos, images)

    @function_tool
    def search_text(query: str, document_no: int | None = None) -> str:
        """Find the pages on which a phrase occurs, with a snippet each, across every page
        of every document (or of one document).

        Args:
            query: The phrase to look for, case-insensitive, at least three characters.
            document_no: Limit the search to this document; omit for all.
        """
        return harness.search_text(query, document_no)

    @function_tool
    def submit_finding(
        field_path: str, value: str, confidence: float, rationale: str, evidence: list[Quote]
    ) -> str:
        """Submit one finding for one field. Accepted only when every quote is found
        verbatim on the page it cites and that page was read first; a refusal says why.

        Args:
            field_path: The field's path from the brief.
            value: The value as JSON text: a string in quotes, a number, true/false, a
                list, an object, or null when the documents do not state it.
            confidence: 0 to 1.
            rationale: Why the passage answers the field; conversions and doubts.
            evidence: Quotes copied verbatim from pages you have read; empty only with a
                null value.
        """
        return harness.submit_finding(field_path, value, confidence, rationale, evidence)

    return [read_pages, search_text, submit_finding]


def sdk_driver(
    settings: Settings,
    session_factory: sessionmaker[Session],
    prompt: Prompt,
    *,
    provider: ModelProvider | None = None,
) -> Driver:
    """The driver that runs the OpenAI Agents SDK loop with the configured model, every
    turn logged. `provider` replaces the real one in tests."""

    def drive(harness: Harness, instructions: str, brief: str) -> RunOutcome:
        logger = AgentCallLogger(
            settings,
            session_factory,
            prompt=prompt,
            agent_run_id=harness.run.id,
            created_by=harness.run.created_by,
            is_fixture=harness.run.is_fixture,
        )
        agent = Agent(
            name="tender-reader",
            instructions=instructions,
            tools=sdk_tools(harness),
            model=settings.openai_model,
            # Several tool calls in one turn (a run of findings from one page) cost one
            # model call instead of one each; the harness lock serialises them.
            model_settings=ModelSettings(parallel_tool_calls=True),
        )
        config = RunConfig(
            model_provider=LoggedProvider(logger, provider or openai_provider(settings)),
            tracing_disabled=True,
        )
        try:
            result = Runner.run_sync(
                agent, brief, max_turns=settings.agent_max_turns, run_config=config
            )
        except MaxTurnsExceeded:
            return RunOutcome(stopped=f"stopped at the turn limit ({settings.agent_max_turns})")
        except AgentsException as exc:
            return RunOutcome(stopped=f"{type(exc).__name__}: {exc}")
        return RunOutcome(final_output=str(result.final_output or ""))

    return drive


def brief_for(inputs: PassInputs) -> str:
    return describe(inputs)
