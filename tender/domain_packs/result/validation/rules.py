"""Deterministic rules over an imported award: no model, plain Python (CLAUDE.md,
"Validation is deterministic"). Each cross-field rule receives the coerced values of the
object's fields and returns one outcome per thing it checked; a failure sends the table to
needs_review with the rule's name, it never hides it."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Candidate, EvidenceSpan, ExtractionRun
from core.schemas import CandidateOutcome, RuleOutcome

WINNERS = "result.award.winners"
RESULT_KIND = "result.award.result_kind"

# Plausible bands per price unit, wide enough for every published figure and narrow enough
# to catch a unit mix-up (a tariff in paise, a VGF amount read as a tariff). A green
# hydrogen incentive may be bid at zero (the SIGHT auctions of 2024), so that band starts
# at 0.
PRICE_BANDS: dict[str, tuple[float, float]] = {
    "inr_per_kwh": (0.5, 25.0),
    "inr_per_kg": (0.0, 200.0),
    "inr_per_mw_vgf": (100_000.0, 100_000_000.0),
    "inr_per_mw_month": (10_000.0, 10_000_000.0),
    "inr_per_mw_annum": (100_000.0, 100_000_000.0),
    "months_ppa_term": (12.0, 480.0),
    "inr_contract_value": (100_000.0, 1_000_000_000_000.0),
    "inr_two_year_charges": (100_000.0, 1_000_000_000_000.0),
}
# The price units a kind of publication may carry. A tariff adoption order adopts a
# tariff or a per-kg incentive; an auction result or an allocation may publish any of
# the units; a register page states no price.
UNITS_BY_KIND: dict[str, frozenset[str]] = {
    "cerc_adoption_order": frozenset({"inr_per_kwh", "inr_per_kg", "inr_per_mw_month"}),
    "auction_result": frozenset(PRICE_BANDS),
    "allocation": frozenset(PRICE_BANDS),
    "register": frozenset(),
}


def _rows(values: dict[str, Any]) -> list[dict[str, Any]] | None:
    rows = values.get(WINNERS)
    return rows if isinstance(rows, list) else None


def _name(row: dict[str, Any], index: int) -> str:
    return str(row.get("bidder") or f"row {index}")


def award_rows_have_status(values: dict[str, Any]) -> list[RuleOutcome]:
    """Every winner row says what it is (awarded, adopted, L1 only, empanelled ...)."""
    rows = _rows(values)
    if rows is None:
        return []
    missing = [_name(row, i) for i, row in enumerate(rows, start=1) if not row.get("status")]
    if missing:
        return [RuleOutcome((WINNERS,), False, f"row(s) without a status: {', '.join(missing)}")]
    return [RuleOutcome((WINNERS,), True, "every row has a status")]


def award_capacity_positive(values: dict[str, Any]) -> list[RuleOutcome]:
    """A capacity, where the row gives one, is above zero."""
    rows = _rows(values)
    if rows is None:
        return []
    bad = [
        _name(row, i)
        for i, row in enumerate(rows, start=1)
        if row.get("capacity") is not None and float(row["capacity"]) <= 0
    ]
    if bad:
        return [RuleOutcome((WINNERS,), False, f"capacity not above zero: {', '.join(bad)}")]
    return [RuleOutcome((WINNERS,), True, "every stated capacity is above zero")]


def award_adopted_within_awarded(values: dict[str, Any]) -> list[RuleOutcome]:
    """What an order adopted is never more than what was awarded."""
    rows = _rows(values)
    if rows is None:
        return []
    bad = [
        f"{_name(row, i)} ({row['adopted_capacity']:g} adopted of {row['capacity']:g})"
        for i, row in enumerate(rows, start=1)
        if row.get("adopted_capacity") is not None
        and row.get("capacity") is not None
        and float(row["adopted_capacity"]) > float(row["capacity"])
    ]
    if bad:
        return [RuleOutcome((WINNERS,), False, f"adopted above awarded: {', '.join(bad)}")]
    return [RuleOutcome((WINNERS,), True, "adopted capacity within the awarded capacity")]


def award_price_in_band(values: dict[str, Any]) -> list[RuleOutcome]:
    """A price lies in the plausible band of its unit; a price without a unit is flagged."""
    rows = _rows(values)
    if rows is None:
        return []
    bad: list[str] = []
    for i, row in enumerate(rows, start=1):
        for key in ("price", "adopted_price"):
            price = row.get(key)
            if price is None:
                continue
            unit = row.get("price_unit")
            if unit is None:
                bad.append(f"{_name(row, i)}: {key} {float(price):g} without a unit")
                continue
            low, high = PRICE_BANDS[unit]
            if not low <= float(price) <= high:
                bad.append(
                    f"{_name(row, i)}: {key} {float(price):g} outside {low:g}–{high:g} {unit}"
                )
    if bad:
        return [RuleOutcome((WINNERS,), False, "; ".join(bad))]
    return [RuleOutcome((WINNERS,), True, "every price is within the band of its unit")]


def award_unit_matches_kind(values: dict[str, Any]) -> list[RuleOutcome]:
    """The price units of the rows fit the kind of publication."""
    rows = _rows(values)
    kind = values.get(RESULT_KIND)
    if rows is None or kind not in UNITS_BY_KIND:
        return []
    allowed = UNITS_BY_KIND[kind]
    bad = sorted(
        {
            str(row["price_unit"])
            for row in rows
            if row.get("price_unit") is not None and row["price_unit"] not in allowed
        }
    )
    if bad:
        return [
            RuleOutcome(
                (WINNERS, RESULT_KIND), False, f"unit(s) {bad} are not published in a {kind}"
            )
        ]
    return [RuleOutcome((WINNERS, RESULT_KIND), True, f"price units fit a {kind}")]


def award_rows_located(
    session: Session, run: ExtractionRun, candidates: Sequence[Candidate]
) -> list[CandidateOutcome]:
    """Every winner row's quotes (its bidder, and its price or capacity) were all found on
    the page it cites: a number alone proves nothing, it recurs. The importer stores a
    row's quotes with the row's number as their ordinal, so the rows whose evidence was
    not located can be named; the generic evidence check sends the table to review, this
    says which rows."""
    outcomes: list[CandidateOutcome] = []
    for candidate in candidates:
        if candidate.field_path != WINNERS or not isinstance(candidate.value, list):
            continue
        located: dict[int, bool] = {}
        for ordinal, char_start in session.execute(
            select(EvidenceSpan.ordinal, EvidenceSpan.char_start).where(
                EvidenceSpan.candidate_id == candidate.id,
                EvidenceSpan.tenant_id == run.tenant_id,
            )
        ):
            if ordinal is not None:
                located[ordinal] = located.get(ordinal, True) and char_start is not None
        rows = candidate.value
        missing = [
            _name(row, i)
            for i, row in enumerate(rows, start=1)
            if isinstance(row, dict) and not located.get(i, False)
        ]
        if missing:
            message = f"{len(missing)} of {len(rows)} row(s) not located on the page: " + ", ".join(
                missing
            )
            outcomes.append(CandidateOutcome(candidate.id, False, message))
        else:
            outcomes.append(CandidateOutcome(candidate.id, True, "every row located on its page"))
    return outcomes
