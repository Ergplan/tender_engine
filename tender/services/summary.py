"""The summary of a tender, written from its record in a second pass.

The summary is a reading of the record, not another reading of the document. Once the
extraction runs of a tender are validated, SummaryWriter gives the model the fields that
were extracted (each with its value and the version it comes from) and asks for eight
short paragraphs in which every sentence names the fields it rests on. The sentence
inherits the evidence of those fields: the candidate's evidence spans are copies of the
fields' located spans, numbered, and the text carries the numbers. No quote is located
anew, and the summary cannot say a value is missing while the field beside it has one.

What no single field holds (the plain description of what is procured, who the offtaker
is, where projects may be located) comes from the summary that was read from the pages
(prompt `summary`), whose sentences are offered as sources with the quotes they carried.

Model output still lands only in `candidate`: the summary is the candidate of its field
in a run of mode "record", validated and reviewed like any other.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.llm.client import LLMClient, LLMRequest, TextPart
from core.models import (
    Approval,
    Candidate,
    CanonicalFact,
    EvidenceSpan,
    ExtractionRun,
    Job,
    LLMCallLog,
)
from core.models.extraction import RECORD_MODE, REVIEWABLE_STATUSES
from core.schemas import SchemaRegistry
from core.services import jobs
from core.services.approve import ApprovalError, ApprovalService
from core.services.extract import LIVE_STATUSES, ExtractService
from core.services.review_state import EvidenceView, ReviewStateService
from tender.models import Tender
from tender.services.packs import Catalog
from tender.services.review import ReviewField, TenderReview, tender_review
from tender.services.tenders import JOB_KIND as AMENDMENT_JOB
from tender.services.tenders import OBJECT_TYPE, TenderService

log = logging.getLogger("tender.summary")
ACTOR = "summary"
JOB_KIND = "tender_summary"
SUMMARY_FIELD = "core.summary.plain_english_summary"
PROMPT_NAME, PROMPT_VERSION = "summary_record", "v1"
# The prompt of the summary that is read from the pages; its sentences are the fallback.
PAGE_PROMPT = "summary"
HEADINGS = (
    "What is procured",
    "Buyer and offtaker",
    "Location",
    "Timeline",
    "Eligibility",
    "Money at risk",
    "Tariff or payment",
    "Obligations and penalties",
)
# The topics for which a sentence of the page-read summary may stand in: what no single
# field holds. For every other topic the record is the only source.
NARRATIVE_HEADINGS = HEADINGS[:3]
MAX_VALUE_CHARS = 1500
# Between the model's own note on the summary and the list of what each number is the
# evidence of. The reviewer's screen shows the note; the list stays in the record.
SOURCES_HEADING = (
    "Written from the extracted fields; each number is the evidence of the field it follows: "
)
UNSOURCED_CONFIDENCE_CAP = 0.3
_MARKERS = re.compile(r"((?:\s*\[\d+\])+)")


class SummaryState(BaseModel):
    """Where the summary stands for the reviewer. It is written from the other fields, so
    it is decided after them."""

    # Other fields that still need a decision before the summary can be decided.
    waiting_for: int
    # The summary in review was written from the record as it stands, decisions included.
    current: bool
    # A new summary is queued or being written.
    being_written: bool


class SummaryError(ValueError):
    """The model's summary cannot be used as it came back. Worth another attempt."""


class SummarySentence(BaseModel):
    text: str
    sources: list[str]


class SummaryParagraph(BaseModel):
    heading: str
    sentences: list[SummarySentence]


class RecordSummary(BaseModel):
    paragraphs: list[SummaryParagraph]
    confidence: float
    rationale: str


@dataclass
class Source:
    """Something a sentence may rest on, with the located evidence it brings."""

    id: str
    line: str
    name: str
    spans: list[EvidenceView] = field(default_factory=list)
    # The tender version a field's value comes from; 1 for a narrative sentence.
    version_no: int = 1


