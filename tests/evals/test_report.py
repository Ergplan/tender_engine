"""The reliability report on two fixture gold records, and the stability bar."""

import json
from collections import Counter
from pathlib import Path

from evals.gold import GoldField, GoldRecord
from evals.report import (
    Sitting,
    accuracy_by_prompt_version,
    evaluated_scores,
    prompt_comparison,
    recommendation,
    render_log,
    render_report,
    stability,
    tender_lines,
)
from evals.runner import FieldScore, summarise

RATE = "core.guarantees.emd_per_mw_inr"
DEADLINE = "core.key_dates.bid_submission_deadline"
AGENCY = "core.identity_and_scope.issuing_agency"


def gold(slug: str, tender_type: str = "solar") -> GoldRecord:
    def field(
        path: str, section: str, value_type: str, value: object, required: bool = True
    ) -> GoldField:
        return GoldField(
            field_path=path, section=section, value_type=value_type, required=required,
            decision="approved", final_value=value, version_no=1, evidence_pages=[1],
            reviewer="Asha Rao", decided_at="2026-10-06T09:00:00+00:00", note=None, candidate=None,
        )  # fmt: skip

    return GoldRecord(
        tenant_id="ergplan",
        tender_id=slug, slug=slug, tender_type=tender_type, issuing_agency="SECI",
        title=slug, schema_version="v2", reviewed_version=1, reviewer="Asha Rao",
        completed_at="2026-10-06T10:00:00+00:00", snapshot_id="s",
        made_at="2026-10-06T10:01:00+00:00",
        fields=[
            field(RATE, "guarantees", "money_inr", 928000),
            field(DEADLINE, "key_dates", "date", "2026-03-30"),
            field(AGENCY, "identity_and_scope", "text", "SECI", required=False),
        ],
    )  # fmt: skip


def score(
    slug: str,
    path: str,
    section: str,
    outcome: str,
    version: str = "v1",
    required: bool = True,
    tender_type: str = "solar",
) -> FieldScore:
    return FieldScore(
        slug=slug, tender_type=tender_type, issuing_agency="SECI", field_path=path, section=section,
        value_type="money_inr", required=required, outcome=outcome, gold_value=1,  # type: ignore[arg-type]
        candidate_value=1 if outcome == "correct" else 2, evidence_ok=outcome == "correct",
        gold_pages=[1], candidate_pages=[1], prompt_version=version,
        prompt_name=f"extract/{section}",
    )  # fmt: skip


def two_records() -> tuple[list[GoldRecord], list[FieldScore]]:
    records = [gold("seci-solar-1"), gold("seci-solar-2")]
    scores = [
        score("seci-solar-1", RATE, "guarantees", "correct", "v1"),
        score("seci-solar-1", DEADLINE, "key_dates", "correct", "v2"),
        score("seci-solar-1", AGENCY, "identity_and_scope", "correct", "v1", required=False),
        score("seci-solar-2", RATE, "guarantees", "correct", "v1"),
        score("seci-solar-2", DEADLINE, "key_dates", "correct", "v2"),
        score("seci-solar-2", AGENCY, "identity_and_scope", "wrong_value", "v1", required=False),
    ]
    return records, scores


def test_the_bar_is_met_with_two_reviews_per_type_and_required_fields_at_ninety_percent() -> None:
    records, scores = two_records()
    bar = stability(records, summarise(scores), scores, Counter({"solar": 3, "bess": 1}))
    assert bar.met and bar.types_with_two_or_more_in_set == ["solar"]
    assert bar.required_accuracy == 1.0
    assert bar.prompt_versions_seen == ["extract/guarantees v1", "extract/key_dates v2"]
    assert bar.prompt_versions_below_bar == [] and len(bar.reasons) == 1
    assert bar.reasons[0].startswith("required-field accuracy by section prompt")


def test_the_bar_names_each_shortfall() -> None:
    records, scores = two_records()
    # One review for a type with two tenders; a required field wrong in one of two reviews
    # puts it at 50%, under the floor, and the required accuracy at 75%, under the bar.
    scores[3] = score("seci-solar-2", RATE, "guarantees", "wrong_value", "v1")
    bar = stability(records[:1], summarise(scores), scores, Counter({"solar": 2, "wind": 2}))
    assert not bar.met
    assert bar.types_short_of_two_reviews == ["solar", "wind"]
    assert bar.required_fields_below_floor == [RATE] and bar.required_accuracy == 0.75
    assert "fewer than 2 reviewed tenders for: solar, wind" in bar.reasons
    assert "required-field accuracy 75% is below 90%" in bar.reasons
    assert "required fields below 75%: 1" in bar.reasons
    assert bar.prompt_versions_below_bar == ["extract/guarantees v1 (50%)"]
    assert "below 90% on required fields under: extract/guarantees v1 (50%)" in bar.reasons
    empty = stability([], summarise([]), [], Counter())
    assert empty.reasons[0] == "no gold record yet" and not empty.met


