"""The composite reliability figures (completion plan, Block 7 b).

Three measurements, each from the file its own run wrote under evals/results/, read together
so that every caller (`reliability_report` over MCP, the reliability report, the stage
reports) quotes the same numbers and the same sentences:

- in sample: the latest plain `make eval` over the gold records (Block 1), the accuracy the
  engine's readings reached against what the reviewers decided on the tenders it was tuned on;
- unseen: the latest `scripts.blind_check` over the Block 4 tenders, read under a frozen
  commit and never reviewed, so the one figure it supports is the evidence-location rate;
- the question eval: the latest `make ask-eval` (Block 5 d), when one has run.

The owner's rule of 2026-10-27 (DECISIONS): wherever accuracy is stated, the only sentences
are the in-sample field accuracy on the human-reviewed tenders and the evidence-location
rate on the unseen tenders. `statements` holds exactly those, built from the files, so no
report has to type a number by hand; where a file is missing the statement says so.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from evals.runner import RESULTS_ROOT

NO_EVAL = "No evaluation of the gold set is on file."
NO_UNSEEN = "No check of unseen tenders is on file."
NO_QUERY_EVAL = (
    "The question eval (Block 5 d, `make ask-eval`) has not run: the retrieval route calls "
    "the model, and no run was allowed yet."
)
CAVEAT = (
    "The in-sample figure measures the engine on the tenders it was tuned on, against the "
    "reviewers' decisions; it is not a forecast for a new tender. The unseen tenders were "
    "never reviewed, so nothing about the correctness of their values is known: a located "
    "quote says the value is on the page it cites, not that it is the right value."
)


class InSample(BaseModel):
    """`make eval` over the gold records: Block 1's baseline and every later run."""

    tenders: int
    scored: int
    correct: int
    accuracy: float | None
    evidence_scored: int
    evidence_accuracy: float | None
    critical_scored: int
    critical_accuracy: float | None
    high_confidence_misses: int
    as_of: str | None


class Unseen(BaseModel):
    """`scripts.blind_check` over the Block 4 tenders: only what needs no reviewer."""

    tenders: list[str]
    complete: list[str]
    values: int
    located: int
    evidence_location_rate: float | None
    rules_run: int
    rules_passed: int
    rule_pass_rate: float | None
    unlocated_at_high_confidence: int
    as_of: str | None


class QueryEval(BaseModel):
    """`make ask-eval`: the fifty questions over the gold tenders, when it has run."""

    run: bool
    questions: int = 0
    accuracy: float | None = None
    critical_accuracy: float | None = None
    citations: int = 0
    citation_resolution_rate: float | None = None
    as_of: str | None = None
    note: str | None = None


class Composite(BaseModel):
    in_sample: InSample | None
    unseen: Unseen | None
    query_eval: QueryEval
    # The sentences a report may use for accuracy, and nothing else (DECISIONS 2026-10-27).
    statements: list[str]
    caveat: str = CAVEAT


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _latest(root: Path, pattern: str, keep: Any = None) -> dict[str, Any] | None:
    """The last file matching the pattern (the stamp sorts the names) that `keep` accepts."""
    latest = None
    for path in sorted(root.glob(pattern)):
        data = _load(path)
        if data is not None and (keep is None or keep(data)):
            latest = data
    return latest


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def in_sample(tenant_id: str, results_root: Path | None = None) -> InSample | None:
    data = _latest(
        results_root or RESULTS_ROOT,
        "*-latest*.json",
        lambda d: d.get("tenant_id") == tenant_id and not d.get("prompt"),
    )
    if data is None:
        return None
    summary = data.get("summary") or {}
    critical = (summary.get("by_critical") or {}).get("critical") or {}
    return InSample(
        tenders=len({s.get("slug") for s in data.get("scores") or [] if s.get("slug")}),
        scored=int(summary.get("scored") or 0),
        correct=int(summary.get("value_correct") or 0),
        accuracy=summary.get("value_accuracy"),
        evidence_scored=int(summary.get("evidence_scored") or 0),
        evidence_accuracy=summary.get("evidence_accuracy"),
        critical_scored=int(critical.get("n") or 0),
        critical_accuracy=critical.get("accuracy"),
        high_confidence_misses=len(summary.get("high_confidence_misses") or []),
        as_of=data.get("made_at"),
    )


def unseen(results_root: Path | None = None) -> Unseen | None:
    data = _latest(results_root or RESULTS_ROOT, "*-blind-check.json")
    if data is None:
        return None
    tenders = [t for t in data.get("tenders") or [] if isinstance(t, dict)]
    # The rate is stated on the complete tenders only: a tender whose runs did not finish
    # has values still to come, and its rate would move with them.
    complete = [t for t in tenders if t.get("complete")]
    values = sum(int(t.get("answered") or 0) for t in complete)
    located = sum(int(t.get("located") or 0) for t in complete)
    rules_run = sum(int((t.get("rules") or {}).get("rules_run") or 0) for t in complete)
    rules_passed = sum(int((t.get("rules") or {}).get("passed") or 0) for t in complete)
    return Unseen(
        tenders=[str(t.get("slug")) for t in tenders],
        complete=[str(t.get("slug")) for t in complete],
        values=values,
        located=located,
        evidence_location_rate=_rate(located, values),
        rules_run=rules_run,
        rules_passed=rules_passed,
        rule_pass_rate=_rate(rules_passed, rules_run),
        unlocated_at_high_confidence=sum(len(t.get("unlocated_high") or []) for t in complete),
        as_of=data.get("generated"),
    )