def field_sources(
    review: TenderReview,
    section_labels: dict[str, str],
    reviewer_evidence: dict[str, list[EvidenceView]] | None = None,
    normalise: Callable[[str, Any], Any] | None = None,
) -> list[Source]:
    """One source per field of the record that has a value with located evidence: the
    entry a reviewer would decide (the latest version that states the field). Where a
    reviewer has approved or edited the field, the value is theirs; and where they gave
    their own evidence for an edit (`reviewer_evidence`, by approval id), the evidence is
    theirs too, not the quote the model gave for the value they replaced.

    `normalise(field_path, value)` puts a candidate's value in the form an approval would
    store (a date as 2026-03-30, a number as a number), so that approving a field as it
    stands does not change the record the summary was written from."""
    sources: list[Source] = []
    for item in review.fields:
        found = _field_value(item, reviewer_evidence or {})
        if item.field_path == SUMMARY_FIELD or found is None or item.keys:
            # A structured field repeats the numbers of the prose field beside it.
            continue
        value, spans, version, version_no = found
        if normalise is not None:
            value = normalise(item.field_path, value)
        unit = f" ({item.unit})" if item.unit else ""
        shown = _text(value)
        if item.value_type == "date" and isinstance(value, str):
            shown = written_date(value)
        if item.value_type == "money_inr" and isinstance(value, int | float):
            shown += f" (that is {rupees(float(value))})"
        sources.append(
            Source(
                id=f"F{len(sources) + 1}",
                line=(
                    f"{section_labels.get(item.section, item.section)} | {item.label}{unit} | "
                    f"{shown} | {version}"
                ),
                name=item.label,
                spans=spans,
                version_no=version_no,
            )
        )
    return sources


def _field_value(
    item: ReviewField, reviewer_evidence: dict[str, list[EvidenceView]]
) -> tuple[Any, list[EvidenceView], str, int] | None:
    if item.current is None:
        return None
    entry = item.entries[item.current]
    candidate, approval = entry.state.candidate, entry.state.approval
    if candidate is None or (approval is not None and approval.decision == "not_in_document"):
        return None
    decided = approval is not None and approval.decision in ("approved", "edited")
    value = approval.final_value if decided and approval is not None else candidate.value
    spans = [span for span in candidate.evidence if span.char_start is not None]
    if approval is not None and approval.decision == "edited":
        spans = reviewer_evidence.get(approval.id) or spans
    if value is None or not spans:
        return None
    version = (
        "original tender"
        if entry.version_no == 1
        else f"current value, from version {entry.version_no} ({entry.version_kind})"
    )
    return value, spans, version, entry.version_no


def written_date(value: str) -> str:
    """2026-03-30 as "30 March 2026"; anything that is not such a date as it is."""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{day.day} {day:%B} {day.year}"


def rupees(amount: float) -> str:
    """An amount the way Indian tenders write it: 13000000 is "INR 1.3 crore"."""
    for size, word in ((1e7, "crore"), (1e5, "lakh")):
        if abs(amount) >= size:
            return f"INR {amount / size:.4g} {word}"
    return f"INR {amount:,.10g}"


def _text(value: Any) -> str:
    if isinstance(value, list):
        text = "; ".join(
            ", ".join(f"{key}: {part}" for key, part in item.items())
            if isinstance(item, dict)
            else str(item)
            for item in value
        )
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value)
    text = " ".join(_MARKERS.sub("", text).split())
    return text if len(text) <= MAX_VALUE_CHARS else text[:MAX_VALUE_CHARS].rstrip() + " ..."


