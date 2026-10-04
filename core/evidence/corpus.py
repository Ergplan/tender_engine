"""The evidence corpus: quotes with the page they should (or should not) be found on.

A corpus is a directory: `pages/<id>.json.gz` (text and character boxes of real pages),
`real_cases.json`, `synthetic_cases.json` and `known_failures.json`. This module loads
it and scores the resolver against it. Standard library only.
"""

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.evidence.resolver import Match, PageText, normalise, resolve, resolve_pair

CHAR_WIDTH, LINE_HEIGHT, LEFT, TOP = 6.0, 20.0, 72.0, 100.0


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    passed: bool
    detail: str


def synthetic_page(lines: list[Any], page_no: int = 1) -> PageText:
    """A page from lines. A line is a string, laid out from the left margin, or a list of
    [x, text] segments, each laid out from its own x: that is how a table row with text
    in several columns is written. Characters are 6 wide and lines 20 apart."""
    text: list[str] = []
    boxes: list[list[float] | None] = []
    for number, line in enumerate(lines):
        if number:
            text.append("\n")
            boxes.append(None)
        y = TOP + number * LINE_HEIGHT
        segments = [[LEFT, line]] if isinstance(line, str) else line
        for position, (x, segment) in enumerate(segments):
            if position:
                text.append(" ")
                boxes.append(None)
            for offset, char in enumerate(segment):
                text.append(char)
                left = float(x) + offset * CHAR_WIDTH
                boxes.append(None if char == " " else [left, y, left + CHAR_WIDTH, y + 10.0])
    return PageText(page_no=page_no, text="".join(text), char_boxes=boxes)


def load_page(directory: Path, page_id: str, page_no: int = 1) -> PageText:
    with gzip.open(directory / "pages" / f"{page_id}.json.gz", "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    return PageText(page_no=page_no, text=data["text"], char_boxes=data["char_boxes"])


def load_cases(directory: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for name in ("real_cases.json", "synthetic_cases.json"):
        path = directory / name
        if path.is_file():
            cases.extend(json.loads(path.read_text(encoding="utf-8")))
    return cases


def known_failures(directory: Path) -> set[str]:
    path = directory / "known_failures.json"
    return set(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else set()


def run_case(directory: Path, case: dict[str, Any], threshold: float = 85.0) -> CaseResult:
    """Resolve one case and compare with what it expects: located or not; when located,
    every number of the quote inside the located text, plus the case's own `contains`
    and `not_contains` strings, `method`, `line` (0-based line the match starts on) and
    `page_no`, if it names them."""
    if "page" in case:
        page = load_page(directory, case["page"], case.get("page_no", 1))
    else:
        page = synthetic_page(case["lines"])
    if "next_lines" in case:
        outcome = resolve_pair(
            case["quote"], page, synthetic_page(case["next_lines"], page_no=2), threshold
        )
        pages = {1: page, 2: synthetic_page(case["next_lines"], page_no=2)}
        source = pages.get(outcome.page_no, page).text
    else:
        outcome = resolve(case["quote"], page, threshold)
        source = page.text
    expect = case["expect"]

    def result(passed: bool, detail: str) -> CaseResult:
        return CaseResult(case["id"], case["category"], passed, detail)

    if not isinstance(outcome, Match):
        detail = f"miss, best score {outcome.best_score}"
        return result(not expect["located"], detail)
    located = source[outcome.char_start : outcome.char_end]
    detail = f"{outcome.method} {outcome.score}: {' '.join(located.split())[:120]}"
    if not expect["located"]:
        return result(False, f"located but should not be: {detail}")
    slice_text, _ = normalise(located)
    quote_text, _ = normalise(case["quote"])
    numbers = {
        word.strip(".,;:()[]{}\"'…")
        for word in quote_text.split()
        if any(char.isdigit() for char in word)
    }
    # A number the layout hyphenated across a line ("0002/26-" ... "27") is still there.
    unbroken = slice_text.replace(" ", "")
    tokens = slice_text.split()
    # A match across a page boundary is cut to one page; the resolver checked its numbers
    # on the two pages read together.
    if outcome.method == "page_boundary":
        numbers = set()
    missing = sorted(
        number
        for number in numbers
        if number
        and number not in slice_text
        and number not in unbroken
        and not any(
            token.endswith("-") and number.startswith(token) and number[len(token) :] in tokens
            for token in tokens
        )
    )
    if missing:
        return result(False, f"numbers {missing} not in the located text: {detail}")
    lowered = located.lower()
    for wanted in expect.get("contains", []):
        if wanted.lower() not in lowered:
            return result(False, f"{wanted!r} not in the located text: {detail}")
    for unwanted in expect.get("not_contains", []):
        if unwanted.lower() in lowered:
            return result(False, f"{unwanted!r} is in the located text: {detail}")
    if "method" in expect and outcome.method != expect["method"]:
        return result(False, f"expected method {expect['method']}: {detail}")
    if "line" in expect:
        line = source.count("\n", 0, outcome.char_start)
        if line != expect["line"]:
            return result(False, f"expected the match on line {expect['line']}, got {line}")
    if "page_no" in expect and outcome.page_no != expect["page_no"]:
        return result(False, f"expected page {expect['page_no']}, got {outcome.page_no}")
    return result(True, detail)


def run_corpus(directory: Path, threshold: float = 85.0) -> list[CaseResult]:
    return [run_case(directory, case, threshold) for case in load_cases(directory)]


def summarise(results: list[CaseResult]) -> str:
    """Pass rate overall and per category, as plain lines for a report."""
    lines = []
    passed = sum(1 for result in results if result.passed)
    total = len(results)
    rate = f"{100 * passed / total:.1f}%" if total else "n/a"
    lines.append(f"evidence corpus: {passed} of {total} cases pass ({rate})")
    categories: dict[str, list[CaseResult]] = {}
    for result in results:
        categories.setdefault(result.category, []).append(result)
    for category, group in sorted(categories.items()):
        ok = sum(1 for result in group if result.passed)
        lines.append(f"  {category}: {ok} of {len(group)}")
    return "\n".join(lines)
