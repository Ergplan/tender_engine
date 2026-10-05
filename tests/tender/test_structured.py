"""The two checks on structured fields: numbers are printed in the field's own quotes, and
a structured key agrees with its scalar."""

from typing import Any

import pytest

from core.schemas import FieldDef, KeyDef
from tender.domain_packs.core.structured import (
    CORE_PAIRS,
    agreement,
    numbers_in,
    structured_agrees_with_scalar,
    unquoted_numbers,
)
from tender.domain_packs.power.validation.rules import power_structured_agrees_with_scalar

EMD, EMD_S = "core.guarantees.emd_per_mw_inr", "core.guarantees.emd_structured"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("INR 9,28,000 x Rated Installed Capacity", {928000}),
        ("subject to a maximum of Rs. 10 Crores per Project", {10, 100000000}),
        ("Rs. 6.43 crore and 5 lakh", {6.43, 64300000, 5, 500000}),
        ("PSM charges of 2 paisa per unit", {2, 0.02}),
        ("one and a half times the tariff", {1, 1.5, 0.5}),
        ("calculated @ one and half times of the PPA tariff", {1, 1.5, 0.5}),
        ("for twenty-four months, twice the tariff", {20, 24, 4, 2}),
        ("beyond 175 hours in a year at 0.5%", {175, 0.5}),
        ("within 05:00-10:00 Hrs", {5, 0, 10}),
    ],
)
def test_numbers_are_read_from_a_passage(text: str, expected: set[float]) -> None:
    assert numbers_in(text) == {float(number) for number in expected}


def field() -> FieldDef:
    keys = [
        KeyDef(name="basis", value_type="enum", enum_values=["a"]),
        KeyDef(name="rate_inr", value_type="money_inr"),
        KeyDef(name="multiple", value_type="decimal"),
        KeyDef(name="upper", value_type="decimal", unit="percent of declared CUF"),
        KeyDef(name="lower", value_type="decimal", unit="percent of declared CUF"),
        KeyDef(name="revolving", value_type="bool"),
        KeyDef(
            name="parts",
            value_type="list",
            keys=[KeyDef(name="name"), KeyDef(name="rate", value_type="money_inr")],
        ),
    ]
    return FieldDef(path="t.r", label="R", group="g", value_type="record", keys=keys)


def test_every_number_must_be_printed_in_the_quotes() -> None:
    value: dict[str, Any] = {
        "basis": "a",
        "rate_inr": 100000000,
        "multiple": 1.5,
        "upper": 110,
        "lower": 85,
        "revolving": True,
        "parts": [{"name": "solar", "rate": 928000}, {"name": "wind", "rate": 1264000}],
    }
    quotes = [
        "INR 9,28,000 x solar (MW) + INR 12,64,000 x wind (MW), maximum of Rs. 10 Crores",
        "one and a half times the tariff; CUF within +10% and -15% of the declared value",
    ]
    assert unquoted_numbers(value, field(), quotes) == []
    # "10 Crores" also prints the 10 that +10% would: the check is on numbers, not meaning.
    assert unquoted_numbers(value, field(), quotes[:1]) == ["multiple 1.5", "lower 85"]
    value["parts"][1]["rate"] = 1246000
    assert unquoted_numbers(value, field(), quotes) == ["parts 2.rate 1.246e+06"]
    # Text, choices and yes/no are not numbers; a key that is not stated is not checked.
    assert unquoted_numbers({"basis": "a", "revolving": False, "rate_inr": None}, field(), []) == []


def test_a_multiple_may_be_printed_as_a_percentage() -> None:
    assert unquoted_numbers({"multiple": 0.5}, field(), ["50% of the Applicable Tariff"]) == []
    assert unquoted_numbers({"multiple": 1.1}, field(), ["110% of average monthly billing"]) == []
    assert unquoted_numbers({"rate_inr": 0.5}, field(), ["50% of the tariff"]) == ["rate_inr 0.5"]


def test_a_list_of_records_names_the_item() -> None:
    listed = field().model_copy(update={"value_type": "record_list"})
    value = [{"multiple": 1.5}, {"multiple": 2}]
    assert unquoted_numbers(value, listed, ["1.5 times the tariff"]) == ["2.multiple 2"]


def test_sibling_and_scalar_agree_or_the_pair_fails() -> None:
    same = structured_agrees_with_scalar({EMD: 928000, EMD_S: {"rate_inr_per_mw": 928000.0}})
    assert [(o.passed, o.field_paths) for o in same] == [(True, (EMD, EMD_S))]
    differ = structured_agrees_with_scalar({EMD: 928000, EMD_S: {"rate_inr_per_mw": 982000}})
    assert not differ[0].passed and "982000" in differ[0].message
    only_scalar = structured_agrees_with_scalar({EMD: 928000, EMD_S: {"rate_inr_per_mw": None}})
    assert not only_scalar[0].passed and only_scalar[0].field_paths == (EMD_S,)
    only_key = structured_agrees_with_scalar({EMD_S: {"rate_inr_per_mw": 5}})
    assert not only_key[0].passed and "has no value" in only_key[0].message
    # Neither states it (a formula): nothing to compare. No structured value: no outcome.
    assert structured_agrees_with_scalar({EMD_S: {"rate_inr_per_mw": None}}) == []
    assert structured_agrees_with_scalar({EMD: 928000}) == []
    assert agreement({}, CORE_PAIRS) == []


def test_a_scalar_agrees_with_a_list_when_one_item_says_the_same() -> None:
    multiple = "sector.power.fdre.shortfall_compensation_multiple"
    rules = "core.penalties.shortfall_rules"
    listed = [{"penalty_multiple_of_tariff": 2}, {"penalty_multiple_of_tariff": 1.5}]
    assert power_structured_agrees_with_scalar({multiple: 1.5, rules: listed})[0].passed
    assert not power_structured_agrees_with_scalar({multiple: 3, rules: listed})[0].passed
    # A list may hold rules the scalar field does not speak of.
    assert power_structured_agrees_with_scalar({rules: listed}) == []