def narrative_sources(text: str, spans: list[EvidenceView]) -> list[Source]:
    """The sentences of a page-read summary under the narrative headings, each with the
    located quotes its markers name. `spans` carry their place in the model's list
    (`ordinal`). A sentence without a located quote is no source."""
    by_number = {span.ordinal: span for span in spans if span.char_start is not None}
    sources: list[Source] = []
    for block in re.split(r"\n\s*\n", text):
        heading, sep, body = block.strip().partition(":")
        if not sep or heading.strip() not in NARRATIVE_HEADINGS:
            continue
        pieces = _MARKERS.split(body)
        # Text and its markers alternate: [text, markers, text, markers, ..., tail].
        for sentence, markers in zip(pieces[0::2], pieces[1::2], strict=False):
            words = " ".join(sentence.strip(" .;").split())
            quoted = [
                by_number[number]
                for number in (int(n) for n in re.findall(r"\d+", markers))
                if number in by_number
            ]
            if words and quoted:
                sources.append(
                    Source(
                        id=f"N{len(sources) + 1}",
                        line=f"{heading.strip()} | {words}.",
                        name=f"page summary, {heading.strip().lower()}",
                        spans=quoted,
                    )
                )
    return sources


def compose(
    summary: RecordSummary, sources: dict[str, Source]
) -> tuple[str, list[dict[str, Any]], list[tuple[str, list[int]]], list[str]]:
    """The summary as stored: the text with a number after each sentence, the evidence
    spans those numbers stand for (copies of the sources' spans, numbered in order of
    first use), which numbers each source brought, and the ids the model named that do
    not exist. Raises SummaryError when the paragraphs are not the eight asked for or no
    sentence has evidence."""
    headings = tuple(paragraph.heading.strip().rstrip(":") for paragraph in summary.paragraphs)
    if headings != HEADINGS:
        raise SummaryError(f"expected the headings {list(HEADINGS)}, got {list(headings)}")
    numbers: dict[tuple[str, int, int | None, int | None], int] = {}
    spans: list[dict[str, Any]] = []
    names: dict[int, list[str]] = {}
    used: dict[str, list[int]] = {}
    unknown: list[str] = []
    blocks = []
    for paragraph, heading in zip(summary.paragraphs, HEADINGS, strict=True):
        sentences = []
        for sentence in paragraph.sentences:
            words = " ".join(_MARKERS.sub("", sentence.text).split())
            if not words:
                continue
            marks: list[int] = []
            for source_id in dict.fromkeys(sentence.sources):
                source = sources.get(source_id.strip())
                if source is None:
                    unknown.append(source_id)
                    continue
                for span in source.spans:
                    key = (span.document_id, span.page_no, span.char_start, span.char_end)
                    if key not in numbers:
                        numbers[key] = len(numbers) + 1
                        spans.append(_inherited(span, numbers[key]))
                    if source.name not in names.setdefault(numbers[key], []):
                        names[numbers[key]].append(source.name)
                    if numbers[key] not in marks:
                        marks.append(numbers[key])
                    if numbers[key] not in used.setdefault(source.id, []):
                        used[source.id].append(numbers[key])
            sentences.append(words + ("" if not marks else " " + "".join(f"[{n}]" for n in marks)))
        if not sentences:
            raise SummaryError(f"the paragraph {heading!r} is empty")
        blocks.append(f"{heading}: " + " ".join(sentences))
    if not spans:
        raise SummaryError("no sentence of the summary names a source")
    for item in spans:
        # What the passage was inherited from: one field, or the several that share it.
        item["source"] = "; ".join(names[item["ordinal"]])[:300]
    drawn = [(sources[source_id].name, marks) for source_id, marks in used.items()]
    return "\n\n".join(blocks), spans, drawn, unknown


def _inherited(span: EvidenceView, ordinal: int) -> dict[str, Any]:
    return {
        "document_id": span.document_id,
        "page_no": span.page_no,
        "stated_page_no": span.page_no,
        "bbox": span.bbox,
        "char_start": span.char_start,
        "char_end": span.char_end,
        "quote": span.quote,
        "resolution": span.resolution,
        "match_score": span.match_score,
        "match_method": span.match_method,
        "ordinal": ordinal,
    }


