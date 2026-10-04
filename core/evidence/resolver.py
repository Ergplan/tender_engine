"""Locate a quoted piece of evidence on a page: character range and bounding box.

Deterministic. Text is normalised (case, whitespace, quote and dash variants) with an
index map back to the original, then matched exactly, then fuzzily (rapidfuzz), then
by words in any order, because a table cell that wraps is read by a person as
"Closing Date & Time 12.04.2024" and by the text layer as "Closing 12.04.2024 / Date & Time",
then by words in order with other words between them, because a table with two text
columns side by side (the "existing clause | amended clause" layout of an amendment) is
read by a person one column at a time and by the text layer line by line across both.
"""

from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

MIN_FUZZY_QUOTE_CHARS = 12
MIN_REORDERED_QUOTE_WORDS = 4
MIN_INTERLEAVED_QUOTE_WORDS = 6
# Words of the neighbouring column that may sit between two consecutive words of a quote.
INTERLEAVED_LOOKAHEAD = 14
INTERLEAVED_MIN_SCORE = 90.0
_EDGE_PUNCTUATION = ".,;:()[]{}\"'…"
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
            lowered = char.lower()
            # A few characters lower-case to two; keep one so the index map stays aligned.
            out.append(lowered if len(lowered) == 1 else char)
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
    start = _find_whole(needle, haystack)
    if start >= 0:
        end, score = start + len(needle), 100.0
    else:
        if len(needle) < MIN_FUZZY_QUOTE_CHARS:
            return None
        alignment = fuzz.partial_ratio_alignment(needle, haystack)
        if (
            alignment is not None
            and alignment.score >= threshold
            and _whole(haystack, alignment.dest_start, alignment.dest_end)
        ):
            start, end, score = alignment.dest_start, alignment.dest_end, float(alignment.score)
        else:
            reordered = _locate_reordered(needle, haystack, threshold)
            if reordered is None:
                return _locate_interleaved(needle, haystack, index_map, page, threshold)
            start, end, score = reordered
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


def _locate_interleaved(
    needle: str, haystack: str, index_map: list[int], page: PageText, threshold: float
) -> Located | None:
    """The quote's words found in order, with words of a neighbouring column between them.
    Each next word must follow within INTERLEAVED_LOOKAHEAD page words. At least 90% of
    the quote's words (and never fewer than the threshold) must be found, and every word
    that holds a digit must be among them, so the value itself is always on the page.
    The character range runs from the first matched word to the last; the box is the union
    of the matched words only, which is the quoted column and not its neighbour."""
    quoted = [word.strip(_EDGE_PUNCTUATION) for word in needle.split()]
    quoted = [word for word in quoted if word]
    if len(quoted) < MIN_INTERLEAVED_QUOTE_WORDS:
        return None
    words: list[tuple[str, int, int]] = []
    position = 0
    for raw in haystack.split(" "):
        word = raw.strip(_EDGE_PUNCTUATION)
        if word:
            offset = position + raw.index(word)
            words.append((word, offset, offset + len(word)))
        position += len(raw) + 1
    needed = max(threshold, INTERLEAVED_MIN_SCORE)
    best: tuple[float, list[int]] | None = None
    for first in (0, 1):
        for start, (word, _, _) in enumerate(words):
            if word != quoted[first]:
                continue
            matched = [start]
            cursor = start + 1
            failed = False
            for wanted in quoted[first + 1 :]:
                limit = min(cursor + INTERLEAVED_LOOKAHEAD, len(words))
                found = next((i for i in range(cursor, limit) if words[i][0] == wanted), None)
                if found is None:
                    if any(char.isdigit() for char in wanted):
                        failed = True
                        break
                    continue
                matched.append(found)
                cursor = found + 1
            if failed or (first == 1 and any(char.isdigit() for char in quoted[0])):
                continue
            score = 100.0 * len(matched) / len(quoted)
            # Of two equally complete matches, the tighter one is the quoted column.
            rank = (score, matched[0] - matched[-1])
            if score >= needed and (best is None or rank > (best[0], best[1][0] - best[1][-1])):
                best = (score, matched)
        if best is not None:
            break
    if best is None:
        return None
    score, matched = best
    spans = [(index_map[words[i][1]], index_map[words[i][2] - 1] + 1) for i in matched]
    boxes = [box for begin, end in spans for box in page.char_boxes[begin:end]]
    return Located(
        page_no=page.page_no,
        char_start=spans[0][0],
        char_end=spans[-1][1],
        bbox=_union(boxes),
        score=round(score, 1),
    )


def _whole(haystack: str, start: int, end: int) -> bool:
    """Whether haystack[start:end] begins and ends on word boundaries."""
    if end <= start:
        return False
    cut_before = start > 0 and haystack[start].isalnum() and haystack[start - 1].isalnum()
    cut_after = end < len(haystack) and haystack[end - 1].isalnum() and haystack[end].isalnum()
    return not (cut_before or cut_after)


def _find_whole(needle: str, haystack: str) -> int:
    """First occurrence of needle that does not start or end inside a word or a number:
    "50 MW" is not evidence on a page that says "250 MW". Returns -1 if there is none."""
    start = haystack.find(needle)
    while start >= 0:
        end = start + len(needle)
        cut_before = start > 0 and needle[0].isalnum() and haystack[start - 1].isalnum()
        cut_after = end < len(haystack) and needle[-1].isalnum() and haystack[end].isalnum()
        if not (cut_before or cut_after):
            return start
        start = haystack.find(needle, start + 1)
    return -1


def _locate_reordered(
    needle: str, haystack: str, threshold: float
) -> tuple[int, int, float] | None:
    """The run of consecutive page words that best matches the quote's words in any order.
    Only for quotes that hold a number (a table row with a date or an amount): every such
    word must appear in the run unchanged, so a neighbouring row is never taken for the
    quoted one. A quote of words alone is not matched this way, because reordered words
    can reverse a sentence's meaning.
    Returns (start, end, score) in the normalised haystack, or None below the threshold."""
    quoted = needle.split()
    wanted = len(quoted)
    if wanted < MIN_REORDERED_QUOTE_WORDS:
        return None
    numbers = {word for word in quoted if any(char.isdigit() for char in word)}
    if not numbers:
        return None
    words: list[tuple[int, int]] = []
    position = 0
    for word in haystack.split(" "):
        words.append((position, position + len(word)))
        position += len(word) + 1
    best: tuple[int, int, float] | None = None
    best_rank = (0.0, False)
    for size in (wanted, wanted + 1, wanted - 1):
        for first in range(len(words) - size + 1):
            start, end = words[first][0], words[first + size - 1][1]
            run = haystack[start:end]
            if not numbers.issubset(run.split()):
                continue
            score = float(fuzz.token_sort_ratio(needle, run))
            # Rows of a table repeat words, so two runs can tie; take the one that
            # starts where the quote starts.
            rank = (score, run.startswith(quoted[0]))
            if score >= threshold and rank > best_rank:
                best, best_rank = (start, end, score), rank
    return best


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
