"""Every match rule of the runner, on the real value types of the tender schemas."""

import json
from pathlib import Path
from typing import Any

import pytest

from core.schemas import FieldDef, KeyDef, SchemaRegistry
from evals.gold import GoldField, GoldRecord
from evals.runner import (
    CandidateUnderTest,
    FieldScore,
    markdown_table,
    match_record,
    match_scalar,
    normalise_text,
    score_field,
    summarise,
    write_results,
)
from tender.services.packs import build_registry


@pytest.fixture(scope="module")
def registry() -> SchemaRegistry:
    return build_registry()[0]


def record() -> GoldRecord:
    return GoldRecord(
        tender_id="t1",
        slug="acme-solar",
        tender_type="solar",
        issuing_agency="Acme",
        title="600 MW solar",
        schema_version="v2",
        reviewed_version=1,
        reviewer="Asha Rao",
        completed_at="2026-10-06T10:00:00+00:00",
        snapshot_id="s1",
        made_at="2026-10-06T10:01:00+00:00",
        fields=[],
    )


def gold(
    value_type: str, final: Any, decision: str = "approved", pages: list[int] | None = None
) -> GoldField:
    return GoldField(
        field_path="core.x.y",
        section="x",
        value_type=value_type,
        required=True,
        decision=decision,
        final_value=final,
        version_no=1,
        evidence_pages=[3] if pages is None else pages,
        reviewer="Asha Rao",
        decided_at="2026-10-06T09:00:00+00:00",
        note=None,
        candidate=None,
    )


def definition(value_type: str, **extra: Any) -> FieldDef:
    return FieldDef(path="core.x.y", label="Y", group="x", value_type=value_type, **extra)


def score(
    registry: SchemaRegistry,
    value_type: str,
    final: Any,
    candidate: Any,
    *,
    decision: str = "approved",
    pages: list[int] | None = None,
    **extra: Any,
) -> FieldScore:
    found = score_field(
        record(),
        gold(value_type, final, decision),
        definition(value_type, **extra),
        registry,
        None
        if candidate is None and decision == "missing"
        else CandidateUnderTest(id="c1", value=candidate, pages=[3] if pages is None else pages),
    )
    assert found is not None
    return found


@pytest.mark.parametrize(
    ("value_type", "gold_value", "candidate", "expected"),
    [
        ("enum", "annual", "annual", "correct"),
        ("enum", "annual", "monthly", "wrong_value"),
        ("int", 600, 600, "correct"),
        ("int", 600, 601, "wrong_value"),
        ("bool", True, "yes", "correct"),
        ("time", "11:00", "11:00", "correct"),
        ("duration_months", 24, 24, "correct"),
        ("duration_months", 24, 25, "wrong_value"),
    ],
)
def test_enums_whole_numbers_booleans_and_times_match_exactly(
    registry: SchemaRegistry, value_type: str, gold_value: Any, candidate: Any, expected: str
) -> None:
    extra = {"enum_values": ["annual", "monthly"]} if value_type == "enum" else {}
    assert score(registry, value_type, gold_value, candidate, **extra).outcome == expected


@pytest.mark.parametrize(
    "printed",
    [
        "2026-03-12",
        "12/03/2026",
        "12.03.2026",
        "12-03-2026",
        "12-Mar-2026",
        "12 March 2026",
        "12th March 2026",
        "March 12, 2026",
    ],
)
def test_dates_match_after_parsing_the_forms_indian_documents_use(
    registry: SchemaRegistry, printed: str
) -> None:
    assert score(registry, "date", "2026-03-12", printed).outcome == "correct"


def test_a_date_of_another_day_is_wrong_and_an_unreadable_one_is_a_matter_of_form(
    registry: SchemaRegistry,
) -> None:
    assert score(registry, "date", "2026-03-12", "13/03/2026").outcome == "wrong_value"
    assert score(registry, "date", "2026-03-12", "2026/03/12").outcome == "format"
    assert score(registry, "date", "2026-03-12", "yesterday").outcome == "wrong_value"


@pytest.mark.parametrize(
    ("value_type", "gold_value", "candidate", "expected"),
    [
        ("money_inr", 928000, 928000, "correct"),
        ("money_inr", 928000, 932000, "correct"),  # 0.43%: within the half-percent band
        ("money_inr", 928000, 933000, "wrong_value"),  # 0.54%
        ("money_inr", 928000, "9,28,000", "correct"),
        ("decimal", 1.5, 1.504, "correct"),
        ("decimal", 1.5, 1.6, "wrong_value"),
        ("percent", 10, 10.04, "correct"),
        ("mw", 600, 600.0, "correct"),
        ("money_inr", 0, 0, "correct"),
        ("money_inr", 0, 1, "wrong_value"),
    ],
)
def test_money_decimals_and_percentages_match_within_half_a_percent(
    registry: SchemaRegistry, value_type: str, gold_value: Any, candidate: Any, expected: str
) -> None:
    assert score(registry, value_type, gold_value, candidate).outcome == expected


def test_text_matches_once_normalised_and_the_fuzzy_score_is_reported_not_counted(
    registry: SchemaRegistry,
) -> None:
    same = score(
        registry,
        "text",
        "Solar Energy Corporation of India Ltd.",
        "solar  energy corporation of india ltd",
    )
    assert same.outcome == "correct" and same.fuzzy == 100.0
    near = score(
        registry, "text", "Solar Energy Corporation of India", "Solar Energy Corp. of India"
    )
    assert near.outcome == "wrong_value" and near.fuzzy is not None and 60 < near.fuzzy < 100
    assert normalise_text("  SECI – Solar  ") == "seci solar"


