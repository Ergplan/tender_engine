from typing import Any

from core.schemas import RuleOutcome

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
    if any(str(element.get("kv", "")).strip() for element in elements):
        return [RuleOutcome((ELEMENTS,), True, "at least one element states its voltage")]
    return [RuleOutcome((ELEMENTS,), False, "no element states a voltage (kv)")]
