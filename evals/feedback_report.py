"""The feedback report: where reviewers corrected the model, grouped, with a suggestion per
field for a person to act on. Nothing here changes a prompt, a threshold or a model.

  python -m evals.feedback_report [--out docs/reports/FEEDBACK-REPORT.md]

Only feedback of active decisions counts: a decision that was cleared or decided again
leaves its feedback row as history.
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

from core.models import Approval, Feedback
from evals.gold import tender_key
from tender.models import Tender

DEFAULT_OUT = Path("docs/reports/FEEDBACK-REPORT.md")
SUGGESTIONS = {
    "wrong_value": (
        "prompt: name the clause that governs and the figure to prefer when a table and a "
        "clause disagree"
    ),
    "format": "validator or normaliser: accept the printed form and store the normalised one",
    "missing": "prompt or routing: say where the value is stated and which pages to read for it",
    "extra": (
        "prompt: return null unless the pages state the value; say what wording is not a value"
    ),
}


class FeedbackRow(BaseModel):
    field_path: str
    delta_kind: str
    tender_slug: str
    tender_type: str
    issuing_agency: str
    prompt_version: str
    reviewer: str
    candidate_value: Any
    final_value: Any
    note: str | None = None


def load_feedback(session: Session, tenant_id: str) -> list[FeedbackRow]:
    rows = session.execute(
        select(Feedback, Approval, Tender)
        .join(Approval, Approval.id == Feedback.approval_id)
        .join(Tender, Tender.id == Approval.object_id)
        .where(
            Feedback.tenant_id == tenant_id,
            Approval.tenant_id == tenant_id,
            Approval.status == "active",
            Approval.object_type == "tender",
        )
        .order_by(Feedback.created_at)
    ).all()
    return [
        FeedbackRow(
            field_path=f.field_path,
            delta_kind=f.delta_kind,
            tender_slug=tender_key(t),
            tender_type=t.tender_type,
            issuing_agency=t.issuing_agency,
            prompt_version=f.prompt_version,
            reviewer=f.reviewer,
            candidate_value=f.candidate_value,
            final_value=f.final_value,
            note=a.note,
        )
        for f, a, t in rows
    ]


def group(rows: list[FeedbackRow]) -> dict[str, dict[str, Counter[str]]]:
    """field path -> dimension -> counts, the dimensions being delta_kind, tender_type,
    issuing_agency and prompt_version."""
    grouped: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for row in rows:
        for dimension in ("delta_kind", "tender_type", "issuing_agency", "prompt_version"):
            grouped[row.field_path][dimension][getattr(row, dimension)] += 1
    return grouped


def suggestion(kinds: Counter[str]) -> str:
    if not kinds:
        return ""
    kind, _ = kinds.most_common(1)[0]
    return SUGGESTIONS.get(kind, "look at the examples")


def render(rows: list[FeedbackRow], *, made_at: datetime | None = None) -> str:
    made = (made_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    grouped = group(rows)
    lines = [
        "# Feedback report",
        "",
        f"Generated {made} by `python -m evals.feedback_report` from the `feedback` table: "
        "every correction a reviewer made to a candidate, for decisions that stand. "
        "The suggestions are for a person to act on; nothing is applied automatically.",
        "",
        f"Corrections: {len(rows)} on {len(grouped)} field(s), "
        f"{len({r.tender_slug for r in rows})} tender(s).",
        "",
        "## Corrections by kind",
        "",
        "| Kind | Count | Meaning |",
        "| --- | --- | --- |",
    ]
    meanings = {
        "wrong_value": "the reviewer gave a different value",
        "format": "the same value in another form",
        "missing": "the model found nothing; the reviewer supplied the value",
        "extra": "the model gave a value; the reviewer says the document has none",
    }
    kinds = Counter(r.delta_kind for r in rows)
    for kind, meaning in meanings.items():
        lines.append(f"| {kind} | {kinds.get(kind, 0)} | {meaning} |")
    lines += ["", "## The fields with the most corrections", ""]
    ranked = sorted(
        grouped.items(), key=lambda item: (-sum(item[1]["delta_kind"].values()), item[0])
    )
    if not ranked:
        lines.append("No corrections yet.")
    for path, dims in ranked[:10]:
        total = sum(dims["delta_kind"].values())
        lines.append(f"### `{path}`: {total} correction(s)")
        lines.append("")
        lines.append(
            "Kinds: "
            + ", ".join(f"{k} {n}" for k, n in dims["delta_kind"].most_common())
            + ". Tender types: "
            + ", ".join(f"{k} {n}" for k, n in dims["tender_type"].most_common())
            + ". Agencies: "
            + ", ".join(f"{k} {n}" for k, n in dims["issuing_agency"].most_common())
            + ". Prompt versions: "
            + ", ".join(f"{k} {n}" for k, n in dims["prompt_version"].most_common())
            + "."
        )
        lines.append("")
        lines.append("| Tender | Kind | Candidate | Final | Reviewer's note |")
        lines.append("| --- | --- | --- | --- | --- |")
        for row in [r for r in rows if r.field_path == path][:3]:
            lines.append(
                f"| {row.tender_slug} | {row.delta_kind} | {_cell(row.candidate_value)} | "
                f"{_cell(row.final_value)} | {_cell(row.note or '')} |"
            )
        lines.append("")
        lines.append(f"Suggested change: {suggestion(dims['delta_kind'])}.")
        lines.append("")
    return "\n".join(lines) + "\n"


def _cell(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    text = " ".join(text.split()).replace("|", "\\|")
    return text[:90] + ("…" if len(text) > 90 else "")


def main(argv: list[str]) -> int:
    from core.config import Settings
    from core.db import make_engine, make_session_factory

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv[1:])
    settings = Settings()
    with make_session_factory(make_engine(settings))() as session:
        rows = load_feedback(session, settings.tenant_id)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(rows), encoding="utf-8")
    print(f"wrote {args.out} ({len(rows)} corrections)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
