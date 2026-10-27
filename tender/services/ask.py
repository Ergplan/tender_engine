"""ask_tender (Stage 7, Block 5 b): one question about one tender.

When the question maps to a field, the answer is the approved fact for that field (or,
failing one, the engine's live reading, marked as machine); every quote behind it is
located on its page again by the evidence resolver before it is shown. Otherwise the best
chunks of the tender's documents are retrieved (`core.retrieval`), the model answers from
those passages alone, and each claim's quote is resolved on its page: a quote the resolver
cannot find is shown as unresolved, never dropped and never smoothed over. The answer is
against the current version (versions in date order) and says when an amendment changed
it. An answer is never written as a fact: it carries `is_fact: false` and the source it
came from, `approved` or `machine`."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.evidence.resolver import Match, PageText, resolve
from core.llm.client import LLMCallError, LLMClient, LLMRequest, TextPart
from core.models import Document, Page
from core.retrieval import Hit, Retriever
from core.schemas import SchemaRegistry
from core.services.review_state import ReviewStateService
from tender.models import Tender
from tender.services.amendments import tender_amendments
from tender.services.ask_fields import FieldMatch, map_question
from tender.services.current_view import current_view
from tender.services.packs import Catalog
from tender.services.tenders import OBJECT_TYPE, TenderService

PROMPT_NAME = "ask_tender"
PROMPT_VERSION = "v1"
AUTHORITY_NOTE = (
    "An answer is a reading of the tender's pages, not a fact of the record: only a "
    "reviewer's decision makes a fact. `source` says whether the value shown was approved."
)


class AskError(Exception):
    pass


# -- the model's output ------------------------------------------------------------------


class AskClaimOut(BaseModel):
    statement: str
    passage: int = Field(ge=1, description="the passage number the claim comes from")
    quote: str


class AskOutput(BaseModel):
    answer: str
    answered: bool = True
    claims: list[AskClaimOut] = []
    amendment_changed: bool = False
    amendment_note: str | None = None


# -- the answer ----------------------------------------------------------------------------


class Citation(BaseModel):
    n: int
    document_id: str
    filename: str | None
    page_no: int
    clause: str | None = None
    version_no: int | None = None
    quote: str
    resolved: bool
    char_start: int | None = None
    char_end: int | None = None
    bbox: list[float] | None = None
    score: float | None = None
    reason: str | None = None


class AskClaim(BaseModel):
    statement: str
    citations: list[int]


class AskAnswer(BaseModel):
    tender_id: str
    question: str
    version_no: int | None
    mode: Literal["field", "retrieval"]
    source: Literal["approved", "machine", "none"]
    answered: bool
    answer: str
    field_path: str | None = None
    label: str | None = None
    value: Any = None
    unit: str | None = None
    confidence: float | None = None
    claims: list[AskClaim] = []
    citations: list[Citation] = []
    citations_resolved: int = 0
    citations_total: int = 0
    amendment_changed: bool = False
    amendment_note: str | None = None
    retrieval: str | None = None
    passages_read: int = 0
    cost_usd: float = 0.0
    call_log_id: str | None = None
    is_fact: Literal[False] = False
    authority_note: str = AUTHORITY_NOTE


class AskService:
    def __init__(
        self,
        llm: LLMClient,
        catalog: Catalog,
        schemas: SchemaRegistry,
        tenders: TenderService,
        retriever: Retriever | None,
        settings: Settings,
    ) -> None:
        self._llm = llm
        self._catalog = catalog
        self._tenders = tenders
        self._retriever = retriever
        self._settings = settings
        self._schemas = schemas
        self._review_state = ReviewStateService(schemas, settings.tenant_id)
        self._tenant_id = settings.tenant_id

    # -- entry point -----------------------------------------------------------------------

    def ask(self, session: Session, tender: Tender, question: str, *, created_by: str) -> AskAnswer:
        question = " ".join(question.split())
        if not question:
            raise AskError("the question is empty")
        entries = self._tenders.versions(session, tender)
        current = entries[-1].version.version_no if entries else None
        schema = self._catalog.get(tender.tender_type).schema
        match = map_question(question, schema)
        if match is not None:
            answer = self._from_field(session, tender, match, question, current)
            if answer is not None:
                return answer
        return self._from_pages(session, tender, question, current, entries, created_by)

    # -- a field's fact --------------------------------------------------------------------

    def _from_field(
        self,
        session: Session,
        tender: Tender,
        match: FieldMatch,
        question: str,
        current: int | None,
    ) -> AskAnswer | None:
        field = match.field
        view = current_view(session, self._catalog, tender)
        fv = next((f for f in view.fields if f.field_path == field.path), None)
        if fv is None:
            return None
        source: Literal["approved", "machine", "none"]
        if fv.decided:
            source, value, version_no, evidence, confidence = (
                "approved",
                fv.value,
                fv.version_no,
                list(fv.evidence),
                None,
            )
        else:
            state = self._review_state.for_object(session, OBJECT_TYPE, tender.id)
            fs = next((f for f in state.fields if f.field_path == field.path), None)
            candidate = fs.candidate if fs is not None else None
            if candidate is None or candidate.value is None:
                return None  # nothing read for the field yet: the pages may still say
            source, value, version_no, confidence = (
                "machine",
                candidate.value,
                state.object_version,
                candidate.confidence,
            )
            evidence = [e.model_dump() for e in candidate.evidence]
        citations = self._resolve_evidence(session, evidence, version_no)
        unit = f" {fv.unit}" if fv.unit and not isinstance(value, dict | list) else ""
        if fv.withdrawn:
            text = f"{fv.label}: the provision was withdrawn by version {fv.version_no}" + (
                f" (it stood at {fv.withdrawn_value})." if fv.withdrawn_value is not None else "."
            )
        else:
            text = f"{fv.label}: {_shown(value)}{unit}."
        if source == "approved":
            text += (
                f" Approved fact, set by version {version_no} ({fv.version_kind or 'original'})."
            )
        else:
            text += (
                f" The engine's reading of version {version_no}, confidence "
                f"{confidence:.2f}, not yet reviewed."
            )
        note, changed_by = self._amendment_note(session, tender, field.path)
        return AskAnswer(
            tender_id=tender.id,
            question=question,
            version_no=current,
            mode="field",
            source=source,
            answered=True,
            answer=text,
            field_path=field.path,
            label=fv.label,
            value=value,
            unit=fv.unit,
            confidence=confidence,
            claims=[AskClaim(statement=text, citations=[c.n for c in citations])],
            citations=citations,
            citations_resolved=sum(1 for c in citations if c.resolved),
            citations_total=len(citations),
            amendment_changed=changed_by is not None,
            amendment_note=note,
        )

    def _amendment_note(
        self, session: Session, tender: Tender, field_path: str
    ) -> tuple[str | None, int | None]:
        try:
            amendments = tender_amendments(
                session, self._catalog, self._tenders, self._review_state, self._schemas, tender
            )
        except Exception:  # a tender without runs has no amendments view
            return None, None
        latest: tuple[str, int] | None = None
        for version in amendments.versions:
            for change in version.changes:
                if change.field_path != field_path or change.change_class == "restated":
                    continue
                before = (
                    f" (before: {_shown(change.before.value)}, version {change.before.version_no})"
                    if change.before is not None
                    else ""
                )
                issued = f" issued {version.issued_on:%d.%m.%Y}" if version.issued_on else ""
                latest = (
                    f"Version {version.version_no} ({version.kind}{issued}) "
                    f"{_class_text(change.change_class)}{before}.",
                    version.version_no,
                )
        return latest if latest else (None, None)

    def _resolve_evidence(
        self, session: Session, evidence: list[dict[str, Any]], version_no: int | None
    ) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[tuple[str, int, str]] = set()
        for span in evidence:
            document_id, page_no, quote = (
                span.get("document_id"),
                span.get("page_no"),
                span.get("quote"),
            )
            if not document_id or not page_no or not quote:
                continue
            key = (document_id, int(page_no), quote)
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                self._locate(
                    session, len(citations) + 1, document_id, int(page_no), quote, None, version_no
                )
            )
        return citations

    # -- the pages -------------------------------------------------------------------------

    def _from_pages(
        self,
        session: Session,
        tender: Tender,
        question: str,
        current: int | None,
        entries: list[Any],
        created_by: str,
    ) -> AskAnswer:
        base = dict(tender_id=tender.id, question=question, version_no=current, mode="retrieval")
        if self._retriever is None or not self._settings.retrieval_enabled:
            return AskAnswer(
                **base,
                source="none",
                answered=False,
                answer="No field of the record answers this and retrieval is not configured.",
            )
        document_ids = [doc.id for entry in entries for _, doc in entry.documents]
        if not document_ids:
            return AskAnswer(
                **base, source="none", answered=False, answer="The tender has no documents yet."
            )
        filters = {
            "operator": "AND",
            "conditions": [
                {"field": "meta.tender_id", "operator": "==", "value": tender.id},
                {"field": "meta.document_id", "operator": "in", "value": document_ids},
            ],
        }
        hits, retrieval_mode = self._retriever.retrieve(question, filters)
        if not hits:
            return AskAnswer(
                **base,
                source="none",
                answered=False,
                answer="No passage of the tender's documents matches the question "
                "(the documents may not be indexed yet).",
                retrieval=retrieval_mode,
            )
        passages = "\n\n".join(_passage(i + 1, hit) for i, hit in enumerate(hits))
        prompt_text = (
            f"Tender: {tender.title}\nType: {tender.tender_type}\n"
            f"Version asked about: {current} (the current version; passages name their own)\n\n"
            f"Question: {question}\n\nPassages:\n\n{passages}"
        )
        try:
            response = self._llm.call(
                LLMRequest[AskOutput](
                    prompt_name=PROMPT_NAME,
                    prompt_version=PROMPT_VERSION,
                    content=[TextPart(text=prompt_text)],
                    response_model=AskOutput,
                    created_by=created_by,
                    max_tokens=4000,
                )
            )
        except LLMCallError as exc:
            raise AskError(f"the model call failed: {exc}") from exc
        out = response.parsed
        citations: list[Citation] = []
        claims: list[AskClaim] = []
        index: dict[tuple[str, int, str], int] = {}
        cited_versions: set[int] = set()
        for claim in out.claims:
            if not 1 <= claim.passage <= len(hits):
                claims.append(AskClaim(statement=claim.statement, citations=[]))
                continue
            hit = hits[claim.passage - 1]
            document_id = str(hit.meta.get("document_id"))
            page_no = int(hit.meta.get("page_no") or 0)
            key = (document_id, page_no, claim.quote)
            if key not in index:
                citation = self._locate(
                    session,
                    len(citations) + 1,
                    document_id,
                    page_no,
                    claim.quote,
                    hit.meta.get("clause"),
                    hit.meta.get("version_no"),
                )
                citations.append(citation)
                index[key] = citation.n
            claims.append(AskClaim(statement=claim.statement, citations=[index[key]]))
            if hit.meta.get("version_no"):
                cited_versions.add(int(hit.meta["version_no"]))
        amended_versions = sorted(v for v in cited_versions if v > 1)
        note = out.amendment_note
        if amended_versions and not note:
            note = f"The answer cites version {amended_versions[-1]} (an amendment)."
        return AskAnswer(
            **base,
            source="machine",
            answered=out.answered,
            answer=out.answer,
            claims=claims,
            citations=citations,
            citations_resolved=sum(1 for c in citations if c.resolved),
            citations_total=len(citations),
            amendment_changed=out.amendment_changed or bool(amended_versions),
            amendment_note=note,
            retrieval=retrieval_mode,
            passages_read=len(hits),
            cost_usd=float(response.cost_usd),
            call_log_id=response.call_log_id,
        )

    def _locate(
        self,
        session: Session,
        n: int,
        document_id: str,
        page_no: int,
        quote: str,
        clause: str | None,
        version_no: int | None,
    ) -> Citation:
        page = session.scalar(
            select(Page).where(
                Page.document_id == document_id,
                Page.page_no == page_no,
                Page.tenant_id == self._tenant_id,
            )
        )
        filename = session.scalar(
            select(Document.filename).where(
                Document.id == document_id, Document.tenant_id == self._tenant_id
            )
        )
        if page is None:
            return Citation(
                n=n,
                document_id=document_id,
                filename=filename,
                page_no=page_no,
                clause=clause,
                version_no=version_no,
                quote=quote,
                resolved=False,
                reason="page not found",
            )
        located = resolve(
            quote,
            PageText(page.page_no, page.text, page.char_boxes, page.has_text_layer),
            threshold=self._settings.evidence_match_threshold,
        )
        if isinstance(located, Match):
            return Citation(
                n=n,
                document_id=document_id,
                filename=filename,
                page_no=page_no,
                clause=clause,
                version_no=version_no,
                quote=quote,
                resolved=True,
                char_start=located.char_start,
                char_end=located.char_end,
                bbox=located.bbox,
                score=located.score,
            )
        return Citation(
            n=n,
            document_id=document_id,
            filename=filename,
            page_no=page_no,
            clause=clause,
            version_no=version_no,
            quote=quote,
            resolved=False,
            score=located.best_score,
            reason=located.reason,
        )


def _passage(n: int, hit: Hit) -> str:
    meta = hit.meta
    where = f"{meta.get('filename') or meta.get('document_id')} p.{meta.get('page_no')}"
    if meta.get("clause"):
        where += f" clause {meta['clause']}"
    version = meta.get("version_no")
    kind = meta.get("version_kind") or ("original" if version == 1 else "")
    if version:
        where += f" — version {version}" + (f" ({kind})" if kind else "")
    return f"[{n}] {where}\n{hit.content}"


def _shown(value: Any) -> str:
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, Decimal):
        return f"{value:,}"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    if isinstance(value, list):
        return ", ".join(_shown(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_shown(v)}" for k, v in value.items())
    return str(value)


def _class_text(change_class: str) -> str:
    return {
        "value_changed": "changed this value",
        "date_moved": "moved this date",
        "clause_withdrawn": "withdrew this provision",
        "annexure_replaced": "replaced this annexure",
        "requirement_added": "added this requirement",
    }.get(change_class, "changed this")
