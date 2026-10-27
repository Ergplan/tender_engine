"""Block 5 d: the question set over the gold tenders, against the live engine.

  python -m evals.ask_eval [--only q01,q02] [--questions evals/questions/gold-questions.yaml]

Every question in the set has the reviewer's decided value as its expected answer (the
gold record). The engine is asked the way the API asks it (`AskService.ask`, the same
retriever and model), and two things are measured, as the plan wants: answer accuracy
(the expected value is in the answer, under the match rules below) and the citation
resolution rate (of every quote the answer gives, the share the evidence resolver located
on its page). Both are reported overall, for the critical questions, and per route
(`field`: answered from the record; `retrieval`: answered from retrieved pages by the
model). The cross-tender questions (Block 5 c) are scored on whether the question is read
into the right structured query and whether the structured query matches the right gold
tenders. Results go to evals/results/ask-eval-<stamp>.json and .md.

Match rules. A date matches in any written form (30.10.2026, 30 October 2026, 2026-10-30,
30/10/2026). A number matches any number in the answer within 0.5%, after Indian and
plain scales are applied (Rs. 87.514 lakh = 8,751,400; 4 crore = 40,000,000; commas
dropped; a percent sign kept apart). Text matches when one of the expected phrases is in
the answer. A boolean matches yes/allowed/permitted against no/not allowed/prohibited.
"""

import argparse
import contextlib
import json
import re
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from core.config import Settings
from core.retrieval import ChunkStores, Retriever, make_embedders
from scripts.ingest_tenders import build_services
from tender.services.ask import AskAnswer, AskError, AskService
from tender.services.ask_across import CrossQuery, parse_cross_question, search_facts

QUESTIONS = Path(__file__).resolve().parent / "questions" / "gold-questions.yaml"
RESULTS_ROOT = Path(__file__).resolve().parent / "results"
TOLERANCE = 0.005
ACTOR = "ask_eval"

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december")
    )
}  # fmt: skip
_SCALES = {
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
    "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "million": 1e6, "mn": 1e6, "billion": 1e9, "thousand": 1e3,
}  # fmt: skip
_NUMBER = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*"
    r"(%|lakhs?|lacs?|crores?|cr\b|million|mn\b|billion|thousand)?",
    re.I,
)
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_WORDS = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|"
    r"september|october|november|december)[,.]?\s+(\d{4})\b",
    re.I,
)
_YES = ("yes", "allowed", "permitted", "may bid", "can bid", "is allowed", "are allowed", "true")
_NO = ("not allowed", "not permitted", "prohibited", "no,", "no.", "false", "cannot")


# -- match rules ---------------------------------------------------------------------------


def numbers_in(text: str) -> list[float]:
    """Every number in the text, scaled by the word after it when there is one. A percent
    sign scales nothing (85% stays 85)."""
    out: list[float] = []
    for raw, unit in _NUMBER.findall(text):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        out.append(value)
        if unit and unit.lower() in _SCALES:
            out.append(value * _SCALES[unit.lower()])
    return out


def dates_in(text: str) -> set[date]:
    found: set[date] = set()
    for d, m, y in _DATE_NUMERIC.findall(text):
        with contextlib.suppress(ValueError):
            found.add(date(int(y), int(m), int(d)))
    for y, m, d in _DATE_ISO.findall(text):
        with contextlib.suppress(ValueError):
            found.add(date(int(y), int(m), int(d)))
    for d, month, y in _DATE_WORDS.findall(text):
        with contextlib.suppress(ValueError, KeyError):
            found.add(date(int(y), _MONTHS[month.lower()], int(d)))
    return found


def matches(expect: dict[str, Any], text: str, value: Any = None) -> bool:
    """Does the answer (its prose, and the record value when the route gave one) hold the
    expected answer?"""
    kind = expect["kind"]
    haystack = text if value is None else f"{text}\n{_as_text(value)}"
    if kind == "date":
        wanted = expect["value"]
        wanted = wanted if isinstance(wanted, date) else date.fromisoformat(str(wanted))
        return wanted in dates_in(haystack)
    if kind == "number":
        wanted = float(expect["value"])
        return any(
            abs(found - wanted) <= TOLERANCE * max(abs(wanted), 1e-9)
            for found in numbers_in(haystack)
        )
    if kind == "text":
        lowered = haystack.lower()
        return any(phrase.lower() in lowered for phrase in expect["any_of"])
    if kind == "bool":
        lowered = haystack.lower()
        if isinstance(value, bool):
            return value is bool(expect["value"])
        said_no = any(w in lowered for w in _NO)
        said_yes = any(w in lowered for w in _YES)
        return (said_yes and not said_no) if expect["value"] else said_no
    raise ValueError(f"unknown expect kind {kind!r}")


