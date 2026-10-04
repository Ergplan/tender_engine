"""Pure helpers: section digest, page selection, chunking, delta classification."""

import pytest

from core.schemas import RoutingHints
from core.services.approve import classify_delta
from core.services.extract import build_group_model, chunked, select_pages
from core.services.section_map import (
    MappedSection,
    clean_sections,
    detect_headings,
    normalise_kind,
    page_digest,
)
from tests.fixtures.schemas import contract_schema, make_registry

SECTIONS = [
    (1, 2, "Cover", "cover_and_notice"),
    (3, 6, "Section 3: Bid Security", "financial_security"),
    (7, 10, "Annexure A", "formats_and_annexures"),
]
TEXTS = {n: "" for n in range(1, 11)} | {4: "EMD and EMD again", 8: "emd once", 9: "nothing"}


def pages(
    routing: RoutingHints, max_pages: int = 80, fallback: int = 3, keyword_pages: int = 0
) -> list[int]:
    return select_pages(
        routing,
        SECTIONS,
        TEXTS,
        max_pages=max_pages,
        fallback_pages=fallback,
        keyword_pages=keyword_pages,
    )


def test_sections_are_chosen_by_kind() -> None:
    assert pages(RoutingHints(section_kinds=["Financial Security"])) == [3, 4, 5, 6]


def test_sections_are_chosen_by_keyword_in_the_heading() -> None:
    assert pages(RoutingHints(keywords=["annexure"])) == [7, 8, 9, 10]
    assert pages(RoutingHints(section_kinds=["cover_and_notice"], keywords=["bid security"])) == [
        1, 2, 3, 4, 5, 6,
    ]  # fmt: skip


def test_without_a_matching_section_pages_mentioning_the_keywords_are_used() -> None:
    assert pages(RoutingHints(keywords=["emd"])) == [4, 8]


def test_pages_outside_the_matched_sections_that_mention_the_keywords_most_are_added() -> None:
    """The clause can sit in a section the mapper labelled differently from the formats."""
    routing = RoutingHints(section_kinds=["formats_and_annexures"], keywords=["emd"])
    assert pages(routing) == [7, 8, 9, 10]
    assert pages(routing, keyword_pages=1) == [4, 7, 8, 9, 10]
    cover = RoutingHints(section_kinds=["cover_and_notice"], keywords=["emd"])
    assert pages(cover, keyword_pages=1) == [1, 2, 4], "the page with most mentions first"
    assert pages(cover, keyword_pages=5) == [1, 2, 4, 8]
    both = RoutingHints(section_kinds=["cover_and_notice"], keywords=["emd", "nothing"])
    assert pages(both, keyword_pages=2) == [1, 2, 4, 9], "each keyword gets its best page"


def test_without_any_match_the_opening_pages_are_used() -> None:
    assert pages(RoutingHints(section_kinds=["nope"], keywords=["zzz"])) == [1, 2, 3]
    assert pages(RoutingHints()) == [1, 2, 3]


def test_a_window_over_the_group_cap_keeps_the_pages_with_most_keyword_hits() -> None:
    routing = RoutingHints(
        section_kinds=["financial_security", "formats_and_annexures"], keywords=["emd"]
    )
    assert pages(routing, max_pages=3) == [3, 4, 8]


def test_chunked_splits_at_the_cap() -> None:
    assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(chunked([], 2)) == []


def test_group_model_requires_value_confidence_rationale_and_evidence_for_every_field() -> None:
    schema, registry = contract_schema(), make_registry()
    model = build_group_model(schema, schema.groups[2], registry)
    json_schema = model.model_json_schema()
    assert set(json_schema["required"]) == {"emd_per_mw", "capacity_mw", "tenure_years"}
    for definition in json_schema["$defs"].values():
        if "value" in definition["properties"]:
            assert set(definition["required"]) == {"value", "confidence", "rationale", "evidence"}
    with pytest.raises(ValueError):
        model.model_validate({"emd_per_mw": {"value": 1, "confidence": 1, "rationale": "x"}})


def test_headings_are_detected_by_clause_pattern_and_capitals() -> None:
    text = "\n".join(
        [
            "SECTION 2: KEY DATES",
            "3.1 Earnest Money Deposit",
            "some ordinary sentence here.",
            "ANNEXURE - A",
            "Format 7.1 Covering Letter",
            "Short",
            "BID INFORMATION SHEET",
        ]
    )
    assert detect_headings(text) == [
        "SECTION 2: KEY DATES",
        "3.1 Earnest Money Deposit",
        "ANNEXURE - A",
        "Format 7.1 Covering Letter",
        "BID INFORMATION SHEET",
    ]


def test_page_digest_has_number_preview_and_headings() -> None:
    digest = page_digest(4, "SECTION 2: KEY DATES\n" + "word " * 200)
    assert digest.startswith("=== page 4 ===\nSECTION 2: KEY DATES word")
    assert "Heading-like lines: SECTION 2: KEY DATES" in digest
    assert len(digest.splitlines()[1]) <= 400
    assert "(no extractable text)" in page_digest(5, "   ")


def test_section_ranges_are_clamped_and_inverted_ones_dropped() -> None:
    def section(start: int, end: int) -> MappedSection:
        return MappedSection(start_page=start, end_page=end, heading="h", kind="k", confidence=1)

    cleaned = clean_sections([section(5, 99), section(0, 2), section(9, 3), section(20, 30)], 10)
    assert [(s.start_page, s.end_page) for s in cleaned] == [(1, 2), (5, 10)]


def test_kind_is_normalised_to_a_label() -> None:
    assert normalise_kind(" Financial Security! ") == "financial_security"
    assert normalise_kind("???") == "other"


@pytest.mark.parametrize(
    ("decision", "raw", "coerced", "final", "expected"),
    [
        ("approved", "12.03.2026", "2026-03-12", "2026-03-12", None),
        ("edited", "ACME/2026/001", "ACME/2026/001", "ACME/2026/002", "wrong_value"),
        ("edited", "acme power  limited", "acme power  limited", "Acme Power Limited", "format"),
        ("edited", "9,28,000 per MW", None, 928000, "wrong_value"),
        ("edited", "928000", None, 928000, "format"),
        ("edited", None, None, "x", "missing"),
        ("not_in_document", None, None, None, None),
        ("not_in_document", 25, 25, None, "extra"),
        ("rejected", 25, 25, None, "wrong_value"),
        ("edited", ["a", "b"], ["a", "b"], ["A", "B"], "format"),
        ("edited", 25, 25, 30, "wrong_value"),
    ],
)
def test_delta_classification(
    decision: str, raw: object, coerced: object, final: object, expected: str | None
) -> None:
    assert classify_delta(decision, raw, coerced, final) == expected
