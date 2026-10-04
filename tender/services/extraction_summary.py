"""EXTRACTION-SUMMARY.md: what extraction returned for every tender, before any review.

Two numbers are reported separately, per tender and per tender type:
evidence-location rate = values with located evidence / values returned (target 95%), and
answer rate = fields with a value / fields in the schema (reported, not targeted).
A field counts once per tender: its value is the best live candidate of the latest
version that gives one.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.models import Document, ExtractionRun, LLMCallLog
from core.services.review_state import FieldState, ReviewStateService
from tender.models import Tender
from tender.services.packs import Catalog
from tender.services.tenders import OBJECT_TYPE, TenderService

TARGET = 0.95


@dataclass
class FieldResult:
    path: str
    section: str
    answered: bool
    located: bool
    failing: bool
    version_no: int | None


@dataclass
class TenderResult:
    tender: Tender
    versions: int
    documents: int
    pages: int
    runs: int
    unfinished_runs: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    fields: list[FieldResult] = field(default_factory=list)

    @property
    def answered(self) -> int:
        return sum(1 for f in self.fields if f.answered)

    @property
    def located(self) -> int:
        return sum(1 for f in self.fields if f.located)

    @property
    def failing(self) -> int:
        return sum(1 for f in self.fields if f.failing)


def _located(state: FieldState) -> bool:
    return state.candidate is not None and any(
        span.char_start is not None for span in state.candidate.evidence
    )


def collect(
    session: Session, catalog: Catalog, tenders: TenderService, review: ReviewStateService
) -> list[TenderResult]:
    results = []
    for tender in tenders.all(session):
        compiled = catalog.get(tender.tender_type)
        entries = tenders.versions(session, tender)
        runs = list(
            session.scalars(
                select(ExtractionRun).where(
                    ExtractionRun.tenant_id == tender.tenant_id,
                    ExtractionRun.object_type == OBJECT_TYPE,
                    ExtractionRun.object_id == tender.id,
                )
            )
        )
        documents: dict[str, Document] = {
            document.id: document for entry in entries for _, document in entry.documents
        }
        result = TenderResult(
            tender=tender,
            versions=len(entries),
            documents=len(documents),
            pages=sum(document.page_count or 0 for document in documents.values()),
            runs=len(runs),
            unfinished_runs=sum(1 for run in runs if run.status != "validated"),
            tokens_in=sum(run.token_in for run in runs),
            tokens_out=sum(run.token_out for run in runs),
            cost_usd=sum((run.cost_usd for run in runs), Decimal(0)),
        )
        chosen: dict[str, tuple[int, FieldState]] = {}
        for entry in entries:
            number = entry.version.version_no
            state = review.for_object(session, OBJECT_TYPE, tender.id, number)
            for item in state.fields:
                valued = item.candidate is not None and item.candidate.value is not None
                # A later version replaces what an earlier one says only where it has a value.
                if valued or item.field_path not in chosen:
                    chosen[item.field_path] = (number, item)
        for spec in compiled.fields:
            picked = chosen.get(spec.path)
            number, shown = picked if picked else (0, None)
            candidate = shown.candidate if shown else None
            answered = candidate is not None and candidate.value is not None
            result.fields.append(
                FieldResult(
                    path=spec.path,
                    section=spec.section,
                    answered=answered,
                    located=answered and shown is not None and _located(shown),
                    failing=candidate is not None and candidate.status == "needs_review",
                    version_no=number if answered else None,
                )
            )
        results.append(result)
    return results


def _rate(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


def _money(value: Decimal | float) -> str:
    return f"{value:.2f}"


def render(
    results: list[TenderResult], *, model: str, total_cost_usd: float, calls: int, now: datetime
) -> str:
    lines = [
        "# Extraction summary",
        "",
        f"Generated {now:%Y-%m-%d %H:%M} UTC by `python -m scripts.ingest_tenders summary` "
        "(the same content is served by `GET /api/v1/reports/extraction-summary`). "
        f"Model `{model}`. Candidates only: nothing here has been reviewed.",
        "",
        "- **Evidence-location rate** = values with located evidence / values returned "
        "(target 95%).",
        "- **Answer rate** = fields with a value / fields in the schema (reported, not "
        "targeted; a field the documents do not state returning no value is a correct answer).",
        "- A field counts once per tender: the best live candidate of the latest version "
        "that gives a value.",
        "- **Failing validation** = fields whose shown candidate is `needs_review` (a rule "
        "failed, or a required field has no value).",
        "",
        "## Per tender",
        "",
        "| Type | Tender | Versions | Documents | Pages | Fields | With a value | Located | "
        "Evidence-location rate | Answer rate | Failing validation | Tokens in | Tokens out | "
        "Cost USD |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        name = r.tender.slug or r.tender.title[:60]
        note = f" ({r.unfinished_runs} of {r.runs} runs not finished)" if r.unfinished_runs else ""
        if not r.runs:
            note = " (not extracted)"
        lines.append(
            f"| {r.tender.tender_type} | {name}{note} | {r.versions} | {r.documents} | "
            f"{r.pages} | {len(r.fields)} | {r.answered} | {r.located} | "
            f"{_rate(r.located, r.answered)} | {_rate(r.answered, len(r.fields))} | "
            f"{r.failing} | {r.tokens_in:,} | {r.tokens_out:,} | {_money(r.cost_usd)} |"
        )
    # Rates over the whole set are only meaningful for tenders whose runs all finished.
    complete = [r for r in results if r.runs and not r.unfinished_runs]
    fields_total = sum(len(r.fields) for r in complete)
    answered = sum(r.answered for r in complete)
    located = sum(r.located for r in complete)
    run_cost = sum((r.cost_usd for r in results), Decimal(0))
    lines += [
        f"| **fully extracted** | {len(complete)} of {len(results)} tenders | "
        f"{sum(r.versions for r in complete)} | "
        f"{sum(r.documents for r in complete)} | {sum(r.pages for r in complete)} | "
        f"{fields_total} | {answered} | {located} | {_rate(located, answered)} | "
        f"{_rate(answered, fields_total)} | {sum(r.failing for r in complete)} | "
        f"{sum(r.tokens_in for r in results):,} | {sum(r.tokens_out for r in results):,} | "
        f"{_money(run_cost)} |",
        "",
        f"**{len(complete)} of {len(results)} tenders are fully extracted.** The last row and "
        "the tables below count only those; tokens and cost count every finished run. A run "
        "that is not finished has no token total yet.",
        "",
        f"Cost of all model calls in the database, including section maps and runs that were "
        f"repeated: **USD {_money(total_cost_usd)}** over {calls} calls. The table counts every "
        "finished extraction run of a tender, including repeated ones.",
        "",
        "## Per tender type",
        "",
        "| Type | Tenders | Fields | With a value | Located | Evidence-location rate | "
        "Answer rate |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    by_type: dict[str, list[TenderResult]] = defaultdict(list)
    for r in complete:
        by_type[r.tender.tender_type].append(r)
    for tender_type, group in sorted(by_type.items()):
        total = sum(len(r.fields) for r in group)
        a, loc = sum(r.answered for r in group), sum(r.located for r in group)
        lines.append(
            f"| {tender_type} | {len(group)} | {total} | {a} | {loc} | {_rate(loc, a)} | "
            f"{_rate(a, total)} |"
        )
    lines += [
        "",
        "## Per section, all tenders",
        "",
        "| Section | Fields | With a value | Located | Evidence-location rate | Answer rate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    sections: dict[str, list[FieldResult]] = defaultdict(list)
    for r in complete:
        for item in r.fields:
            sections[item.section].append(item)
    for section, items in sections.items():
        a, loc = sum(f.answered for f in items), sum(f.located for f in items)
        lines.append(
            f"| {section} | {len(items)} | {a} | {loc} | {_rate(loc, a)} | {_rate(a, len(items))} |"
        )
    lines += ["", "## Fields with an evidence-location rate under 95%, by tender type", ""]
    rows = []
    for tender_type, group in sorted(by_type.items()):
        per_field: dict[str, list[tuple[FieldResult, str]]] = defaultdict(list)
        for r in group:
            for item in r.fields:
                if item.answered:
                    per_field[item.path].append((item, r.tender.slug or r.tender.id))
        for path, returned in per_field.items():
            loc = sum(1 for result, _ in returned if result.located)
            if loc / len(returned) < TARGET:
                missing = ", ".join(slug for result, slug in returned if not result.located)
                rows.append(
                    f"| {tender_type} | `{path}` | {len(returned)} | {loc} | "
                    f"{_rate(loc, len(returned))} | {missing} |"
                )
    if rows:
        lines += [
            "| Type | Field | Values returned | Located | Rate | Tenders where not located |",
            "| --- | --- | --- | --- | --- | --- |",
            *rows,
        ]
    else:
        lines.append("None: every value returned has located evidence.")
    return "\n".join(lines) + "\n"


class TenderSummary(BaseModel):
    tender_id: str
    slug: str | None
    tender_type: str
    title: str
    versions: int
    documents: int
    pages: int
    fields: int
    with_value: int
    located: int
    failing_validation: int
    runs: int
    unfinished_runs: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal


class ExtractionSummary(BaseModel):
    """The extraction summary as data, and the same content as the Markdown report."""

    generated_at: datetime
    model: str
    calls: int
    total_cost_usd: float
    tenders: list[TenderSummary]
    markdown: str


def build(
    session: Session,
    catalog: Catalog,
    tenders: TenderService,
    review: ReviewStateService,
    settings: Settings,
) -> ExtractionSummary:
    results = collect(session, catalog, tenders, review)
    tokens_in, tokens_out, calls = session.execute(
        select(
            func.coalesce(func.sum(LLMCallLog.tokens_in), 0),
            func.coalesce(func.sum(LLMCallLog.tokens_out), 0),
            func.count(),
        ).where(LLMCallLog.tenant_id == settings.tenant_id, LLMCallLog.is_fixture.is_(False))
    ).one()
    total = float(
        tokens_in / 1e6 * settings.llm_price_in_per_mtok
        + tokens_out / 1e6 * settings.llm_price_out_per_mtok
    )
    now = datetime.now(UTC)
    return ExtractionSummary(
        generated_at=now,
        model=settings.anthropic_model,
        calls=int(calls),
        total_cost_usd=round(total, 2),
        tenders=[
            TenderSummary(
                tender_id=r.tender.id,
                slug=r.tender.slug,
                tender_type=r.tender.tender_type,
                title=r.tender.title,
                versions=r.versions,
                documents=r.documents,
                pages=r.pages,
                fields=len(r.fields),
                with_value=r.answered,
                located=r.located,
                failing_validation=r.failing,
                runs=r.runs,
                unfinished_runs=r.unfinished_runs,
                tokens_in=r.tokens_in,
                tokens_out=r.tokens_out,
                cost_usd=r.cost_usd,
            )
            for r in results
        ],
        markdown=render(
            results,
            model=settings.anthropic_model,
            total_cost_usd=total,
            calls=int(calls),
            now=now,
        ),
    )