def _as_text(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_as_text(v)}" for k, v in value.items() if v is not None)
    if isinstance(value, list):
        return ", ".join(_as_text(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# -- results -------------------------------------------------------------------------------


class QuestionResult(BaseModel):
    id: str
    tender: str
    question: str
    field_path: str
    critical: bool
    mode: str
    source: str
    answered: bool
    correct: bool
    answer: str
    citations_total: int
    citations_resolved: int
    cost_usd: float
    seconds: float
    error: str | None = None


class CrossResult(BaseModel):
    id: str
    question: str
    parsed_query: dict[str, Any] | None
    query_as_expected: bool
    matched: list[str]
    expected: list[str]
    set_correct: bool


class Summary(BaseModel):
    questions: int
    answered: int
    correct: int
    accuracy: float
    critical: int
    critical_correct: int
    critical_accuracy: float
    citations_total: int
    citations_resolved: int
    citation_resolution_rate: float
    by_mode: dict[str, dict[str, Any]]
    cross_questions: int
    cross_query_read: int
    cross_set_correct: int
    cost_usd: float
    seconds: float


def summarise(results: list[QuestionResult], cross: list[CrossResult]) -> Summary:
    def rate(num: int, den: int) -> float:
        return round(num / den, 4) if den else 0.0

    by_mode: dict[str, dict[str, Any]] = {}
    for r in results:
        bucket = by_mode.setdefault(
            r.mode, {"questions": 0, "correct": 0, "citations_total": 0, "citations_resolved": 0}
        )
        bucket["questions"] += 1
        bucket["correct"] += int(r.correct)
        bucket["citations_total"] += r.citations_total
        bucket["citations_resolved"] += r.citations_resolved
    for bucket in by_mode.values():
        bucket["accuracy"] = rate(bucket["correct"], bucket["questions"])
        bucket["citation_resolution_rate"] = rate(
            bucket["citations_resolved"], bucket["citations_total"]
        )
    critical = [r for r in results if r.critical]
    total_c = sum(r.citations_total for r in results)
    resolved_c = sum(r.citations_resolved for r in results)
    return Summary(
        questions=len(results),
        answered=sum(1 for r in results if r.answered),
        correct=sum(1 for r in results if r.correct),
        accuracy=rate(sum(1 for r in results if r.correct), len(results)),
        critical=len(critical),
        critical_correct=sum(1 for r in critical if r.correct),
        critical_accuracy=rate(sum(1 for r in critical if r.correct), len(critical)),
        citations_total=total_c,
        citations_resolved=resolved_c,
        citation_resolution_rate=rate(resolved_c, total_c),
        by_mode=by_mode,
        cross_questions=len(cross),
        cross_query_read=sum(1 for c in cross if c.query_as_expected),
        cross_set_correct=sum(1 for c in cross if c.set_correct),
        cost_usd=round(sum(r.cost_usd for r in results), 4),
        seconds=round(sum(r.seconds for r in results), 1),
    )


def markdown(summary: Summary, results: list[QuestionResult], cross: list[CrossResult]) -> str:
    lines = [
        "# Block 5 d: question eval over the gold tenders",
        "",
        f"{summary.questions} questions, {summary.answered} answered, "
        f"**{summary.correct} correct ({summary.accuracy:.1%})**; critical "
        f"{summary.critical_correct}/{summary.critical} ({summary.critical_accuracy:.1%}); "
        f"citations located {summary.citations_resolved}/{summary.citations_total} "
        f"(**{summary.citation_resolution_rate:.1%}**); cost USD {summary.cost_usd}; "
        f"{summary.seconds} s.",
        "",
        "| Route | Questions | Correct | Accuracy | Citations located |",
        "| --- | --- | --- | --- | --- |",
    ]
    for mode, b in sorted(summary.by_mode.items()):
        lines.append(
            f"| {mode} | {b['questions']} | {b['correct']} | {b['accuracy']:.1%} | "
            f"{b['citations_resolved']}/{b['citations_total']} "
            f"({b['citation_resolution_rate']:.1%}) |"
        )
    lines += [
        "",
        f"Cross-tender: {summary.cross_query_read}/{summary.cross_questions} questions read into "
        f"the expected query; {summary.cross_set_correct}/{summary.cross_questions} structured "
        "queries matched exactly the expected gold tenders.",
        "",
        "| Id | Tender | Question | Route | Source | Correct | Citations | Answer |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        answer = (r.error or r.answer).replace("|", "/").replace("\n", " ")
        if len(answer) > 160:
            answer = answer[:157] + "..."
        lines.append(
            f"| {r.id} | {r.tender} | {r.question} | {r.mode} | {r.source} | "
            f"{'yes' if r.correct else 'NO'} | {r.citations_resolved}/{r.citations_total} | "
            f"{answer} |"
        )
    lines += [
        "",
        "| Id | Question | Read as | Matched | Expected |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in cross:
        lines.append(
            f"| {c.id} | {c.question} | "
            f"{json.dumps(c.parsed_query) if c.parsed_query else 'not read'}"
            f"{'' if c.query_as_expected else ' (differs)'} | {', '.join(c.matched)} | "
            f"{', '.join(c.expected)}{'' if c.set_correct else ' (differs)'} |"
        )
    return "\n".join(lines) + "\n"


def write_results(
    summary: Summary, results: list[QuestionResult], cross: list[CrossResult], root: Path
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = root / f"ask-eval-{stamp}.json"
    md_path = root / f"ask-eval-{stamp}.md"
    json_path.write_text(
        json.dumps(
            {
                "summary": summary.model_dump(),
                "results": [r.model_dump() for r in results],
                "cross": [c.model_dump() for c in cross],
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    md_path.write_text(markdown(summary, results, cross), encoding="utf-8")
    return json_path, md_path


# -- the run -------------------------------------------------------------------------------


def load_questions(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def run(path: Path = QUESTIONS, only: set[str] | None = None) -> tuple[Summary, Path, Path]:
    data = load_questions(path)
    services = build_services()
    settings: Settings = services.settings
    schemas = services.schemas
    embedders = make_embedders(settings)
    store = ChunkStores(settings).for_tenant(settings.tenant_id)
    ask = AskService(
        services.llm,
        services.catalog,
        schemas,
        services.tenders,
        Retriever(store, embedders, top_k=settings.ask_top_k),
        settings,
    )
    results: list[QuestionResult] = []
    cross: list[CrossResult] = []
    with services.session_factory() as session:
        by_slug = {t.slug: t for t in services.tenders.all(session)}
        for q in data["questions"]:
            if only and q["id"] not in only:
                continue
            tender = by_slug.get(q["tender"])
            started = time.monotonic()
            if tender is None:
                results.append(_failed(q, "tender not found", started))
                continue
            try:
                answer: AskAnswer = ask.ask(session, tender, q["question"], created_by=ACTOR)
            except AskError as exc:
                results.append(_failed(q, str(exc), started))
                continue
            results.append(
                QuestionResult(
                    id=q["id"],
                    tender=q["tender"],
                    question=q["question"],
                    field_path=q["field_path"],
                    critical=bool(q.get("critical")),
                    mode=answer.mode,
                    source=answer.source,
                    answered=answer.answered,
                    correct=answer.answered and matches(q["expect"], answer.answer, answer.value),
                    answer=answer.answer,
                    citations_total=answer.citations_total,
                    citations_resolved=answer.citations_resolved,
                    cost_usd=answer.cost_usd,
                    seconds=round(time.monotonic() - started, 2),
                )
            )
            mark = "ok " if results[-1].correct else "NO "
            print(f"{q['id']} {answer.mode:9} {mark} {q['question']}")
        gold_slugs = {q["tender"] for q in data["questions"]}
        gold_tenders = [t for s, t in by_slug.items() if s in gold_slugs]
        for cq in data.get("cross_questions", []):
            if only and cq["id"] not in only:
                continue
            parsed = None
            for tender_type in sorted({t.tender_type for t in gold_tenders}):
                parsed = parse_cross_question(
                    cq["question"], services.catalog.get(tender_type).schema
                )
                if parsed is not None:
                    break
            wanted = cq["query"]
            as_expected = parsed is not None and (
                parsed.field_path,
                parsed.operator,
                _as_text(parsed.value).lower(),
            ) == (wanted["field_path"], wanted["operator"], _as_text(wanted["value"]).lower())
            structured = CrossQuery(
                field_path=wanted["field_path"], operator=wanted["operator"], value=wanted["value"]
            )
            found = search_facts(
                session, services.catalog, gold_tenders, structured, question=cq["question"]
            )
            matched = sorted(h.slug or h.tender_id for h in found.matched)
            cross.append(
                CrossResult(
                    id=cq["id"],
                    question=cq["question"],
                    parsed_query=parsed.model_dump() if parsed else None,
                    query_as_expected=as_expected,
                    matched=matched,
                    expected=sorted(cq["expect"]),
                    set_correct=matched == sorted(cq["expect"]),
                )
            )
            mark = "ok " if cross[-1].set_correct else "NO "
            print(f"{cq['id']} cross     {mark} {cq['question']}")
    summary = summarise(results, cross)
    json_path, md_path = write_results(summary, results, cross, RESULTS_ROOT)
    return summary, json_path, md_path


def _failed(q: dict[str, Any], error: str, started: float) -> QuestionResult:
    return QuestionResult(
        id=q["id"],
        tender=q["tender"],
        question=q["question"],
        field_path=q["field_path"],
        critical=bool(q.get("critical")),
        mode="error",
        source="none",
        answered=False,
        correct=False,
        answer="",
        citations_total=0,
        citations_resolved=0,
        cost_usd=0.0,
        seconds=round(time.monotonic() - started, 2),
        error=error,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv[1:])
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    summary, json_path, md_path = run(args.questions, only)
    print(
        f"\n{summary.correct}/{summary.questions} correct ({summary.accuracy:.1%}); critical "
        f"{summary.critical_correct}/{summary.critical}; citations located "
        f"{summary.citations_resolved}/{summary.citations_total} "
        f"({summary.citation_resolution_rate:.1%}); cross {summary.cross_set_correct}/"
        f"{summary.cross_questions}; USD {summary.cost_usd}\nwrote {json_path} and {md_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
