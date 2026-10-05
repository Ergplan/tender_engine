from typing import Any

from core.schemas import RuleOutcome
from tender.domain_packs.core.structured import Pair, agreement

MIN_BID = "sector.power.common.min_bid_mw"
MAX_BID = "sector.power.common.max_bid_mw"
TOTAL = "sector.power.common.total_capacity_mw"
ELEMENTS = "sector.power.transmission.elements"


def bid_capacity_order(values: dict[str, Any]) -> list[RuleOutcome]:
    """min_bid_mw <= max_bid_mw <= total_capacity_mw, for the values present."""
    chain = [
        (path, label, values[path])
        for path, label in (
            (MIN_BID, "minimum bid"),
            (MAX_BID, "maximum bid"),
            (TOTAL, "total capacity"),
        )
        if path in values
    ]
    outcomes = []
    for (path_a, label_a, a), (path_b, label_b, b) in zip(chain, chain[1:], strict=False):
        if a <= b:
            message = f"{label_a} ({a:g} MW) does not exceed {label_b} ({b:g} MW)"
        else:
            message = f"{label_a} ({a:g} MW) exceeds {label_b} ({b:g} MW)"
        outcomes.append(RuleOutcome((path_a, path_b), a <= b, message))
    return outcomes


def elements_have_kv(values: dict[str, Any]) -> list[RuleOutcome]:
    """A transmission scheme lists at least one element with a voltage."""
    elements = values.get(ELEMENTS)
    if elements is None:
        return []
    if any(str(element.get("kv") or "").strip() for element in elements):
        return [RuleOutcome((ELEMENTS,), True, "at least one element states its voltage")]
    return [RuleOutcome((ELEMENTS,), False, "no element states a voltage (kv)")]


FDRE = "sector.power.fdre"
PAIRS: tuple[Pair, ...] = (
    (
        f"{FDRE}.assured_availability_percent",
        f"{FDRE}.demand_profile_structured",
        "peak_availability_pct",
    ),
    (
        f"{FDRE}.excess_energy_price_inr_per_kwh",
        f"{FDRE}.excess_energy_structured",
        "fixed_inr_per_kwh",
    ),
    (
        f"{FDRE}.shortfall_compensation_multiple",
        "core.penalties.shortfall_rules",
        "penalty_multiple_of_tariff",
    ),
    ("sector.power.solar.min_cuf_percent", "sector.power.solar.cuf_terms", "declared_min_pct"),
    ("sector.power.wind.min_cuf_percent", "sector.power.wind.cuf_terms", "declared_min_pct"),
    (
        "sector.power.hybrid.combined_cuf_floor_percent",
        "sector.power.hybrid.cuf_terms",
        "declared_min_pct",
    ),
    (
        "sector.power.bess.availability_floor_percent",
        "core.penalties.shortfall_rules",
        "threshold_pct",
    ),
)


def power_structured_agrees_with_scalar(values: dict[str, Any]) -> list[RuleOutcome]:
    """A structured key of the power pack agrees with the scalar that holds the same fact."""
    return agreement(values, PAIRS)
