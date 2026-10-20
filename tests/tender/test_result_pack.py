"""The result pack compiles into the `result.award` schema, and its validators are plain
Python over the winners table."""

from typing import Any

from tender.domain_packs.result.validation.rules import (
    RESULT_KIND,
    WINNERS,
    award_adopted_within_awarded,
    award_capacity_positive,
    award_price_in_band,
    award_rows_have_status,
    award_unit_matches_kind,
)
from tender.services.awards import _covered
from tender.services.packs import Catalog


def row(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "bidder": "Alpha Power Private Limited",
        "allocation": "published_result",
        "capacity": 380.0,
        "capacity_unit": "mw",
        "price": 2.41,
        "price_unit": "inr_per_kwh",
        "adopted_capacity": None,
        "adopted_price": None,
        "status": "awarded",
        "notes": None,
    }
    base.update(over)
    return base


def test_the_award_type_compiles_as_an_imported_object_beside_the_tenders(
    catalog: Catalog,
) -> None:
    award = catalog.get("award")
    assert award.object_type == "award" and award.pack == "result"
    assert award.schema.name == "result.award" and award.schema.version == "v1"
    assert [section.name for section in award.sections] == ["award_result"]
    assert award.sections[0].imported and not award.sections[0].derived
    assert [f.path for f in award.fields] == [
        "result.award.procurer",
        "result.award.reference",
        "result.award.result_kind",
        "result.award.result_date",
        "result.award.winners",
    ]
    winners = award.schema.field(WINNERS)
    assert winners.value_type == "record_list" and winners.required
    assert [k.name for k in winners.keys or []][:3] == ["bidder", "allocation", "capacity"]
    assert set(award.schema.cross_field_rules) == {
        "award_rows_have_status",
        "award_capacity_positive",
        "award_adopted_within_awarded",
        "award_price_in_band",
        "award_unit_matches_kind",
    }
    assert award.schema.run_rules == ["award_rows_located"]
    # The tender types are unchanged: no result field leaks into them.
    assert (
        all(not f.path.startswith("result.") for f in catalog.get("solar").fields)
        and catalog.get("solar").object_type == "tender"
    )


def test_every_row_needs_a_status() -> None:
    ok = award_rows_have_status({WINNERS: [row(), row(bidder="Beta")]})
    assert len(ok) == 1 and ok[0].passed
    bad = award_rows_have_status({WINNERS: [row(), row(bidder="Beta", status=None)]})
    assert not bad[0].passed and "Beta" in bad[0].message
    assert award_rows_have_status({}) == []


def test_a_stated_capacity_is_above_zero() -> None:
    assert award_capacity_positive({WINNERS: [row(), row(capacity=None)]})[0].passed
    bad = award_capacity_positive({WINNERS: [row(capacity=0.0)]})
    assert not bad[0].passed and "Alpha" in bad[0].message


def test_adopted_capacity_never_exceeds_the_award() -> None:
    assert award_adopted_within_awarded({WINNERS: [row(adopted_capacity=380.0)]})[0].passed
    assert award_adopted_within_awarded({WINNERS: [row(adopted_capacity=200.0)]})[0].passed
    bad = award_adopted_within_awarded({WINNERS: [row(adopted_capacity=470.0)]})
    assert not bad[0].passed and "470 adopted of 380" in bad[0].message


def test_a_price_lies_in_the_band_of_its_unit_and_needs_one() -> None:
    assert award_price_in_band({WINNERS: [row(), row(price=None, price_unit=None)]})[0].passed
    paise = award_price_in_band({WINNERS: [row(price=241.0)]})
    assert not paise.pop().passed
    no_unit = award_price_in_band({WINNERS: [row(price_unit=None)]})
    assert not no_unit[0].passed and "without a unit" in no_unit[0].message
    vgf = award_price_in_band({WINNERS: [row(price=11044800.0, price_unit="inr_per_mw_vgf")]})
    assert vgf[0].passed
    adopted = award_price_in_band({WINNERS: [row(adopted_price=0.01)]})
    assert not adopted[0].passed and "adopted_price" in adopted[0].message