def test_long_text_needs_human_judgement_and_is_not_counted(registry: SchemaRegistry) -> None:
    found = score(registry, "long_text", "A long summary.", "Another long summary.")
    assert found.outcome == "needs_judgement" and not found.counted
    assert summarise([found]).scored == 0 and summarise([found]).needs_judgement == 1


def test_a_list_of_text_matches_as_a_set(registry: SchemaRegistry) -> None:
    assert score(registry, "list_text", ["Solar", "Wind"], ["wind", "solar"]).outcome == "correct"
    assert score(registry, "list_text", ["Solar", "Wind"], ["solar"]).outcome == "wrong_value"


def test_a_record_is_scored_key_by_key(registry: SchemaRegistry) -> None:
    keys = [
        KeyDef(name="basis", value_type="enum", enum_values=["per_mw", "lump_sum"]),
        KeyDef(name="rate_inr", value_type="money_inr"),
        KeyDef(name="note", value_type="text"),
    ]
    gold_value = {"basis": "per_mw", "rate_inr": 928000, "note": None}
    same, keyed = match_record(keys, registry, gold_value, {"basis": "per_mw", "rate_inr": 930000})
    assert same == "correct" and keyed == {"basis": "correct", "rate_inr": "correct"}
    differ, keyed = match_record(
        keys, registry, gold_value, {"basis": "lump_sum", "rate_inr": None, "note": "see 12.3"}
    )
    assert differ == "wrong_value"
    assert keyed == {"basis": "wrong_value", "rate_inr": "missing", "note": "extra"}
    listed, keyed = match_record(keys, registry, [gold_value], [gold_value, gold_value])
    assert listed == "wrong_value" and keyed == {"items": "2 given, 1 in gold"}
    listed, keyed = match_record(keys, registry, [gold_value, gold_value], [gold_value, gold_value])
    assert listed == "correct" and keyed == {
        "1.basis": "correct", "1.rate_inr": "correct", "2.basis": "correct", "2.rate_inr": "correct"
    }  # fmt: skip


def test_a_record_field_goes_through_the_keys(registry: SchemaRegistry) -> None:
    keys = [KeyDef(name="rate_inr_per_mw", value_type="money_inr")]
    found = score(
        registry, "record", {"rate_inr_per_mw": 928000}, {"rate_inr_per_mw": 928000}, keys=keys
    )
    assert found.outcome == "correct" and found.key_outcomes == {"rate_inr_per_mw": "correct"}


def test_an_abstention_is_right_when_the_document_states_nothing(registry: SchemaRegistry) -> None:
    assert (
        score(registry, "money_inr", None, None, decision="not_in_document").outcome
        == "correct_abstention"
    )
    assert score(registry, "money_inr", None, 5, decision="not_in_document").outcome == "extra"
    missing = score_field(
        record(), gold("money_inr", 928000), definition("money_inr"), registry, None
    )
    assert missing is not None and missing.outcome == "missing"
    assert score(registry, "money_inr", 928000, None).outcome == "missing"
    # A field without a decision is not scored at all.
    assert (
        score_field(
            record(), gold("money_inr", 1, decision=None), definition("money_inr"), registry, None
        )
        is None
    )  # type: ignore[arg-type]


def test_evidence_is_scored_apart_from_the_value(registry: SchemaRegistry) -> None:
    right_page = score(registry, "money_inr", 928000, 928000, pages=[3])
    wrong_page = score(registry, "money_inr", 928000, 928000, pages=[7])
    assert (right_page.correct, right_page.evidence_ok) == (True, True)
    assert (wrong_page.correct, wrong_page.evidence_ok) == (True, False)
    no_pages = score_field(
        record(), gold("money_inr", 928000, pages=[]), definition("money_inr"), registry,
        CandidateUnderTest(id="c", value=928000, pages=[1]),
    )  # fmt: skip
    assert no_pages is not None and no_pages.evidence_ok is None
    summary = summarise([right_page, wrong_page])
    assert (summary.value_accuracy, summary.evidence_accuracy) == (1.0, 0.5)


def test_summary_buckets_and_results_file(registry: SchemaRegistry, tmp_path: Path) -> None:
    scores = [
        score(registry, "money_inr", 928000, 928000),
        score(registry, "money_inr", 928000, 1),
        score(registry, "long_text", "a", "b"),
    ]
    summary = summarise(scores)
    assert summary.scored == 2 and summary.value_correct == 1 and summary.value_accuracy == 0.5
    assert summary.by_type["solar"]["n"] == 2 and summary.by_section["x"]["misses"] == 1
    assert summary.by_type_field["solar"]["core.x.y"]["accuracy"] == 0.5
    assert summary.misses[0]["candidate"] == 1 and summary.misses[0]["gold"] == 928000
    table = markdown_table(summary)
    assert "| solar | `core.x.y` | 50% | 2 | 100% |" in table
    assert "| acme-solar | `core.x.y` | wrong_value | 1 | 928000 |" in table
    path, written = write_results(scores, label="unit", root=tmp_path, prompt="commercial/v3")
    data = json.loads(path.read_text())
    assert data["prompt"] == "commercial/v3" and len(data["scores"]) == 3
    assert written.value_accuracy == 0.5 and path.name.endswith("-unit.json")


def test_match_scalar_handles_values_that_are_not_of_the_type() -> None:
    assert match_scalar("money_inr", "number", "x", 1) == ("wrong_value", None)
    assert match_scalar("text", "string", "", "") == ("correct", 0.0)
