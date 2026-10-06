"""The reliability report and the review log.

  python -m evals.report [--out docs/reports/RELIABILITY-REPORT.md]
                         [--log docs/reports/REVIEW-LOG.md]

Scores every gold record against the candidates now in review, and writes: tenders reviewed
by type; overall, per-section, per-field accuracy; value against evidence accuracy; fields
below 90% with what the misses look like; prompt versions tried and their effect (from
evals/results/); reviewer time per tender; a recommendation per section; and whether the
stability bar for Stage 5 is met. Regenerated on every new gold record.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Approval
from evals.gold import GoldRecord, load_all
from evals.runner import RESULTS_ROOT, FieldScore, Summary, summarise
from tender.models import Tender

DEFAULT_OUT = Path("docs/reports/RELIABILITY-REPORT.md")
DEFAULT_LOG = Path("docs/reports/REVIEW-LOG.md")
STABLE_ACCURACY = 0.90
FLOOR_ACCURACY = 0.75
MIN_PER_TYPE = 2
SITTING_GAP_MINUTES = 15


class Sitting(BaseModel):
    started: str
    completed: str | None
    deciding_minutes: int
    sittings: int
    decisions: int


class TenderLine(BaseModel):
    slug: str
    tender_type: str
    issuing_agency: str
    reviewer: str
    completed_at: str
    reviewed_version: int
    decided: int
    edited: int
    not_in_document: int
    edited_fields: list[str]
    time: Sitting | None
    notable_misses: list[str]


class Stability(BaseModel):
    met: bool
    types_with_two_or_more_in_set: list[str]
    types_short_of_two_reviews: list[str]
    required_accuracy: float | None
    required_fields_below_floor: list[str]
    # Per section prompt, required-field accuracy under each of its last two versions seen.
    prompt_versions_seen: list[str]
    prompt_versions_below_bar: list[str]
    reasons: list[str]


def accuracy_by_prompt_version(scores: list[FieldScore]) -> dict[str, dict[str, float]]:
    """prompt name -> version -> required-field accuracy, for the last two versions of each
    prompt that scored candidates carry (the last two by version number)."""
    counts: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for s in scores:
        if s.counted and s.required and s.prompt_name and s.prompt_version:
            counts[s.prompt_name][s.prompt_version].append(int(s.correct))
    found: dict[str, dict[str, float]] = {}
    for prompt, versions in sorted(counts.items()):
        last_two = sorted(versions, key=_version_number)[-2:]
        found[prompt] = {v: round(sum(versions[v]) / len(versions[v]), 4) for v in last_two}
    return found


def _version_number(version: str) -> int:
    digits = "".join(ch for ch in version if ch.isdigit())
    return int(digits) if digits else 0


def tender_lines(
    records: list[GoldRecord], scores: list[FieldScore], timings: dict[str, Sitting]
) -> list[TenderLine]:
    lines = []
    for record in records:
        decided = [f for f in record.fields if f.decision]
        own = [s for s in scores if s.slug == record.slug]
        lines.append(
            TenderLine(
                slug=record.slug,
                tender_type=record.tender_type,
                issuing_agency=record.issuing_agency,
                reviewer=record.reviewer,
                completed_at=record.completed_at,
                reviewed_version=record.reviewed_version,
                decided=len(decided),
                edited=sum(1 for f in decided if f.decision == "edited"),
                not_in_document=sum(1 for f in decided if f.decision == "not_in_document"),
                edited_fields=[f.field_path for f in decided if f.decision == "edited"],
                time=timings.get(record.slug),
                notable_misses=[
                    f"{s.field_path} ({s.outcome})" for s in own if s.counted and not s.correct
                ][:8],
            )
        )
    return lines


def timing(session: Session, tenant_id: str, record: GoldRecord) -> Sitting | None:
    """From the approval rows: first and last decision, sittings separated by gaps of more
    than fifteen minutes, and the minutes spent between decisions inside sittings."""
    times = list(
        session.scalars(
            select(Approval.decided_at)
            .where(
                Approval.tenant_id == tenant_id,
                Approval.object_type == "tender",
                Approval.object_id == record.tender_id,
            )
            .order_by(Approval.decided_at)
        )
    )
    if not times:
        return None
    deciding = 0.0
    sittings = 1
    for earlier, later in zip(times, times[1:], strict=False):
        gap = (later - earlier).total_seconds() / 60
        if gap > SITTING_GAP_MINUTES:
            sittings += 1
        else:
            deciding += gap
    return Sitting(
        started=times[0].isoformat(timespec="seconds"),
        completed=record.completed_at,
        deciding_minutes=round(deciding),
        sittings=sittings,
        decisions=len(times),
    )


def evaluated_scores(tenant_id: str, results_root: Path | None = None) -> list[FieldScore]:
    """The scores of earlier prompt evaluations (results files made with a prompt), so the
    bar can judge a version that a later run has since superseded in review."""
    found = []
    for data in _results(tenant_id, results_root):
        if data.get("prompt"):
            found += [FieldScore.model_validate(s) for s in data.get("scores", [])]
    return found


def stability(
    records: list[GoldRecord],
    summary: Summary,
    scores: list[FieldScore],
    set_types: Counter[str],
    history: list[FieldScore] | None = None,
) -> Stability:
    reviewed_per_type = Counter(r.tender_type for r in records)
    eligible = sorted(t for t, n in set_types.items() if n >= MIN_PER_TYPE)
    short = [t for t in eligible if reviewed_per_type.get(t, 0) < MIN_PER_TYPE]
    required = [s for s in scores if s.counted and s.required]
    required_accuracy = (
        round(sum(1 for s in required if s.correct) / len(required), 4) if required else None
    )
    by_required_field: dict[str, list[FieldScore]] = defaultdict(list)
    for s in required:
        by_required_field[s.field_path].append(s)
    below_floor = sorted(
        path
        for path, own in by_required_field.items()
        if sum(1 for s in own if s.correct) / len(own) < FLOOR_ACCURACY
    )
    by_prompt = accuracy_by_prompt_version(scores + (history or []))
    versions = [f"{p} {v}" for p, vs in by_prompt.items() for v in vs]
    below_bar = [
        f"{p} {v} ({_pct(acc)})"
        for p, vs in by_prompt.items()
        for v, acc in vs.items()
        if acc < STABLE_ACCURACY
    ]
    reasons = []
    if not records:
        reasons.append("no gold record yet")
    if short:
        reasons.append(f"fewer than {MIN_PER_TYPE} reviewed tenders for: {', '.join(short)}")
    if required_accuracy is None or required_accuracy < STABLE_ACCURACY:
        reasons.append(
            f"required-field accuracy {_pct(required_accuracy)} is below {_pct(STABLE_ACCURACY)}"
        )
    if below_floor:
        reasons.append(f"required fields below {_pct(FLOOR_ACCURACY)}: {len(below_floor)}")
    if below_bar:
        reasons.append("below 90% on required fields under: " + ", ".join(below_bar))
    if by_prompt:
        reasons.append(
            "required-field accuracy by section prompt, last two versions seen: "
            + "; ".join(
                f"{p} " + ", ".join(f"{v} {_pct(acc)}" for v, acc in vs.items())
                for p, vs in by_prompt.items()
            )
        )
    met = (
        bool(records)
        and not short
        and required_accuracy is not None
        and required_accuracy >= STABLE_ACCURACY
        and not below_floor
        and not below_bar
    )
    return Stability(
        met=met,
        types_with_two_or_more_in_set=eligible,
        types_short_of_two_reviews=short,
        required_accuracy=required_accuracy,
        required_fields_below_floor=below_floor,
        prompt_versions_seen=versions,
        prompt_versions_below_bar=below_bar,
        reasons=reasons,
    )


def recommendation(bucket: dict[str, Any], misses: list[dict[str, Any]]) -> str:
    if bucket["n"] < 2:
        return "not enough reviews yet"
    if bucket["accuracy"] is not None and bucket["accuracy"] >= STABLE_ACCURACY:
        return "stable"
    kinds = Counter(m["outcome"] for m in misses)
    if not kinds:
        return "stable"
    kind, _ = kinds.most_common(1)[0]
    if kind == "format":
        return "needs validator"
    if kind in ("wrong_value", "missing", "extra"):
        return "needs prompt work"
    return "needs schema change"


def _results(tenant_id: str, results_root: Path | None = None) -> list[dict[str, Any]]:
    """The tenant's results files, oldest first."""
    found = []
    for path in sorted((results_root or RESULTS_ROOT).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("tenant_id") == tenant_id:
            data["file"] = path.name
            found.append(data)
    return found


def prompt_comparison(tenant_id: str, results_root: Path | None = None) -> list[dict[str, Any]]:
    """What the tenant's results files hold, per evaluation."""
    found = []
    for data in _results(tenant_id, results_root):
        path = Path(data["file"])
        summary = data.get("summary", {})
        found.append(
            {
                "file": path.name,
                "made_at": data.get("made_at"),
                "prompt": data.get("prompt"),
                "label": data.get("label"),
                "value_accuracy": summary.get("value_accuracy"),
                "evidence_accuracy": summary.get("evidence_accuracy"),
                "scored": summary.get("scored"),
            }
        )
    return found


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def render_report(
    records: list[GoldRecord],
    scores: list[FieldScore],
    set_types: Counter[str],
    timings: dict[str, Sitting],
    comparisons: list[dict[str, Any]],
    made_at: datetime | None = None,
    history: list[FieldScore] | None = None,
) -> str:
    made = (made_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    summary = summarise(scores)
    bar = stability(records, summary, scores, set_types, history)
    lines = [
        "# Reliability report",
        "",
        f"Generated {made} by `python -m evals.report` (also `make report`). Every gold record "
        "scored against the candidates now in review at the version it was reviewed at. "
        "Accuracy is value accuracy: the candidate the reviewer saw against what they decided. "
        "Evidence accuracy asks whether the candidate cited a page the reviewer accepted. "
        "Long text is not scored by rule.",
        "",
        "## Tenders reviewed",
        "",
        "| Type | In the set | Reviewed | Tenders |",
        "| --- | --- | --- | --- |",
    ]
    reviewed = defaultdict(list)
    for r in records:
        reviewed[r.tender_type].append(r.slug)
    for tender_type in sorted(set(set_types) | set(reviewed)):
        lines.append(
            f"| {tender_type} | {set_types.get(tender_type, 0)} | "
            f"{len(reviewed.get(tender_type, []))} | "
            f"{', '.join(reviewed.get(tender_type, [])) or '-'} |"
        )
    lines += [
        "",
        "## Accuracy",
        "",
        f"- Value accuracy: **{_pct(summary.value_accuracy)}** on {summary.scored} scored fields "
        f"({summary.value_correct} correct); {summary.needs_judgement} long-text fields need "
        "human judgement.",
        f"- Evidence accuracy: **{_pct(summary.evidence_accuracy)}** on {summary.evidence_scored} "
        f"fields with a value and accepted pages ({summary.evidence_correct} cited an accepted "
        "page). A right value from the wrong page counts as right above and wrong here.",
        "",
        "| Section | Accuracy | n | Evidence | Recommendation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for section, bucket in summary.by_section.items():
        misses = [
            m
            for m in summary.misses
            if any(s.section == section and s.field_path == m["field_path"] for s in scores)
        ]
        lines.append(
            f"| {section} | {_pct(bucket['accuracy'])} | {bucket['n']} | "
            f"{_pct(bucket['evidence_accuracy'])} | "
            f"{recommendation(bucket, misses)} |"
        )
    lines += [
        "",
        "### By tender type",
        "",
        "| Type | Accuracy | n | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for tender_type, bucket in summary.by_type.items():
        lines.append(
            f"| {tender_type} | {_pct(bucket['accuracy'])} | {bucket['n']} | "
            f"{_pct(bucket['evidence_accuracy'])} |"
        )
    lines += ["", f"## Fields below {_pct(STABLE_ACCURACY)}", ""]
    low = [
        (p, b)
        for p, b in summary.by_field.items()
        if b["accuracy"] is not None and b["accuracy"] < STABLE_ACCURACY
    ]
    if not low:
        lines.append("None." if summary.scored else "Nothing scored yet.")
    else:
        lines += [
            "| Field | Accuracy | n | Misses | What the misses look like |",
            "| --- | --- | --- | --- | --- |",
        ]
        for path, bucket in low:
            own = [m for m in summary.misses if m["field_path"] == path]
            kinds = Counter(m["outcome"] for m in own)
            agencies = Counter(
                s.issuing_agency
                for s in scores
                if s.field_path == path and s.counted and not s.correct
            )
            why = ", ".join(f"{k} {n}" for k, n in kinds.most_common())
            if len(agencies) > 1:
                why += "; across agencies " + ", ".join(agencies)
            lines.append(
                f"| `{path}` | {_pct(bucket['accuracy'])} | {bucket['n']} | "
                f"{bucket['misses']} | {why} |"
            )
    lines += ["", "## Prompt versions tried", ""]
    if not comparisons:
        lines.append("No scored run in `evals/results/` yet.")
    else:
        lines += [
            "| Result | Prompt | Value accuracy | Evidence accuracy | n |",
            "| --- | --- | --- | --- | --- |",
        ]
        for c in comparisons:
            lines.append(
                f"| {c['file']} | {c['prompt'] or 'as pinned'} | {_pct(c['value_accuracy'])} | "
                f"{_pct(c['evidence_accuracy'])} | {c['scored']} |"
            )
    lines += [
        "",
        "## Reviewer time per tender",
        "",
        "| Tender | Reviewer | Sittings | Minutes deciding | Decisions | Completed |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in records:
        t = timings.get(r.slug)
        lines.append(
            f"| {r.slug} | {r.reviewer} | {t.sittings if t else '-'} | "
            f"{t.deciding_minutes if t else '-'} | "
            f"{t.decisions if t else '-'} | {r.completed_at[:16].replace('T', ' ')} |"
        )
    lines += ["", "## Stability bar for Stage 5", ""]
    lines.append(
        f"**{'Met' if bar.met else 'Not met'}.** Required-field value accuracy "
        f"{_pct(bar.required_accuracy)}."
    )
    lines.append("")
    lines.append(
        f"At least {MIN_PER_TYPE} reviewed tenders for every type with {MIN_PER_TYPE} or more in "
        f"the set ({', '.join(bar.types_with_two_or_more_in_set) or 'none'}); required-field "
        f"value accuracy at least {_pct(STABLE_ACCURACY)} across the last two prompt versions; "
        f"no required field below {_pct(FLOOR_ACCURACY)}."
    )
    lines.append("")
    for reason in bar.reasons:
        lines.append(f"- {reason}")
    lines.append("")
    return "\n".join(lines) + "\n"


def render_log(lines: list[TenderLine], made_at: datetime | None = None) -> str:
    made = (made_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        "# Review log",
        "",
        f"Generated {made} by `python -m evals.report`, from the gold records and the approvals.",
        "",
        "| Tender | Type | Reviewer | Started | Completed | Decided | Edited | "
        "Not in document | Notable misses |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for t in lines:
        started = t.time.started[:16].replace("T", " ") if t.time else "-"
        out.append(
            f"| {t.slug} | {t.tender_type} | {t.reviewer} | {started} | "
            f"{t.completed_at[:16].replace('T', ' ')} | {t.decided} | "
            f"{t.edited}: {', '.join(f'`{p}`' for p in t.edited_fields) or '-'} | "
            f"{t.not_in_document} | "
            f"{', '.join(t.notable_misses) or '-'} |"
        )
    return "\n".join(out) + "\n"


def write_reports(
    session: Session,
    tenant_id: str,
    registry: Any,
    catalog: Any,
    review_state: Any,
    out: Path | None = None,
    log: Path | None = None,
) -> tuple[int, int]:
    """Score the tenant's gold records and write the reliability report and the review
    log. Returns the counts of gold records and scored fields."""
    from evals.runner import candidates_in_review, score_record

    out = out or DEFAULT_OUT
    log = log or DEFAULT_LOG
    records = load_all(tenant_id)
    scores: list[FieldScore] = []
    timings: dict[str, Sitting] = {}
    set_types = Counter(
        session.scalars(select(Tender.tender_type).where(Tender.tenant_id == tenant_id))
    )
    for record in records:
        found = candidates_in_review(session, review_state, record)
        scores += score_record(record, found, catalog, registry)
        sitting = timing(session, tenant_id, record)
        if sitting:
            timings[record.slug] = sitting
    text = render_report(
        records,
        scores,
        set_types,
        timings,
        prompt_comparison(tenant_id),
        history=evaluated_scores(tenant_id),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    log.write_text(render_log(tender_lines(records, scores, timings)), encoding="utf-8")
    return len(records), len(scores)


def main(argv: list[str]) -> int:
    from core.config import Settings
    from core.db import make_engine, make_session_factory
    from core.services.review_state import ReviewStateService
    from tender.services.packs import build_registry

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--log", type=Path, default=None)
    args = parser.parse_args(argv[1:])
    settings = Settings()
    registry, catalog = build_registry()
    review_state = ReviewStateService(registry, settings.tenant_id)
    with make_session_factory(make_engine(settings))() as session:
        records, scored = write_reports(
            session, settings.tenant_id, registry, catalog, review_state, args.out, args.log
        )
    print(
        f"wrote {args.out or DEFAULT_OUT} and {args.log or DEFAULT_LOG}: {records} gold "
        f"record(s), {scored} scored fields"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
