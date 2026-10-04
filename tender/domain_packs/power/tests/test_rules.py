"""Validators of the power pack, each with passing and failing cases."""

from tender.domain_packs.power.validation.rules import (
    ELEMENTS,
    MAX_BID,
    MIN_BID,
    TOTAL,
    bid_capacity_order,
    elements_have_kv,
)
from tender.services.packs import load_catalog


def test_bid_capacity_order_passes() -> None:
    outcomes = bid_capacity_order({MIN_BID: 50, MAX_BID: 600, TOTAL: 1200})
    assert [(o.field_paths, o.passed) for o in outcomes] == [
        ((MIN_BID, MAX_BID), True),
        ((MAX_BID, TOTAL), True),
    ]
    assert bid_capacity_order({MAX_BID: 1200, TOTAL: 1200})[0].passed


def test_bid_capacity_order_fails_the_pair_out_of_order() -> None:
    outcomes = bid_capacity_order({MIN_BID: 700, MAX_BID: 600, TOTAL: 1200})
    assert [o.passed for o in outcomes] == [False, True]
    assert outcomes[0].message == "minimum bid (700 MW) exceeds maximum bid (600 MW)"
    (outcome,) = bid_capacity_order({MIN_BID: 50, TOTAL: 25})
    assert not outcome.passed and outcome.field_paths == (MIN_BID, TOTAL)


def test_bid_capacity_order_needs_two_values() -> None:
    assert bid_capacity_order({TOTAL: 1200}) == []
    assert bid_capacity_order({}) == []


def test_transmission_elements_need_one_voltage() -> None:
    with_kv = [{"name": "Line A", "kind": "line", "kv": "400"}, {"name": "Bay B", "kind": "bay"}]
    assert elements_have_kv({ELEMENTS: with_kv})[0].passed
    (outcome,) = elements_have_kv({ELEMENTS: [{"name": "Line A", "kind": "line"}]})
    assert not outcome.passed and outcome.field_paths == (ELEMENTS,)
    assert elements_have_kv({}) == []


def test_range_rules_of_the_power_fields() -> None:
    """Tariff ceiling between 1 and 15 INR/kWh, PPA tenure 10 to 35 years, SCOD above 0."""
    fields = {field.path: field for field in load_catalog().get("solar").schema.fields}
    ceiling = fields["sector.power.common.tariff_ceiling_inr_per_kwh"].validation
    tenure = fields["sector.power.common.ppa_tenure_years"].validation
    scod = fields["sector.power.common.scod_months"].validation
    assert (ceiling.min, ceiling.max) == (1, 15)
    assert (tenure.min, tenure.max) == (10, 35)
    assert scod.min == 1
