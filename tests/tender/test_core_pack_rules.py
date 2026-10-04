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
    assert [o.field_paths for o in outcomes] == [
        (NIT, PRE_BID),
        (PRE_BID, DEADLINE),
        (DEADLINE, OPENING),
        (NIT, QUERIES),
        (QUERIES, DEADLINE),
    ]
    assert all(outcome.passed and not outcome.warning for outcome in outcomes)


def test_date_order_fails_the_pair_that_is_out_of_order_and_only_that_pair() -> None:
    outcomes = date_order({NIT: "2026-03-01", PRE_BID: "2026-04-02", DEADLINE: "2026-03-30"})
    assert [(o.field_paths, o.passed) for o in outcomes] == [
        ((NIT, PRE_BID), True),
        ((PRE_BID, DEADLINE), False),
    ]
    assert outcomes[1].message == (
        "pre-bid meeting (2026-04-02) is after bid submission deadline (2026-03-30)"
    )
    assert not outcomes[1].warning
    late_queries = date_order({QUERIES: "2026-04-05", DEADLINE: "2026-03-30"})
    assert [(o.field_paths, o.passed, o.warning) for o in late_queries] == [
        ((QUERIES, DEADLINE), False, False)
    ]


def test_date_order_compares_the_dates_present_and_needs_two() -> None:
    assert date_order({DEADLINE: "2026-03-30"}) == []
    assert date_order({}) == []
    skipped = date_order({NIT: "2026-05-01", OPENING: "2026-04-01"})
    assert [(o.field_paths, o.passed) for o in skipped] == [((NIT, OPENING), False)]


def test_queries_closing_before_the_pre_bid_meeting_is_a_warning_not_a_failure() -> None:
    """NHPC FDRE-II: queries close on 26.03.2024, the pre-bid meeting is on 28.03.2024."""
    outcomes = date_order(
        {NIT: "2024-03-15", QUERIES: "2024-03-26", PRE_BID: "2024-03-28", DEADLINE: "2024-04-12"}
    )
    failed = [outcome for outcome in outcomes if not outcome.passed]
    assert [(o.field_paths, o.warning) for o in failed] == [((PRE_BID, QUERIES), True)]
    assert "queries close (2024-03-26) before the pre-bid meeting (2024-03-28)" in failed[0].message
    in_order = date_order({QUERIES: "2024-03-29", PRE_BID: "2024-03-28", DEADLINE: "2024-04-12"})
    assert all(outcome.passed for outcome in in_order)


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