def test_a_recommendation_per_section() -> None:
    assert recommendation({"n": 1, "accuracy": 0.0}, []) == "not enough reviews yet"
    assert recommendation({"n": 4, "accuracy": 1.0}, []) == "stable"
    assert (
        recommendation({"n": 4, "accuracy": 0.5}, [{"outcome": "format"}, {"outcome": "format"}])
        == "needs validator"
    )
    assert (
        recommendation(
            {"n": 4, "accuracy": 0.5}, [{"outcome": "wrong_value"}, {"outcome": "missing"}]
        )
        == "needs prompt work"
    )
    assert (
        recommendation({"n": 4, "accuracy": 0.5}, [{"outcome": "needs_judgement"}])
        == "needs schema change"
    )


def test_the_report_and_the_log_on_two_fixture_records(tmp_path: Path) -> None:
    records, scores = two_records()
    timings = {
        "seci-solar-1": Sitting(
            started="2026-10-06T08:00:00",
            completed="2026-10-06T10:00:00+00:00",
            deciding_minutes=42,
            sittings=2,
            decisions=3,
        ),
    }
    (tmp_path / "20261006T100000Z-latest.json").write_text(json.dumps({
        "made_at": "2026-10-06T10:00:00+00:00", "tenant_id": "ergplan", "label": "latest",
        "prompt": None, "summary": {"value_accuracy": 0.9, "evidence_accuracy": 1.0, "scored": 6},
    }))  # fmt: skip
    (tmp_path / "20261006T110000Z-commercial-v3.json").write_text(json.dumps({
        "made_at": "2026-10-06T11:00:00+00:00", "tenant_id": "ergplan", "label": "commercial-v3",
        "prompt": "commercial/v3",
        "summary": {"value_accuracy": 0.95, "evidence_accuracy": 1.0, "scored": 6},
        "scores": [score("x", RATE, "guarantees", "wrong_value", "v3").model_dump()],
    }))  # fmt: skip
    (tmp_path / "20261006T120000Z-other.json").write_text(json.dumps({
        "made_at": "2026-10-06T12:00:00+00:00", "tenant_id": "someone-else", "label": "latest",
        "prompt": None, "summary": {"value_accuracy": 0.1, "evidence_accuracy": 0.1, "scored": 1},
    }))  # fmt: skip
    (tmp_path / "broken.json").write_text("{")
    comparisons = prompt_comparison("ergplan", tmp_path)
    assert [c["prompt"] for c in comparisons] == [None, "commercial/v3"]
    # An earlier prompt evaluation counts for the bar even once superseded in review.
    history = evaluated_scores("ergplan", tmp_path)
    assert [h.prompt_version for h in history] == ["v3"]
    bar = stability(records, summarise(scores), scores, Counter({"solar": 3}), history)
    assert not bar.met and bar.prompt_versions_below_bar == ["extract/guarantees v3 (0%)"]
    assert evaluated_scores("someone-else", tmp_path) == []

    report = render_report(records, scores, Counter({"solar": 3, "bess": 1}), timings, comparisons)
    assert "| solar | 3 | 2 | seci-solar-1, seci-solar-2 |" in report
    assert "| bess | 1 | 0 | - |" in report
    assert "- Value accuracy: **83%** on 6 scored fields (5 correct)" in report
    assert "| guarantees | 100% | 2 | 100% | stable |" in report
    assert "| identity_and_scope | 50% | 2 | 50% | needs prompt work |" in report
    assert f"| `{AGENCY}` | 50% | 2 | 1 | wrong_value 1 |" in report
    assert "| 20261006T110000Z-commercial-v3.json | commercial/v3 | 95% | 100% | 6 |" in report
    assert "| seci-solar-1 | Asha Rao | 2 | 42 | 3 | 2026-10-06 10:00 |" in report
    assert "| seci-solar-2 | Asha Rao | - | - | - | 2026-10-06 10:00 |" in report
    assert "**Met.**" in report

    lines = tender_lines(records, scores, timings)
    assert lines[1].notable_misses == [f"{AGENCY} (wrong_value)"] and lines[1].time is None
    log = render_log(lines)
    first, second = (line for line in log.splitlines() if line.startswith("| seci-solar-"))
    assert first == (
        "| seci-solar-1 | solar | Asha Rao | 2026-10-06 08:00 | 2026-10-06 10:00 "
        "| 3 | 0: - | 0 | - |"
    )
    assert second == (
        "| seci-solar-2 | solar | Asha Rao | - | 2026-10-06 10:00 | 3 | 0: - | 0 "
        f"| {AGENCY} (wrong_value) |"
    )


def test_the_last_two_versions_of_each_prompt_are_judged_apart() -> None:
    scores = [
        score("a", RATE, "guarantees", "correct", "v1"),
        score("b", RATE, "guarantees", "wrong_value", "v2"),
        score("c", RATE, "guarantees", "correct", "v3"),
        score("d", RATE, "guarantees", "correct", "v10"),
        score("a", DEADLINE, "key_dates", "correct", "v1"),
    ]
    assert accuracy_by_prompt_version(scores) == {
        "extract/guarantees": {"v3": 1.0, "v10": 1.0},
        "extract/key_dates": {"v1": 1.0},
    }
    # The same reading scored twice is one observation; the later score of it wins.
    twice = scores + [score("c", RATE, "guarantees", "wrong_value", "v3")]
    assert accuracy_by_prompt_version(twice)["extract/guarantees"] == {"v3": 0.0, "v10": 1.0}
    assert accuracy_by_prompt_version(twice + [scores[2]])["extract/guarantees"]["v3"] == 1.0