def test_the_price_units_fit_the_kind_of_publication() -> None:
    order = {RESULT_KIND: "cerc_adoption_order", WINNERS: [row()]}
    assert award_unit_matches_kind(order)[0].passed
    wrong = {RESULT_KIND: "cerc_adoption_order", WINNERS: [row(price_unit="inr_per_mw_vgf")]}
    outcome = award_unit_matches_kind(wrong)[0]
    assert not outcome.passed and outcome.field_paths == (WINNERS, RESULT_KIND)
    assert award_unit_matches_kind({RESULT_KIND: "auction_result", WINNERS: [row()]})[0].passed
    register = {RESULT_KIND: "register", WINNERS: [row(price=None, price_unit=None)]}
    assert award_unit_matches_kind(register)[0].passed
    assert award_unit_matches_kind({WINNERS: [row()]}) == []


def test_a_reviewer_quote_covers_a_row_only_when_it_states_its_numbers() -> None:
    sheet = ["sunsource energy private limited 4 mw 6.95 inr/kwh"]
    assert _covered(row(bidder="SUNSOURCE ENERGY PRIVATE LIMITED", capacity=4.0, price=6.95), sheet)
    # Swapped quantities: the units say which number is which.
    assert not _covered(
        row(bidder="Sunsource Energy Private Limited", capacity=6.95, price=4.0), sheet
    )
    # Without units the reviewer's assignment stands (a table cell under its header).
    cells = ["beta energy limited 200 2.45"]
    assert _covered(row(bidder="Beta Energy Limited", capacity=200.0, price=2.45), cells)
    # One printed number is one value; a digit-substring is not a number; another row's
    # quote covers nothing; every number of the row is needed.
    assert not _covered(row(bidder="Beta Energy Limited", capacity=2.45, price=2.45), cells)
    assert not _covered(row(bidder="Beta Energy Limited", capacity=20.0, price=2.45), cells)
    assert not _covered(
        row(bidder="Beta Energy Limited", capacity=200.0, price=2.45), ["alpha power 200 2.45"]
    )
    assert not _covered(
        row(bidder="Beta Energy Limited", capacity=200.0, price=2.45, adopted_capacity=150.0), cells
    )
    assert _covered(
        row(bidder="Beta Energy Limited", capacity=200.0, price=2.45, adopted_capacity=150.0),
        ["beta energy limited 200 mw 2.45", "beta energy limited adopted 150 mw"],
    )
    # A quote running over two rows lends the second row's figures to nobody.
    two_rows = [
        "alpha power private limited 380 mw 2.41 inr/kwh; beta energy limited 200 mw 2.45 inr/kwh"
    ]
    table = {"alpha power private limited", "beta energy limited"}
    assert _covered(row(capacity=380.0, price=2.41), two_rows, table)
    assert not _covered(row(capacity=200.0, price=2.45), two_rows, table)
    assert _covered(row(bidder="Beta Energy Limited", capacity=200.0, price=2.45), two_rows, table)
    # Quoting the same place at two lengths adds no occurrence.
    assert not _covered(
        row(bidder="Beta Energy Limited", capacity=200.0, price=2.45, adopted_capacity=200.0),
        ["beta energy limited 200 mw 2.45 inr/kwh", "beta energy limited 200 mw"],
    )
    assert not _covered(
        row(bidder="Beta Energy Limited", capacity=200.0, price=2.45, adopted_capacity=200.0),
        ["beta energy limited 200 mw 2.45 inr/kwh", "beta energy limited 200 mw 2.46"],
    )
    # A stretch that runs past the row's own figures into a row the table does not list
    # lends nothing: only the first numbers after the bidder, as many as the row carries.
    assert not _covered(
        row(capacity=200.0, price=2.45),
        ["alpha power private limited 380 mw 2.41 inr/kwh; gamma renewables 200 mw 2.45 inr/kwh"],
        {"alpha power private limited"},
    )