def query_eval(results_root: Path | None = None) -> QueryEval:
    data = _latest(results_root or RESULTS_ROOT, "ask-eval-*.json")
    if data is None:
        return QueryEval(run=False, note=NO_QUERY_EVAL)
    summary = data.get("summary") or {}
    return QueryEval(
        run=True,
        questions=int(summary.get("questions") or 0),
        accuracy=summary.get("accuracy"),
        critical_accuracy=summary.get("critical_accuracy"),
        citations=int(summary.get("citations_total") or 0),
        citation_resolution_rate=summary.get("citation_resolution_rate"),
        as_of=data.get("made_at"),
        note=(
            "In-sample: the expected answers are the gold records' decided values, over the "
            "tenders the engine was tuned on."
        ),
    )


def _pct(value: float | None, digits: int = 1) -> str:
    return "–" if value is None else f"{value * 100:.{digits}f}%"


def statements(sample: InSample | None, blind: Unseen | None, questions: QueryEval) -> list[str]:
    out = []
    if sample is None or sample.accuracy is None:
        out.append(NO_EVAL)
    else:
        out.append(
            f"{_pct(sample.accuracy)} field accuracy on {sample.tenders} human-reviewed "
            f"tenders (in-sample)"
        )
    if blind is None or blind.evidence_location_rate is None:
        out.append(NO_UNSEEN)
    else:
        out.append(
            f"{_pct(blind.evidence_location_rate)} evidence location on {len(blind.complete)} "
            f"unseen tenders ({blind.located} of {blind.values} values located on the page "
            "they cite; no accuracy claim)"
        )
    if questions.run:
        out.append(
            f"Question eval: {_pct(questions.accuracy)} of {questions.questions} questions "
            f"answered as the gold record says, {_pct(questions.citation_resolution_rate)} of "
            f"{questions.citations} citations resolved on their page (in-sample)"
        )
    else:
        out.append(questions.note or NO_QUERY_EVAL)
    return out


def composite(tenant_id: str, results_root: Path | None = None) -> Composite:
    sample = in_sample(tenant_id, results_root)
    blind = unseen(results_root)
    questions = query_eval(results_root)
    return Composite(
        in_sample=sample,
        unseen=blind,
        query_eval=questions,
        statements=statements(sample, blind, questions),
    )


def markdown(report: Composite) -> list[str]:
    """The headline block of the reliability report: the sentences, then the figures."""
    lines = ["## Headline (completion plan, Block 7 b)", ""]
    lines += [f"- {s}" for s in report.statements]
    lines += ["", report.caveat, ""]
    lines += ["| Measurement | Figure | n | As of |", "| --- | --- | --- | --- |"]
    if report.in_sample:
        s = report.in_sample
        lines.append(
            f"| Field accuracy, gold set (in-sample) | {_pct(s.accuracy)} | {s.scored} scored "
            f"fields of {s.tenders} tenders | {s.as_of or '–'} |"
        )
        lines.append(
            f"| Critical fields, gold set (in-sample) | {_pct(s.critical_accuracy)} | "
            f"{s.critical_scored} | {s.as_of or '–'} |"
        )
        lines.append(
            f"| Evidence accuracy, gold set | {_pct(s.evidence_accuracy)} | {s.evidence_scored} "
            f"| {s.as_of or '–'} |"
        )
        lines.append(
            f"| Wrong readings shown at high confidence, gold set | {s.high_confidence_misses} "
            f"| {s.scored} | {s.as_of or '–'} |"
        )
    if report.unseen:
        u = report.unseen
        lines.append(
            f"| Evidence location, unseen tenders | {_pct(u.evidence_location_rate)} | "
            f"{u.values} values, {len(u.complete)} tenders ({', '.join(u.complete)}) | "
            f"{u.as_of or '–'} |"
        )
        lines.append(
            f"| Deterministic rules passed, unseen tenders | {_pct(u.rule_pass_rate)} | "
            f"{u.rules_run} | {u.as_of or '–'} |"
        )
        lines.append(
            f"| Unlocated readings at high confidence, unseen tenders | "
            f"{u.unlocated_at_high_confidence} | {u.values} | {u.as_of or '–'} |"
        )
    q = report.query_eval
    if q.run:
        lines.append(
            f"| Question eval, answer accuracy (in-sample) | {_pct(q.accuracy)} | {q.questions} "
            f"| {q.as_of or '–'} |"
        )
        lines.append(
            f"| Question eval, citations resolved | {_pct(q.citation_resolution_rate)} | "
            f"{q.citations} | {q.as_of or '–'} |"
        )
    else:
        lines.append("| Question eval | not run | – | – |")
    lines.append("")
    return lines