class SummaryWriter:
    def __init__(
        self,
        llm: LLMClient,
        catalog: Catalog,
        extract: ExtractService,
        tenders: TenderService,
        review_state: ReviewStateService,
        schemas: SchemaRegistry,
        tenant_id: str,
    ) -> None:
        self._llm = llm
        self._catalog = catalog
        self._extract = extract
        self._tenders = tenders
        self._review_state = review_state
        self._schemas = schemas
        self._tenant_id = tenant_id

    def after_validation(self, session: Session, extraction_run_id: str) -> None:
        """Called by the worker when a run has been validated: once no extraction of the
        tender is still under way, queue the summary. A record run does not queue one."""
        run = session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.id == extraction_run_id, ExtractionRun.tenant_id == self._tenant_id
            )
        )
        if run is None or run.object_type != OBJECT_TYPE or run.mode == RECORD_MODE:
            return
        self.queue_if_settled(session, run.object_id, created_by=ACTOR, is_fixture=run.is_fixture)

    def queue_if_settled(
        self,
        session: Session,
        tender_id: str,
        *,
        created_by: str,
        is_fixture: bool = False,
        force: bool = False,
    ) -> bool:
        """Queue the summary of the tender unless an extraction or an amendment map of it
        is still queued or running, or its summary is queued already."""
        under_way = session.scalar(
            select(ExtractionRun.id)
            .where(
                ExtractionRun.tenant_id == self._tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.object_id == tender_id,
                ExtractionRun.mode != RECORD_MODE,
                ExtractionRun.status.in_(("queued", "running", "extracted")),
            )
            .limit(1)
        )
        waiting = session.scalar(
            select(Job.id)
            .where(
                Job.tenant_id == self._tenant_id,
                Job.kind.in_((AMENDMENT_JOB, JOB_KIND)),
                Job.status.in_(("queued", "running")),
                Job.payload["tender_id"].astext == tender_id,
            )
            .limit(1)
        )
        if under_way is not None or waiting is not None:
            return False
        jobs.enqueue(
            session,
            tenant_id=self._tenant_id,
            kind=JOB_KIND,
            payload={"tender_id": tender_id, "is_fixture": is_fixture, "force": force},
            created_by=created_by,
        )
        session.commit()
        return True

    def _prepare(
        self,
        session: Session,
        tender: Tender,
        review: TenderReview | None = None,
        *,
        is_fixture: bool = False,
    ) -> tuple[LLMRequest[RecordSummary], list[Source], TenderReview] | None:
        """The record as the model would be given it now, or None when it holds no field
        to summarise. No call is made."""
        compiled = self._catalog.get(tender.tender_type)
        review = review or tender_review(
            session, self._catalog, self._tenders, self._review_state, tender
        )
        labels = {section.name: section.label for section in compiled.sections}
        fields = {item.path: item for item in compiled.schema.fields}

        def normalise(path: str, value: Any) -> Any:
            try:
                return self._schemas.value_types.coerce(value, fields[path])
            except ValueError:
                return value

        sources = field_sources(review, labels, self._reviewer_evidence(session, tender), normalise)
        page_summary = self._page_summary(session, tender)
        if page_summary is not None:
            sources += narrative_sources(*page_summary)
        if not any(source.id.startswith("F") for source in sources) or not review.versions:
            return None
        request = LLMRequest[RecordSummary](
            prompt_name=PROMPT_NAME,
            prompt_version=PROMPT_VERSION,
            content=[TextPart(text=_record(tender, sources))],
            response_model=RecordSummary,
            created_by=ACTOR,
            is_fixture=is_fixture,
        )
        return request, sources, review

    def review(self, session: Session, tender: Tender) -> TenderReview:
        return tender_review(session, self._catalog, self._tenders, self._review_state, tender)

    def state(
        self, session: Session, tender: Tender, review: TenderReview | None = None
    ) -> "SummaryState":
        """Where the summary stands for a reviewer: how many other fields are still to be
        decided, whether the summary in review was written from the record as it stands
        now (their decisions included), and whether a new one is being written."""
        review = review or tender_review(
            session, self._catalog, self._tenders, self._review_state, tender
        )
        waiting_for = sum(
            1
            for item in review.fields
            if item.field_path != SUMMARY_FIELD and item.current is not None and not item.decided
        )
        prepared = self._prepare(session, tender, review)
        current = prepared is None or self._already_written(
            session, tender, self._llm.input_hash(prepared[0])
        )
        being_written = (
            session.scalar(
                select(Job.id)
                .where(
                    Job.tenant_id == self._tenant_id,
                    Job.kind == JOB_KIND,
                    Job.status.in_(("queued", "running")),
                    Job.payload["tender_id"].astext == tender.id,
                )
                .limit(1)
            )
            is not None
            or session.scalar(
                select(ExtractionRun.id)
                .where(
                    ExtractionRun.tenant_id == self._tenant_id,
                    ExtractionRun.object_type == OBJECT_TYPE,
                    ExtractionRun.object_id == tender.id,
                    ExtractionRun.mode == RECORD_MODE,
                    ExtractionRun.status.in_(("running", "extracted")),
                )
                .limit(1)
            )
            is not None
        )
        return SummaryState(waiting_for=waiting_for, current=current, being_written=being_written)

    def write(
        self, session: Session, tender_id: str, *, is_fixture: bool = False, force: bool = False
    ) -> ExtractionRun | None:
        """Write the summary of the tender from its record, as the candidate of a new
        record run on the tender's latest version, and queue its validation. Returns None
        when the record has nothing to summarise, or is the one the live summary was
        written from (unless `force`). Raises LLMCallError or SummaryError, storing nothing,
        when the model gives no usable summary."""
        tender = self._tenders.get(session, tender_id)
        prepared = self._prepare(session, tender, is_fixture=is_fixture)
        if prepared is None:
            return None
        request, sources, review = prepared
        compiled = self._catalog.get(tender.tender_type)
        if not force and self._already_written(session, tender, self._llm.input_hash(request)):
            return None

        # Nothing is stored unless the summary can be used: a call that fails, or an answer
        # that is not the eight paragraphs with their sources, leaves the earlier summary
        # in review and no run behind (the call itself is in llm_call_log).
        started = datetime.now(UTC)
        response = self._llm.call(request)
        text, spans, drawn, unknown = compose(
            response.parsed, {source.id: source for source in sources}
        )
        run = ExtractionRun(
            tenant_id=self._tenant_id,
            created_by=ACTOR,
            # The first document of the tender: the one a reviewer's own evidence for the
            # summary is looked up in.
            document_id=review.versions[0].documents[0].document_id,
            object_type=OBJECT_TYPE,
            object_id=tender.id,
            # The latest version the record draws on: a version that has not been
            # extracted yet has nothing in it.
            object_version=max(source.version_no for source in sources),
            schema_name=compiled.schema.name,
            schema_version=compiled.schema.version,
            prompt_version=PROMPT_VERSION,
            groups=[compiled.schema.field(SUMMARY_FIELD).group],
            model=self._llm.model,
            status="running",
            is_fixture=is_fixture,
            mode=RECORD_MODE,
            started_at=started,
        )
        session.add(run)
        session.flush()
        rationale = (
            " ".join(response.parsed.rationale.split())
            + "\n\n"
            + SOURCES_HEADING
            + "; ".join(f"{_range(marks)} {name}" for name, marks in drawn)
            + "."
        )
        confidence = response.parsed.confidence
        if unknown:
            rationale += f" The model named sources that do not exist: {', '.join(unknown)}."
            confidence = min(confidence, UNSOURCED_CONFIDENCE_CAP)
        candidate = self._extract.record_candidate(
            session,
            run,
            SUMMARY_FIELD,
            value=text,
            confidence=confidence,
            rationale=rationale,
            spans=spans,
            call_log_id=response.call_log_id,
            prompt_name=PROMPT_NAME,
            prompt_version=PROMPT_VERSION,
        )
        # One summary per tender: the earlier ones, read from pages or written from an
        # earlier state of the record, leave review.
        for earlier in session.scalars(
            select(Candidate)
            .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
            .where(
                Candidate.tenant_id == self._tenant_id,
                ExtractionRun.tenant_id == self._tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.object_id == tender.id,
                Candidate.field_path == SUMMARY_FIELD,
                Candidate.id != candidate.id,
                Candidate.status.in_(LIVE_STATUSES),
            )
        ):
            self._extract.supersede(session, earlier, run)
        run.token_in = response.tokens_in + response.cache_read_tokens + response.cache_write_tokens
        run.token_cached = response.cache_read_tokens
        run.token_out = response.tokens_out
        run.cost_usd = response.cost_usd.quantize(Decimal("0.0001"))
        run.status = "extracted"
        jobs.enqueue(
            session,
            tenant_id=self._tenant_id,
            kind="validate",
            payload={"extraction_run_id": run.id},
            created_by=ACTOR,
        )
        session.commit()
        return run

    def _reviewer_evidence(self, session: Session, tender: Tender) -> dict[str, list[EvidenceView]]:
        """By approval id, the evidence reviewers gave with their edits: the page and the
        words that state the corrected value, located when the edit was stored."""
        found: dict[str, list[EvidenceView]] = {}
        for fact in session.scalars(
            select(CanonicalFact).where(
                CanonicalFact.tenant_id == self._tenant_id,
                CanonicalFact.object_type == OBJECT_TYPE,
                CanonicalFact.object_id == tender.id,
                CanonicalFact.is_current.is_(True),
            )
        ):
            spans = [
                EvidenceView(
                    id=f"{fact.approval_id}-{place}",
                    document_id=item["document_id"],
                    page_no=item["page_no"],
                    bbox=item.get("bbox"),
                    char_start=item.get("char_start"),
                    char_end=item.get("char_end"),
                    quote=item.get("quote", ""),
                    resolution="reviewer",
                    match_score=None,
                    match_method=None,
                )
                for place, item in enumerate(fact.evidence)
                if item.get("kind") == "reviewer_span" and item.get("char_start") is not None
            ]
            if spans:
                found[fact.approval_id] = spans
        return found

    def _page_summary(
        self, session: Session, tender: Tender
    ) -> tuple[str, list[EvidenceView]] | None:
        """The latest summary of the tender that was read from pages, with its quotes:
        of the latest version that has one, the one with most quotes. It may have left
        review already (superseded by an earlier summary from the record)."""
        rows = session.execute(
            select(Candidate, ExtractionRun.object_version)
            .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
            .where(
                Candidate.tenant_id == self._tenant_id,
                ExtractionRun.tenant_id == self._tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.object_id == tender.id,
                ExtractionRun.mode != RECORD_MODE,
                Candidate.field_path == SUMMARY_FIELD,
                Candidate.prompt_name == PAGE_PROMPT,
                Candidate.value.is_not(None),
                Candidate.status.in_((*REVIEWABLE_STATUSES, "superseded")),
            )
        ).all()
        best: tuple[tuple[int, Any, int], Candidate, list[EvidenceView]] | None = None
        for candidate, version_no in rows:
            if not isinstance(candidate.value, str):
                continue
            spans = [
                EvidenceView.model_validate(span, from_attributes=True)
                for span in session.scalars(
                    select(EvidenceSpan).where(
                        EvidenceSpan.candidate_id == candidate.id,
                        EvidenceSpan.tenant_id == self._tenant_id,
                    )
                )
            ]
            # The newest reading of a document wins over an older one; then the richer.
            key = (version_no, candidate.created_at, len(spans))
            if best is None or key > best[0]:
                best = (key, candidate, spans)
        return None if best is None else (str(best[1].value), best[2])

    def _already_written(self, session: Session, tender: Tender, input_hash: str) -> bool:
        """Whether the summary in review was written from exactly this record."""
        return (
            session.scalar(
                select(Candidate.id)
                .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
                .join(LLMCallLog, Candidate.llm_call_log_id == LLMCallLog.id)
                .where(
                    Candidate.tenant_id == self._tenant_id,
                    ExtractionRun.tenant_id == self._tenant_id,
                    LLMCallLog.tenant_id == self._tenant_id,
                    ExtractionRun.object_type == OBJECT_TYPE,
                    ExtractionRun.object_id == tender.id,
                    ExtractionRun.mode == RECORD_MODE,
                    Candidate.field_path == SUMMARY_FIELD,
                    Candidate.status.in_(("raw", *REVIEWABLE_STATUSES)),
                    LLMCallLog.input_hash == input_hash,
                )
                .limit(1)
            )
            is not None
        )


