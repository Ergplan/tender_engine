"""The resolver against the evidence corpus. The pass rate is reported, and it may only
move with a deliberate change to known_failures.json."""

from pathlib import Path

from core.evidence.corpus import known_failures, load_cases, run_corpus, summarise

CORPUS = Path(__file__).parent / "evidence_corpus"
CATEGORIES = {
    "hyphenation",
    "ligatures",
    "spaces",
    "quotes_and_dashes",
    "reformatted_numbers",
    "two_column",
    "page_boundary",
    "table_cell_reading_order",
    "repeated_quote",
    "not_on_page",
    "real_unlocated_at_extraction",
    "real_near_miss",
    "real_not_exact",
}


def test_the_corpus_holds_the_real_cases_and_every_deliberate_category() -> None:
    cases = load_cases(CORPUS)
    assert len(cases) >= 220 and len({case["id"] for case in cases}) == len(cases)
    assert {case["category"] for case in cases} == CATEGORIES
    real = [case for case in cases if case["category"].startswith("real_")]
    assert len(real) >= 190
    for case in real:
        assert (CORPUS / "pages" / f"{case['page']}.json.gz").is_file(), case["id"]
    assert sum(1 for case in cases if not case["expect"]["located"]) >= 8


def test_only_the_known_failures_fail() -> None:
    results = run_corpus(CORPUS)
    print("\n" + summarise(results))
    failing = {result.case_id: result.detail for result in results if not result.passed}
    known = known_failures(CORPUS)
    assert failing.keys() - known == set(), {k: failing[k] for k in failing.keys() - known}
    assert known - failing.keys() == set(), "these now pass: remove them from known_failures.json"
    assert len(failing) / len(results) < 0.02
