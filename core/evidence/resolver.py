"""Locate a quoted piece of evidence on a page: character range and bounding box.

Deterministic, and independent of everything else: a quote, a page's text and one box
per character go in; a Match or a Miss comes out. Text is normalised (case, whitespace,
quote and dash variants, ligatures, thousands separators, words hyphenated across a line
break) with an index map back to the original, then four methods are tried in order:

1. exact    the normalised quote as a run of characters, on word boundaries;
2. fuzzy    rapidfuzz partial ratio at the threshold, on word boundaries, with every
            number of the quote present in the matched text;
3. reordered  the quote's words in any order over consecutive page words, numbers
            unchanged: a table cell that wraps is read by a person as "Closing Date &
            Time 12.04.2024" and by the text layer as "Closing 12.04.2024 / Date & Time";
4. interleaved  the quote's words in order with other words between them: a table with
            text columns side by side ("existing clause | amended clause") is read by a
            person one column at a time and by the text layer line by line across all.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

MIN_FUZZY_QUOTE_CHARS = 12
MIN_REORDERED_QUOTE_WORDS = 4
MIN_INTERLEAVED_QUOTE_WORDS = 4
# A short quote must be found whole; a longer one may lose a word the layout broke.
INTERLEAVED_PARTIAL_FROM_WORDS = 6
INTERLEAVED_MIN_SCORE = 90.0
# Words of a neighbouring column that may sit between two consecutive words of a quote.
INTERLEAVED_LOOKAHEAD = 14
# A cell that wraps continues under its first line: a longer gap is allowed when the next
# word starts inside the horizontal band of the words matched so far.
INTERLEAVED_COLUMN_LOOKAHEAD = 150
COLUMN_EDGE_TOLERANCE = 3.0
_EDGE_PUNCTUATION = ".,;:()[]{}\"'…"
_TRANSLATE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        "‐": "-",
        "‑": "-",
    }
)
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
# Characters that take no part in matching: soft hyphen, zero-width space and joiners, BOM.
_INVISIBLE = {"­", "​", "‌", "‍", "⁠", "﻿"}
_HYPHENATED_BREAK = re.compile(r"(?<=[A-Za-z])-[ \t]*\n[ \t]*(?=[a-z])")
_THOUSANDS_SEPARATOR = re.compile(r"(?<=\d),(?=\d)")


@dataclass(frozen=True)
class PageText:
    """A page: its text and, aligned with it, one [x0, top, x1, bottom] box per character
    (None for whitespace the text layout inserted)."""

    page_no: int
    text: str
    char_boxes: list[Any]
    has_text_layer: bool = True


@dataclass(frozen=True)
class Match:
    page_no: int
    char_start: int
    char_end: int
    bbox: list[float] | None
    score: float
    method: str = "exact"


@dataclass(frozen=True)
class Miss:
    """The quote was not found. best_score is the highest score any method reached."""

    page_no: int
    best_score: float
    reason: str


Located = Match


def normalise(text: str) -> tuple[str, list[int]]:
    """Lower-case; unify quotes and dashes; expand ligatures; collapse every kind of
    whitespace (including non-breaking and thin spaces); drop invisible characters,
    thousands separators inside numbers and the hyphen of a word broken across a line.
    Returns the normalised string and, for each of its characters, the index of the
    original character it came from."""
    dropped: set[int] = set()
    for pattern in (_HYPHENATED_BREAK, _THOUSANDS_SEPARATOR):
        for match in pattern.finditer(text):
            dropped.update(range(match.start(), match.end()))
    out: list[str] = []
    index_map: list[int] = []
    previous_space = True
    for index, raw in enumerate(text):
        if index in dropped or raw in _INVISIBLE:
            continue
        char = raw.translate(_TRANSLATE)
        if char.isspace():
            if not previous_space:
                out.append(" ")
                index_map.append(index)
            previous_space = True
            continue
        for piece in _LIGATURES.get(char, char):
            lowered = piece.lower()
            # A few characters lower-case to two; keep one so the index map stays aligned.
            out.append(lowered if len(lowered) == 1 else piece)
            index_map.append(index)
        previous_space = False
    if out and out[-1] == " ":
        out.pop()
        index_map.pop()
    return "".join(out), index_map


def resolve(quote: str, page: PageText, threshold: float = 85.0) -> Match | Miss:
    """Find the quote on the page, or say how close the best attempt came."""
    if not page.has_text_layer:
        return Miss(page.page_no, 0.0, "no_text_layer")
    needle, _ = normalise(quote)
    haystack, index_map = normalise(page.text)
    if not needle or not haystack:
        return Miss(page.page_no, 0.0, "empty")

    def match(start: int, end: int, score: float, method: str) -> Match:
        char_start = index_map[start]
        char_end = index_map[end - 1] + 1
        return Match(
            page_no=page.page_no,
            char_start=char_start,
            char_end=char_end,
            bbox=_union(page.char_boxes[char_start:char_end]),
            score=round(score, 1),
            method=method,
        )

    start = _find_whole(needle, haystack)
    if start >= 0:
        return match(start, start + len(needle), 100.0, "exact")
    best = 0.0
    if len(needle) < MIN_FUZZY_QUOTE_CHARS:
        return Miss(page.page_no, best, "not_found")
    alignment = fuzz.partial_ratio_alignment(needle, haystack)
    if alignment is not None:
        best = float(alignment.score)
        if (
            alignment.score >= threshold
            and alignment.dest_end > alignment.dest_start
            and _whole(haystack, alignment.dest_start, alignment.dest_end)
            and _numbers(needle) <= _numbers(haystack[alignment.dest_start : alignment.dest_end])
        ):
            return match(alignment.dest_start, alignment.dest_end, best, "fuzzy")
    reordered = _locate_reordered(needle, haystack, threshold)
    if reordered is not None and reordered[1] > reordered[0]:
        return match(*reordered, "reordered")
    interleaved, share = _locate_interleaved(needle, haystack, index_map, page, threshold)
    if interleaved is not None:
        return interleaved
    return Miss(page.page_no, round(max(best, share), 1), "not_found")


def locate(quote: str, page: PageText, threshold: float = 85.0) -> Match | None:
    """resolve() for callers that only need the match."""
    found = resolve(quote, page, threshold)
    return found if isinstance(found, Match) else None


def resolve_pair(
    quote: str, first: PageText, second: PageText, threshold: float = 85.0
) -> Match | Miss:
    """A quote that runs from the foot of one page onto the head of the next. The two
    pages are read as one text; a match is reported on the page that holds the larger
    part of it, with the range and box cut to that page."""
    if not (first.has_text_layer and second.has_text_layer):
        return Miss(first.page_no, 0.0, "no_text_layer")
    joined = PageText(
        page_no=first.page_no,
        text=first.text + "\n" + second.text,
        char_boxes=[*first.char_boxes, None, *second.char_boxes],
    )
    found = resolve(quote, joined, threshold)
    if isinstance(found, Miss):
        return found
    boundary = len(first.text)
    if found.char_end <= boundary or found.char_start > boundary:
        # Entirely on one page: that page alone would have found it.
        page = first if found.char_end <= boundary else second
        return resolve(quote, page, threshold)
    on_first = boundary - found.char_start
    on_second = found.char_end - boundary - 1
    if on_first >= on_second:
        start, end, page = found.char_start, boundary, first
    else:
        start, end, page = 0, on_second, second
    return Match(
        page_no=page.page_no,
        char_start=start,
        char_end=end,
        bbox=_union(page.char_boxes[start:end]),
        score=found.score,
        method="page_boundary",
    )


def _numbers(text: str) -> set[str]:
    """The words that hold a digit, without edge punctuation. A near match must carry
    every one of the quote's: "928500" is not evidence on a page that says "928000"."""
    words = (word.strip(_EDGE_PUNCTUATION) for word in text.split())
    return {word for word in words if any(char.isdigit() for char in word)}


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


