"""Validators of the core pack, each with passing and failing cases."""

from tender.domain_packs.core.validation import EMD, PBG, date_order, emd_pbg_within_10x

NIT = "core.key_dates.nit_date"
PRE_BID = "core.key_dates.pre_bid_meeting_date"
QUERIES = "core.key_dates.query_deadline"
DEADLINE = "core.key_dates.bid_submission_deadline"
OPENING = "core.key_dates.technical_opening_date"


def test_date_order_passes_for_dates_in_order() -> None:
    outcomes = date_order(
        {
            NIT: "2026-03-01",
            PRE_BID: "2026-03-12",
            QUERIES: "2026-03-14",
            DEADLINE: "2026-03-30",
            OPENING: "2026-03-30",
        }
    )
    assert len(outcomes) == 4 and all(outcome.passed for outcome in outcomes)
    assert outcomes[0].field_paths == (NIT, PRE_BID)


def test_date_order_fails_the_pair_that_is_out_of_order_and_only_that_pair() -> None:
    outcomes = date_order({NIT: "2026-03-01", PRE_BID: "2026-04-02", DEADLINE: "2026-03-30"})
    assert [(o.field_paths, o.passed) for o in outcomes] == [
        ((NIT, PRE_BID), True),
        ((PRE_BID, DEADLINE), False),
    ]
    assert outcomes[1].message == (
        "pre-bid meeting (2026-04-02) is after bid submission deadline (2026-03-30)"
    )


def test_date_order_compares_the_dates_present_and_needs_two() -> None:
    assert date_order({DEADLINE: "2026-03-30"}) == []
    assert date_order({}) == []
    skipped = date_order({NIT: "2026-05-01", OPENING: "2026-04-01"})
    assert [(o.field_paths, o.passed) for o in skipped] == [((NIT, OPENING), False)]


def test_emd_and_pbg_within_ten_times_of_each_other_pass() -> None:
    (outcome,) = emd_pbg_within_10x({EMD: 928000, PBG: 2320000})
    assert outcome.passed and outcome.field_paths == (EMD, PBG)
    assert emd_pbg_within_10x({EMD: 100000, PBG: 1000000})[0].passed


def test_emd_and_pbg_more_than_ten_times_apart_fail() -> None:
    (outcome,) = emd_pbg_within_10x({EMD: 9280, PBG: 2320000})
    assert not outcome.passed and "more than 10x" in outcome.message
    assert not emd_pbg_within_10x({EMD: 2320000, PBG: 9280})[0].passed


def test_emd_and_pbg_must_be_positive_and_both_present() -> None:
    assert not emd_pbg_within_10x({EMD: 0, PBG: 2320000})[0].passed
    assert emd_pbg_within_10x({EMD: 928000}) == []
    assert emd_pbg_within_10x({PBG: 2320000}) == []
