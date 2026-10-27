"""The match rules of the question eval (Block 5 d) and the shape of its set: fifty
questions, each on a gold tender's decided field; dates, Indian number scales, phrases and
booleans are recognised in prose; the summary cuts critical questions and routes."""

from datetime import date
from pathlib import Path

import yaml

from evals.ask_eval import (
    QUESTIONS,
    CrossResult,
    QuestionResult,
    dates_in,
    matches,
    numbers_in,
    summarise,
)
from evals.gold import load_all

ROOT = Path(__file__).resolve().parents[2]


def test_the_set_has_fifty_questions_on_decided_gold_fields() -> None:
    data = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    questions = data["questions"]
    assert len(questions) == 50
    assert len({q["id"] for q in questions}) == 50
    gold = {record.slug: record for record in load_all(root=ROOT / "evals" / "gold")}
    for q in questions:
        record = gold[q["tender"]]
        decided = {f.field_path for f in record.fields if f.decision == "approved"}
        assert q["field_path"] in decided, f"{q['id']}: {q['field_path']} is not decided in gold"
        assert q["expect"]["kind"] in {"date", "number", "text", "bool"}
    assert len(data["cross_questions"]) == 3


def test_dates_are_read_in_every_written_form() -> None:
    text = "Bids close on 30.10.2026 (also written 30 October 2026, 2026-10-30, 30/10/2026)."
    assert dates_in(text) == {date(2026, 10, 30)}
    assert matches({"kind": "date", "value": "2026-10-30"}, text)
    assert not matches({"kind": "date", "value": "2026-10-31"}, text)


def test_numbers_match_through_indian_scales_and_commas() -> None:
    assert 8751400.0 in numbers_in("a turnover of Rs. 87.514 Lakh per MW")
    assert 40000000.0 in numbers_in("INR 4 crore")
    assert 965400000.0 in numbers_in("Rs 96.54 Crore") or any(
        abs(n - 965400000) < 965400000 * 0.005 for n in numbers_in("Rs 96.54 Crore")
    )
    assert numbers_in("availability of 85%")[:1] == [85.0]
    assert matches({"kind": "number", "value": 100000000}, "capped at Rs. 10,00,00,000 per project")
    assert matches({"kind": "number", "value": 5.8}, "", value=5.8)
    assert not matches({"kind": "number", "value": 600}, "a 1200 MW tender")


def test_text_and_booleans() -> None:
    assert matches({"kind": "text", "any_of": ["west bengal", "wbsedcl"]}, "sold to WBSEDCL.")
    assert not matches({"kind": "text", "any_of": ["west bengal"]}, "sold to a discom.")
    assert matches({"kind": "bool", "value": True}, "Yes, a consortium is allowed to bid.")
    assert not matches({"kind": "bool", "value": True}, "A consortium is not allowed.")
    assert matches({"kind": "bool", "value": True}, "", value=True)
    assert not matches({"kind": "bool", "value": True}, "", value=False)


def test_the_summary_cuts_critical_questions_and_routes() -> None:
    def result(
        id_: str, mode: str, correct: bool, critical: bool, cited: int, located: int
    ) -> QuestionResult:
        return QuestionResult(
            id=id_, tender="t", question="q", field_path="f", critical=critical, mode=mode,
            source="machine", answered=True, correct=correct, answer="a",
            citations_total=cited, citations_resolved=located, cost_usd=0.01, seconds=1.0,
        )  # fmt: skip

    results = [
        result("1", "field", True, True, 1, 1),
        result("2", "field", False, True, 1, 1),
        result("3", "retrieval", True, False, 3, 2),
        result("4", "retrieval", True, True, 2, 2),
    ]
    cross = [
        CrossResult(
            id="x",
            question="q",
            parsed_query=None,
            query_as_expected=False,
            matched=["a"],
            expected=["a"],
            set_correct=True,
        )  # fmt: skip
    ]
    summary = summarise(results, cross)
    assert (summary.correct, summary.accuracy) == (3, 0.75)
    assert (summary.critical, summary.critical_correct) == (3, 2)
    assert (summary.citations_total, summary.citations_resolved) == (7, 6)
    assert summary.by_mode["retrieval"]["accuracy"] == 1.0
    assert summary.by_mode["retrieval"]["citation_resolution_rate"] == 0.8
    assert (summary.cross_query_read, summary.cross_set_correct) == (0, 1)
    assert summary.cost_usd == 0.04