@dataclass(frozen=True)
class _Word:
    text: str
    start: int  # offsets in the normalised page text
    end: int
    x0: float | None  # left edge on the page, when the character has a box


@dataclass(frozen=True)
class _Chain:
    """Quote words matched so far, ending at page word `last`."""

    matched: tuple[tuple[int, int], ...]  # (first page word, last page word) per quote word
    skipped: int
    left: float | None  # the band of x positions where the matched words start:
    right: float | None  # the column the quote is being read down

    @property
    def last(self) -> int:
        return self.matched[-1][1]

    @property
    def span(self) -> int:
        return self.matched[-1][1] - self.matched[0][0]


def _locate_interleaved(
    needle: str, haystack: str, index_map: list[int], page: PageText, threshold: float
) -> tuple[Match | None, float]:
    """The quote's words found in order, with words of other columns between them.

    Each next word must follow within INTERLEAVED_LOOKAHEAD page words, or, when it starts
    inside the horizontal band of the words matched so far (a wrapped cell continuing
    under its first line), within INTERLEAVED_COLUMN_LOOKAHEAD. A page word that ends in a hyphen
    and is completed by a later word counts as the quoted word ("0002/26-" ... "27"). Every word
    that holds a digit must be found, so the value itself is always on the page; of the
    other words a quote of six or more may lose up to a tenth. Among the chains that
    satisfy this the tightest is taken. Returns the match, or None, and the share of the
    quote's words that the best chain found.
    """
    quoted = [word.strip(_EDGE_PUNCTUATION) for word in needle.split()]
    quoted = [word for word in quoted if word]
    if len(quoted) < MIN_INTERLEAVED_QUOTE_WORDS:
        return None, 0.0
    words = _page_words(haystack, index_map, page)
    positions: dict[str, list[int]] = {}
    for index, word in enumerate(words):
        positions.setdefault(word.text, []).append(index)
    needed = (
        100.0
        if len(quoted) < INTERLEAVED_PARTIAL_FROM_WORDS
        else max(threshold, INTERLEAVED_MIN_SCORE)
    )
    allowed_skips = int(len(quoted) * (100.0 - needed) / 100.0)

    def candidates(wanted: str) -> list[tuple[int, int]]:
        """(first, last) page words that spell the quoted word, whole or hyphen-split."""
        found = [(index, index) for index in positions.get(wanted, [])]
        for index, word in enumerate(words):
            head = word.text
            if len(head) < 2 or not head.endswith("-"):
                continue
            # "0002/26-" + "27" spells "0002/26-27"; "commis-" + "sioning" spells
            # "commissioning".
            for stem in (head, head[:-1]):
                if not wanted.startswith(stem) or len(wanted) <= len(stem):
                    continue
                for later in positions.get(wanted[len(stem) :], []):
                    if index < later <= index + INTERLEAVED_COLUMN_LOOKAHEAD:
                        found.append((index, later))
                        break
        return sorted(found)

    # chains[k]: for each page word a chain can end on, the tightest chain with k skips.
    chains: list[dict[int, _Chain]] = [{} for _ in range(allowed_skips + 1)]
    best_share = 0.0
    for number, wanted in enumerate(quoted):
        holds_digit = any(char.isdigit() for char in wanted)
        options = candidates(wanted)
        firsts = [first for first, _ in options]
        nxt: list[dict[int, _Chain]] = [{} for _ in range(allowed_skips + 1)]
        for skips, level in enumerate(chains):
            for chain in level.values():
                low = bisect_right(firsts, chain.last)
                for first, last in options[low:]:
                    gap = first - chain.last
                    if gap > INTERLEAVED_COLUMN_LOOKAHEAD:
                        break
                    x0 = words[first].x0
                    in_column = (
                        chain.left is not None
                        and chain.right is not None
                        and x0 is not None
                        and chain.left - COLUMN_EDGE_TOLERANCE
                        <= x0
                        <= chain.right + COLUMN_EDGE_TOLERANCE
                    )
                    if gap > INTERLEAVED_LOOKAHEAD and not in_column:
                        continue
                    starts = [x for x in (chain.left, chain.right, x0) if x is not None]
                    grown = _Chain(
                        (*chain.matched, (first, last)),
                        skips,
                        min(starts, default=None),
                        max(starts, default=None),
                    )
                    kept = nxt[skips].get(last)
                    if kept is None or grown.span < kept.span:
                        nxt[skips][last] = grown
                # The quoted word is left out, if it may be.
                if not holds_digit and skips < allowed_skips:
                    kept = nxt[skips + 1].get(chain.last)
                    if kept is None or chain.span < kept.span:
                        nxt[skips + 1][chain.last] = _Chain(
                            chain.matched, skips + 1, chain.left, chain.right
                        )
        # A chain may start at this word, the words before it having been left out.
        skipped_before = number
        digits_before = any(any(c.isdigit() for c in word) for word in quoted[:number])
        if skipped_before <= allowed_skips and not digits_before:
            for first, last in options:
                if last not in nxt[skipped_before]:
                    nxt[skipped_before][last] = _Chain(
                        ((first, last),), skipped_before, words[first].x0, words[first].x0
                    )
        chains = nxt
        longest = max((len(c.matched) for level in chains for c in level.values()), default=0)
        best_share = max(best_share, 100.0 * longest / len(quoted))
        if not any(chains):
            return None, round(best_share, 1)
    finished = [chain for level in chains for chain in level.values()]
    if not finished:
        return None, round(best_share, 1)
    chain = min(finished, key=lambda c: (c.skipped, c.span))
    score = 100.0 * len(chain.matched) / len(quoted)
    if score < needed:
        return None, round(score, 1)
    spans = []
    for first, last in chain.matched:
        for index in {first, last}:
            word = words[index]
            spans.append((index_map[word.start], index_map[word.end - 1] + 1))
    spans.sort()
    boxes = [box for begin, end in spans for box in page.char_boxes[begin:end]]
    return (
        Match(
            page_no=page.page_no,
            char_start=spans[0][0],
            char_end=spans[-1][1],
            bbox=_union(boxes),
            score=round(score, 1),
            method="interleaved",
        ),
        round(score, 1),
    )


def _page_words(haystack: str, index_map: list[int], page: PageText) -> list[_Word]:
    words: list[_Word] = []
    position = 0
    for raw in haystack.split(" "):
        word = raw.strip(_EDGE_PUNCTUATION)
        if word:
            offset = position + raw.index(word)
            original = index_map[offset]
            box = page.char_boxes[original] if original < len(page.char_boxes) else None
            words.append(_Word(word, offset, offset + len(word), box[0] if box else None))
        position += len(raw) + 1
    return words


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