def _record(tender: Tender, sources: list[Source]) -> str:
    fields = [source for source in sources if source.id.startswith("F")]
    narrative = [source for source in sources if source.id.startswith("N")]
    lines = [
        f"Tender: {tender.title}",
        f"Type: {tender.tender_type}. Issuing agency as registered: {tender.issuing_agency}.",
        "",
        "Fields of the record (id | section | field | value | where the value comes from):",
        *(f"{source.id} | {source.line}" for source in fields),
    ]
    if narrative:
        lines += [
            "",
            "Sentences of the page-read summary, for what no field holds (id | topic | sentence):",
            *(f"{source.id} | {source.line}" for source in narrative),
        ]
    return "\n".join(lines)


def _range(marks: list[int]) -> str:
    return "".join(f"[{number}]" for number in marks)


class SummaryGuard:
    """The rule on decisions that keeps a reviewer from approving a contradiction: the
    summary is a reading of the other fields, so

    - it cannot be approved, edited or set aside while another field is undecided;
    - it cannot be approved while it is not the reading of the record as it stands (a new
      one is written as soon as the last other field is decided, if a decision changed
      the record);
    - a decision on another field that changes the record withdraws a decision already
      made on the summary (it is flagged, with the reason)."""

    def __init__(self, writer: SummaryWriter, tenders: TenderService) -> None:
        self._writer = writer
        self._tenders = tenders

    def before(
        self, session: Session, candidate: Candidate, run: ExtractionRun, decision: str
    ) -> None:
        if (
            run.object_type != OBJECT_TYPE
            or candidate.field_path != SUMMARY_FIELD
            or decision not in ("approved", "edited", "not_in_document")
        ):
            return
        state = self._writer.state(session, self._tenders.get(session, run.object_id))
        if state.waiting_for:
            raise ApprovalError(
                f"decide the other fields first ({state.waiting_for} to go): the summary is "
                "written from them"
            )
        if decision == "approved" and not state.current:
            raise ApprovalError(
                "the summary is being written again from your decisions; it will be ready "
                "in about a minute"
            )

    def after(
        self, session: Session, service: ApprovalService, approval: Approval, run: ExtractionRun
    ) -> None:
        if run.object_type != OBJECT_TYPE or approval.field_path == SUMMARY_FIELD:
            return
        tender = self._tenders.get(session, run.object_id)
        review = self._writer.review(session, tender)
        state = self._writer.state(session, tender, review)
        if state.current:
            return
        summary = next((f for f in review.fields if f.field_path == SUMMARY_FIELD), None)
        entry = (
            summary.entries[summary.current] if summary and summary.current is not None else None
        )
        decided = entry.state.approval if entry else None
        if entry and entry.state.candidate and decided and decided.decision != "flagged":
            # The summary was decided on a record that has since changed.
            service.approve(
                session,
                candidate_id=entry.state.candidate.id,
                decision="flagged",
                reviewer=approval.reviewer,
                note=f"{approval.field_path} was decided again after the summary; the summary "
                "is written again and needs a new decision",
            )
        if state.waiting_for == 0:
            self._writer.queue_if_settled(session, tender.id, created_by=approval.reviewer)


def job_handlers(writer: SummaryWriter) -> dict[str, Callable[[Session, dict[str, Any]], None]]:
    def tender_summary(session: Session, payload: dict[str, Any]) -> None:
        writer.write(
            session,
            payload["tender_id"],
            is_fixture=payload.get("is_fixture", False),
            force=payload.get("force", False),
        )

    return {JOB_KIND: tender_summary}
