"""share_windows: field groups share a page window when that is cheaper."""

from core.services.extract_plan import SharedWindow, share_windows, window_cost

RATES = {
    "pages_per_call": 40,
    "cache_write_factor": 1.25,
    "cache_read_factor": 0.025,
    "call_overhead_pages": 6.0,
}


def plan(windows: dict[str, list[int]], max_pages: int = 80) -> list[SharedWindow]:
    return share_windows(windows, max_pages=max_pages, **RATES)


def pages(start: int, end: int) -> list[int]:
    return list(range(start, end + 1))


def test_groups_with_the_same_window_share_it() -> None:
    [window] = plan(
        {"dates": pages(1, 30), "eligibility": pages(1, 30), "commercial": pages(1, 30)}
    )
    assert window.groups == ("dates", "eligibility", "commercial")
    assert window.pages == tuple(pages(1, 30)) and window.shared


def test_windows_that_differ_slightly_become_one_window_of_their_union() -> None:
    [window] = plan({"dates": pages(1, 30), "eligibility": pages(3, 34)})
    assert window.groups == ("dates", "eligibility") and window.pages == tuple(pages(1, 34))


def test_windows_that_do_not_overlap_stay_apart() -> None:
    result = plan({"dates": pages(1, 20), "penalties": pages(100, 120)})
    assert [w.groups for w in result] == [("dates",), ("penalties",)]
    assert not any(w.shared for w in result)


def test_a_small_window_does_not_join_a_large_one_it_barely_touches() -> None:
    result = plan({"identity": pages(1, 3), "commercial": pages(3, 60)})
    assert [w.groups for w in result] == [("identity",), ("commercial",)]


def test_a_union_over_the_page_cap_is_not_made() -> None:
    windows = {"a": pages(1, 60), "b": pages(1, 70)}
    assert [w.groups for w in plan(windows, max_pages=65)] == [("a",), ("b",)]
    [together] = plan(windows, max_pages=80)
    assert together.pages == tuple(pages(1, 70))


def test_three_groups_share_when_a_pair_alone_would_not_pay() -> None:
    # A write that costs twice the input price (the one-hour cache of a batch run) is not
    # earned back by one reader, but is by two.
    hour = {**RATES, "cache_write_factor": 2.0}
    same = pages(1, 20)
    two = share_windows({"a": same, "b": same}, max_pages=80, **hour)
    assert [w.groups for w in two] == [("a",), ("b",)]
    [three] = share_windows({"a": same, "b": same, "c": same}, max_pages=80, **hour)
    assert three.groups == ("a", "b", "c")


def test_sharing_is_not_chosen_when_it_needs_more_calls_than_it_saves() -> None:
    # 30 + 30 pages overlapping by 15: the union of 45 would need two calls per group.
    result = plan({"a": pages(1, 30), "b": pages(16, 45)})
    assert [w.groups for w in result] == [("a",), ("b",)]


def test_order_follows_the_schema_and_groups_without_pages_are_left_out() -> None:
    result = plan(
        {
            "summary": pages(1, 10),
            "dates": pages(50, 60),
            "empty": [],
            "identity": pages(1, 10),
            "penalties": pages(50, 61),
        }
    )
    assert [w.groups for w in result] == [("summary", "identity"), ("dates", "penalties")]


def test_the_result_does_not_depend_on_the_order_pairs_are_tried_in() -> None:
    windows = {"a": pages(1, 20), "b": pages(1, 22), "c": pages(2, 21), "d": pages(70, 75)}
    forwards = plan(windows)
    backwards = plan(dict(reversed(list(windows.items()))))
    assert {w.groups: w.pages for w in forwards} == {
        tuple(sorted(w.groups)): w.pages for w in backwards
    }


def test_window_cost_counts_one_write_and_cheap_reads() -> None:
    assert window_cost(10, 1, **RATES) == 10 + 6
    assert window_cost(10, 3, **RATES) == 10 * (1.25 + 2 * 0.025) + 3 * 6
    assert window_cost(50, 2, **RATES) == 50 * (1.25 + 0.025) + 2 * 2 * 6
    assert window_cost(0, 2, **RATES) == 0
