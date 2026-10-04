"""Locate a quoted piece of evidence on a page: character range and bounding box.

Deterministic. Text is normalised (case, whitespace, quote and dash variants) with an
index map back to the original, then matched exactly, then fuzzily (rapidfuzz).
"""

from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

MIN_FUZZY_QUOTE_CHARS = 12
_TRANSLATE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
    }
)


@dataclass(frozen=True)
class PageText:
    page_no: int
    text: str
    char_boxes: list[Any]
    has_text_layer: bool


@dataclass(frozen=True)
class Located:
    page_no: int
    char_start: int
    char_end: int
    bbox: list[float] | None
    score: float


def normalise(text: str) -> tuple[str, list[int]]:
    """Lower-case, unify quotes and dashes, collapse whitespace. Returns the normalised
    string and, for each of its characters, the index of the original character."""
    out: list[str] = []
    index_map: list[int] = []
    previous_space = True
    for index, char in enumerate(text.translate(_TRANSLATE)):
        if char.isspace():
            if not previous_space:
                out.append(" ")
                index_map.append(index)
            previous_space = True
        else:
            out.append(char.lower())
            index_map.append(index)
            previous_space = False
    if out and out[-1] == " ":
        out.pop()
        index_map.pop()
    return "".join(out), index_map


def locate(quote: str, page: PageText, threshold: float) -> Located | None:
    """Find the quote on the page, or return None."""
    if not page.has_text_layer:
        return None
    needle, _ = normalise(quote)
    haystack, index_map = normalise(page.text)
    if not needle or not haystack:
        return None
    start = haystack.find(needle)
    if start >= 0:
        end, score = start + len(needle), 100.0
    else:
        if len(needle) < MIN_FUZZY_QUOTE_CHARS:
            return None
        alignment = fuzz.partial_ratio_alignment(needle, haystack)
        if alignment is None or alignment.score < threshold:
            return None
        start, end, score = alignment.dest_start, alignment.dest_end, float(alignment.score)
        if end <= start:
            return None
    char_start = index_map[start]
    char_end = index_map[end - 1] + 1
    return Located(
        page_no=page.page_no,
        char_start=char_start,
        char_end=char_end,
        bbox=_union(page.char_boxes[char_start:char_end]),
        score=round(score, 1),
    )


def _union(boxes: list[Any]) -> list[float] | None:
    present = [box for box in boxes if box is not None]
    if not present:
        return None
    return [
        min(box[0] for box in present),
        min(box[1] for box in present),
        max(box[2] for box in present),
        max(box[3] for box in present),
    ]
