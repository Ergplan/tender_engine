"""Three-way comparison (Stage 5B): human (gold), engine (candidate), agent (agent_finding)
per field, for every gold tender.

  python -m evals.threeway            compare, write THREEWAY-REPORT.md and the emphasis file
  python -m evals.threeway --only slug,slug

Each gold field with a decision falls into one of six classes:

  all_agree               engine and agent both match the reviewer (a value, or an abstention
                          where the reviewer marked the field absent)
  engine_right_agent_wrong
  agent_right_engine_wrong
  both_wrong_same_way     both miss, and their values match each other (the schema or the
                          document is the likelier problem: an ambiguous clause, a table
                          against a clause)
  both_wrong_differently  both miss, each in its own way (a candidate for a mandatory
                          second pass in production)
  both_abstained          the reviewer found a value, neither model did

Long-text fields are left to human judgement and reported apart (`needs_judgement`), as
the scorer does. "Right" and "wrong" are the scorer's own rules (`evals.runner.score_field`):
the same match rules for both models, so the comparison is fair to neither.

The production confidence rule (written into `review-emphasis-<tenant>.json` beside the
results and into the report): a field is "auto-surface with low-review" only when
human-engine-agent agreement is at least 97% over at least 15 gold instances; otherwise it
stays full review. That changes the reviewer screen's default emphasis and nothing in the
truth pipeline: no auto-approval exists.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.models import AgentFinding, AgentRun
from core.schemas import SchemaRegistry
from core.services.review_state import ReviewStateService
from evals.gold import GoldRecord, load_all
from evals.runner import (
    RESULTS_ROOT,
    CandidateUnderTest,
    FieldScore,
    candidates_in_review,
    match_record,
    match_scalar,
    normalise_text,
    score_field,
)
from tender.services.packs import Catalog
from tender.services.summary import SUMMARY_FIELD

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "docs" / "reports" / "THREEWAY-REPORT.md"
STANDING = ("accepted", "not_found", "withdrawn")
AGREEMENT_MIN = 0.97
INSTANCES_MIN = 15
Agreement = Literal[
    "all_agree",
    "engine_right_agent_wrong",
    "agent_right_engine_wrong",
    "both_wrong_same_way",
    "both_wrong_differently",
    "both_abstained",
    "needs_judgement",
]
CLASSES: tuple[Agreement, ...] = (
    "all_agree",
    "engine_right_agent_wrong",
    "agent_right_engine_wrong",
    "both_wrong_same_way",
    "both_wrong_differently",
    "both_abstained",
    "needs_judgement",
)


class ThreeWay(BaseModel):
    """One gold field seen three ways."""

    slug: str
    tender_type: str
    issuing_agency: str
    field_path: str
    section: str
    value_type: str
    required: bool
    agreement: Agreement
    gold_value: Any
    engine_value: Any
    agent_value: Any
    engine_outcome: str
    agent_outcome: str
    engine_evidence_ok: bool | None = None
    agent_evidence_ok: bool | None = None
    agent_run_id: str | None = None
    agent_status: str | None = None


class Emphasis(BaseModel):
    field_path: str
    instances: int
    agreement: float
    low_review: bool


class ThreeWaySummary(BaseModel):
    tenant_id: str
    made_at: str
    tenders: int
    tenders_without_agent_pass: list[str]
    fields: int
    by_class: dict[str, int]
    by_type: dict[str, dict[str, int]]
    by_agency: dict[str, dict[str, int]]
    by_field: dict[str, dict[str, int]]
    emphasis: list[Emphasis]


def agent_findings(
    session: Session, tenant_id: str, record: GoldRecord
) -> tuple[AgentRun | None, dict[str, CandidateUnderTest]]:
    """The standing findings of the latest finished agent pass over the tender at the
    version the gold record was reviewed at (a pass over a later version read documents
    the reviewer did not see)."""
    run = session.scalar(
        select(AgentRun)
        .where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.object_type == "tender",
            AgentRun.object_id == record.tender_id,
            AgentRun.object_version == record.reviewed_version,
            AgentRun.status.in_(("done", "stopped")),
        )
        .order_by(AgentRun.finished_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    if run is None:
        return None, {}
    found: dict[str, CandidateUnderTest] = {}
    for finding in session.scalars(
        select(AgentFinding)
        .where(
            AgentFinding.agent_run_id == run.id,
            AgentFinding.tenant_id == tenant_id,
            AgentFinding.status.in_(STANDING),
        )
        .order_by(AgentFinding.ordinal)
    ):
        pages = sorted(
            {
                int(span["page_no"])
                for span in finding.evidence
                if span.get("document_id") == _document_of(record, run, span)
            }
        )
        found[finding.field_path] = CandidateUnderTest(
            id=finding.id,
            value=finding.value,
            confidence=finding.confidence,
            pages=pages,
            prompt_name=run.prompt_name,
            prompt_version=run.prompt_version,
        )
    return run, found


def _document_of(record: GoldRecord, run: AgentRun, span: dict[str, Any]) -> str | None:
    """The gold record's pages are pages of the document the field was read from; an
    agent quote counts for the page check only when it cites a document of the pass."""
    numbers = {int(d["number"]): d["document_id"] for d in run.documents}
    return numbers.get(int(span.get("document_no") or 0))


def _same_miss(
    definition: Any, registry: SchemaRegistry, value_type: str, engine: Any, agent: Any
) -> bool:
    """Whether two wrong readings are the same reading."""
    if engine is None or agent is None:
        return engine is None and agent is None
    try:
        e = registry.value_types.coerce(engine, definition)
        a = registry.value_types.coerce(agent, definition)
    except ValueError:
        return normalise_text(engine) == normalise_text(agent)
    if definition.keys:
        outcome, _ = match_record(definition.keys, registry, e, a)
        return outcome == "correct"
    kind = registry.value_types.get(value_type).json_kind
    outcome, _ = match_scalar(value_type, kind, e, a)
    return outcome in ("correct", "needs_judgement")


def classify(
    engine: FieldScore, agent: FieldScore, definition: Any, registry: SchemaRegistry
) -> Agreement:
    if not engine.counted or not agent.counted:
        return "needs_judgement"
    if engine.correct and agent.correct:
        return "all_agree"
    if engine.correct:
        return "engine_right_agent_wrong"
    if agent.correct:
        return "agent_right_engine_wrong"
    if engine.candidate_value is None and agent.candidate_value is None:
        return "both_abstained"
    if _same_miss(
        definition, registry, engine.value_type, engine.candidate_value, agent.candidate_value
    ):
        return "both_wrong_same_way"
    return "both_wrong_differently"


def compare_record(
    record: GoldRecord,
    engine: dict[str, CandidateUnderTest],
    agent: dict[str, CandidateUnderTest],
    run: AgentRun | None,
    catalog: Catalog,
    registry: SchemaRegistry,
) -> list[ThreeWay]:
    compiled = catalog.get(record.tender_type)
    rows: list[ThreeWay] = []
    for field in record.fields:
        if field.field_path == SUMMARY_FIELD:
            # Written from the record in a second pass, not read from pages, and not asked
            # of the agent: nothing to compare three ways.
            continue
        try:
            definition = compiled.schema.field(field.field_path)
        except KeyError:
            continue
        e = score_field(record, field, definition, registry, engine.get(field.field_path))
        a = score_field(record, field, definition, registry, agent.get(field.field_path))
        if e is None or a is None:
            continue
        rows.append(
            ThreeWay(
                slug=record.slug,
                tender_type=record.tender_type,
                issuing_agency=record.issuing_agency,
                field_path=field.field_path,
                section=field.section,
                value_type=field.value_type,
                required=field.required,
                agreement=classify(e, a, definition, registry),
                gold_value=field.final_value,
                engine_value=e.candidate_value,
                agent_value=a.candidate_value,
                engine_outcome=e.outcome,
                agent_outcome=a.outcome,
                engine_evidence_ok=e.evidence_ok,
                agent_evidence_ok=a.evidence_ok,
                agent_run_id=run.id if run else None,
                agent_status=run.status if run else None,
            )
        )
    return rows


def compare_all(
    session: Session,
    tenant_id: str,
    records: list[GoldRecord],
    review_state: ReviewStateService,
    catalog: Catalog,
    registry: SchemaRegistry,
) -> tuple[list[ThreeWay], list[str]]:
    """Every gold tender with a finished agent pass; the slugs without one are returned
    apart and left out (a tender the agent has not read cannot be compared)."""
    rows: list[ThreeWay] = []
    without: list[str] = []
    for record in records:
        run, agent = agent_findings(session, tenant_id, record)
        if run is None:
            without.append(record.slug)
            continue
        engine = candidates_in_review(session, review_state, record)
        rows += compare_record(record, engine, agent, run, catalog, registry)
    return rows, without


def _counts(rows: list[ThreeWay]) -> dict[str, int]:
    counter = Counter(row.agreement for row in rows)
    return {name: counter.get(name, 0) for name in CLASSES}


def emphasis_of(rows: list[ThreeWay]) -> list[Emphasis]:
    """Per field, the agreement rate over the counted instances and whether it earns the
    low-review emphasis: at least 97% over at least 15 instances."""
    by_field: dict[str, list[ThreeWay]] = defaultdict(list)
    for row in rows:
        if row.agreement != "needs_judgement":
            by_field[row.field_path].append(row)
    out = []
    for path, group in sorted(by_field.items()):
        agree = sum(1 for r in group if r.agreement == "all_agree")
        rate = agree / len(group)
        out.append(
            Emphasis(
                field_path=path,
                instances=len(group),
                agreement=round(rate, 4),
                low_review=len(group) >= INSTANCES_MIN and rate >= AGREEMENT_MIN,
            )
        )
    return out


def summarise(
    rows: list[ThreeWay], tenant_id: str, tenders: int, without: list[str]
) -> ThreeWaySummary:
    def grouped(key: str) -> dict[str, dict[str, int]]:
        groups: dict[str, list[ThreeWay]] = defaultdict(list)
        for row in rows:
            groups[getattr(row, key)].append(row)
        return {name: _counts(group) for name, group in sorted(groups.items())}

    return ThreeWaySummary(
        tenant_id=tenant_id,
        made_at=datetime.now(UTC).isoformat(timespec="seconds"),
        tenders=tenders,
        tenders_without_agent_pass=without,
        fields=len(rows),
        by_class=_counts(rows),
        by_type=grouped("tender_type"),
        by_agency=grouped("issuing_agency"),
        by_field=grouped("field_path"),
        emphasis=emphasis_of(rows),
    )


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "–"


def _cell(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    text = " ".join(text.split())
    return (text[:57] + "…") if len(text) > 60 else text or "∅"


def _table(title: str, groups: dict[str, dict[str, int]]) -> list[str]:
    lines = [
        f"### {title}",
        "",
        "| | n | all agree | engine right | agent right | both wrong, same | "
        "both wrong, apart | both abstained | judgement |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, counts in groups.items():
        counted = sum(counts[c] for c in CLASSES if c != "needs_judgement")
        lines.append(
            f"| {name} | {counted} | {_pct(counts['all_agree'], counted)} | "
            f"{counts['engine_right_agent_wrong']} | {counts['agent_right_engine_wrong']} | "
            f"{counts['both_wrong_same_way']} | {counts['both_wrong_differently']} | "
            f"{counts['both_abstained']} | {counts['needs_judgement']} |"
        )
    return lines + [""]


def _listing(title: str, note: str, rows: list[ThreeWay]) -> list[str]:
    lines = [f"### {title}", "", note, ""]
    if not rows:
        return lines + ["None.", ""]
    lines += [
        "| Tender | Field | Reviewer | Engine | Agent |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in sorted(rows, key=lambda r: (r.field_path, r.slug)):
        lines.append(
            f"| {row.slug} | `{row.field_path}` | {_cell(row.gold_value)} | "
            f"{_cell(row.engine_value)} | {_cell(row.agent_value)} |"
        )
    return lines + [""]


def render_report(summary: ThreeWaySummary, rows: list[ThreeWay]) -> str:
    counted = summary.fields - summary.by_class["needs_judgement"]
    by = summary.by_class
    lines = [
        "# Three-way comparison: reviewer, engine, agent",
        "",
        f"Made {summary.made_at} by `python -m evals.threeway` (`make threeway`, "
        "`POST /api/v1/admin/threeway`) from the gold records, the readings in review and "
        "the latest finished agent pass of each gold tender at its reviewed version. "
        "Rewritten on every run; never edited by hand.",
        "",
        f"{summary.tenders} gold tender(s) compared"
        + (
            f"; {len(summary.tenders_without_agent_pass)} without an agent pass, left out: "
            + ", ".join(summary.tenders_without_agent_pass)
            if summary.tenders_without_agent_pass
            else ""
        )
        + f". {summary.fields} decided fields, {counted} counted "
        f"({by['needs_judgement']} long-text fields left to human judgement).",
        "",
        "## The six classes",
        "",
        "| Class | Fields | Share of counted |",
        "| --- | --- | --- |",
    ]
    labels = {
        "all_agree": "All agree",
        "engine_right_agent_wrong": "Engine right, agent wrong",
        "agent_right_engine_wrong": "Agent right, engine wrong",
        "both_wrong_same_way": "Both wrong the same way",
        "both_wrong_differently": "Both wrong, differently",
        "both_abstained": "Both abstained",
    }
    for name, label in labels.items():
        lines.append(f"| {label} | {by[name]} | {_pct(by[name], counted)} |")
    lines += ["", "## By tender type, agency and field", ""]
    lines += _table("By tender type", summary.by_type)
    lines += _table("By agency", summary.by_agency)
    disagreeing = {
        path: counts
        for path, counts in summary.by_field.items()
        if sum(counts[c] for c in CLASSES if c not in ("all_agree", "needs_judgement")) > 0
    }
    lines += _table("Fields with any disagreement", disagreeing)
    lines += ["## Error patterns", ""]
    lines += _listing(
        "Both wrong the same way: the schema or the document",
        "Two models from different families read the same wrong value: the clause is "
        "ambiguous, a table and a clause disagree, or the field's definition does not fit "
        "what the document states. Look at the schema and the help text before the prompts.",
        [r for r in rows if r.agreement == "both_wrong_same_way"],
    )
    lines += _listing(
        "The models disagree: candidates for a mandatory second pass",
        "One model right and the other wrong, or both wrong apart: in production these "
        "fields earn a second reading before they are shown, whatever their confidence.",
        [
            r
            for r in rows
            if r.agreement
            in ("engine_right_agent_wrong", "agent_right_engine_wrong", "both_wrong_differently")
        ],
    )
    lines += _listing(
        "The agent caught what the engine missed: prompt work",
        "Where the agent read the right value and the engine did not, the agent's path to "
        "the evidence (its search, the page it cited) is what to fold into the section's "
        "extract prompt, then `make eval PROMPT=<section>/vN` to measure it.",
        [r for r in rows if r.agreement == "agent_right_engine_wrong"],
    )
    lines += _listing(
        "Both abstained: the reviewer found what neither model did",
        "The value is in the document (the reviewer cited its page) and neither model "
        "returned it: routing, a scanned page, or a clause written in words the prompts do "
        "not expect.",
        [r for r in rows if r.agreement == "both_abstained"],
    )
    low = [e for e in summary.emphasis if e.low_review]
    lines += [
        "## Production confidence rule",
        "",
        f"A field is shown with low-review emphasis only when reviewer, engine and agent agree "
        f"on at least {AGREEMENT_MIN:.0%} of at least {INSTANCES_MIN} gold instances. "
        "It changes the reviewer screen's default emphasis and nothing else: there is no "
        "auto-approval. Written to `evals/results/review-emphasis-<tenant>.json`.",
        "",
        f"Fields that qualify today: {len(low)}"
        + (": " + ", ".join(f"`{e.field_path}`" for e in low) if low else "")
        + ". "
        + (
            f"The most instances any field has is "
            f"{max((e.instances for e in summary.emphasis), default=0)}; "
            f"the rule needs {INSTANCES_MIN}."
            if not low
            else ""
        ),
        "",
        "| Field | Instances | Agreement | Emphasis |",
        "| --- | --- | --- | --- |",
    ]
    for e in sorted(summary.emphasis, key=lambda e: (-e.agreement, -e.instances, e.field_path)):
        lines.append(
            f"| `{e.field_path}` | {e.instances} | {e.agreement:.0%} | "
            f"{'low-review' if e.low_review else 'full review'} |"
        )
    return "\n".join(lines) + "\n"


def emphasis_path(tenant_id: str, root: Path | None = None) -> Path:
    return (root or RESULTS_ROOT) / f"review-emphasis-{tenant_id}.json"


def write_emphasis(summary: ThreeWaySummary, root: Path | None = None) -> Path:
    path = emphasis_path(summary.tenant_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "tenant_id": summary.tenant_id,
                "made_at": summary.made_at,
                "rule": {"agreement_min": AGREEMENT_MIN, "instances_min": INSTANCES_MIN},
                "fields": [e.model_dump() for e in summary.emphasis],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def low_review_fields(tenant_id: str, root: Path | None = None) -> frozenset[str]:
    """The fields the emphasis file marks low-review; empty when there is no file."""
    path = emphasis_path(tenant_id, root)
    if not path.is_file():
        return frozenset()
    data = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(f["field_path"] for f in data.get("fields", []) if f.get("low_review"))


def write_threeway(
    session: Session,
    tenant_id: str,
    registry: SchemaRegistry,
    catalog: Catalog,
    review_state: ReviewStateService,
    *,
    only: set[str] | None = None,
    out: Path | None = None,
    results_root: Path | None = None,
) -> tuple[ThreeWaySummary, Path]:
    records = [r for r in load_all(tenant_id) if not only or r.slug in only]
    rows, without = compare_all(session, tenant_id, records, review_state, catalog, registry)
    summary = summarise(rows, tenant_id, len(records) - len(without), without)
    out = out or DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(summary, rows), encoding="utf-8")
    write_emphasis(summary, results_root)
    root = results_root or RESULTS_ROOT
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (root / f"{stamp}-threeway-{tenant_id}.json").write_text(
        json.dumps(
            {"summary": summary.model_dump(), "rows": [r.model_dump() for r in rows]},
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary, out


def main(argv: list[str]) -> int:
    from core.config import Settings
    from core.db import make_engine, make_session_factory
    from tender.services.packs import build_registry

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv[1:])
    settings = Settings()
    registry, catalog = build_registry()
    review_state = ReviewStateService(registry, settings.tenant_id)
    only = {s for s in args.only.split(",") if s} or None
    # The same root the review API reads the emphasis file from (settings.results_root).
    results_root = Path(settings.results_root) if settings.results_root else None
    with make_session_factory(make_engine(settings))() as session:
        summary, out = write_threeway(
            session,
            settings.tenant_id,
            registry,
            catalog,
            review_state,
            only=only,
            out=args.out,
            results_root=results_root,
        )
    by = summary.by_class
    print(
        f"wrote {out}: {summary.tenders} tender(s), {summary.fields} fields — "
        + ", ".join(f"{name} {by[name]}" for name in CLASSES)
        + (
            f"; without an agent pass: {', '.join(summary.tenders_without_agent_pass)}"
            if summary.tenders_without_agent_pass
            else ""
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
