"""Chunks of a page for retrieval. Pure: no database, no model.

A page is cut at the lines that open a numbered clause (`12.3 The Bidder shall…`,
`Clause 5`, `Article 3.1`, `Section 4`), short clauses are merged and long ones split, so
that a chunk is one clause or part of one. Each chunk carries the clause number the text
stands under and its character offsets into the page text, so a quote taken from it is
resolved on the page like any other evidence (`core.evidence.resolve`)."""

import hashlib
import re
from dataclasses import dataclass

MAX_CHARS = 1500
MIN_CHARS = 300

_CLAUSE = re.compile(
    r"^\s*(?:(?P<word>clause|article|section|para(?:graph)?|item)\s+)?"
    r"(?P<number>\d{1,3}(?:\.\d{1,3}){0,4})\s*[.):]?\s+(?P<rest>\S.*)?$",
    re.IGNORECASE,
)
_MONTHS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}  # fmt: skip
_UNITS = {"mw", "mwh", "kv", "kwh", "inr", "rs", "rs.", "crore", "crores", "lakh", "lakhs", "%"}


def clause_of(line: str) -> str | None:
    """The clause number a line opens, or None. A bare number needs a capitalised word
    after it that is not a month or a unit (`30 March 2026` and `600 MW` open nothing); a
    dotted number (`12.3`) is a clause whatever follows."""
    match = _CLAUSE.match(line)
    if match is None:
        return None
    number = match.group("number")
    rest = (match.group("rest") or "").strip()
    if match.group("word"):
        # `SECTION 3: SECURITY AND CAPACITY` is a part heading, not a clause.
        if match.group("word").lower() == "section" and rest and rest.upper() == rest:
            return None
        return number
    if "." in number:
        return number
    if not rest:
        return None
    first = rest.split()[0].strip("(),;:").lower()
    if first in _MONTHS or first in _UNITS or not rest[0].isalpha() or not rest[0].isupper():
        return None
    return number if int(number) <= 99 else None


@dataclass(frozen=True)
class Chunk:
    page_no: int
    clause: str | None
    char_start: int
    char_end: int
    text: str

    def id(self, document_id: str) -> str:
        raw = f"{document_id}:{self.page_no}:{self.char_start}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def chunk_page(
    page_no: int,
    text: str,
    *,
    carry_clause: str | None = None,
    max_chars: int = MAX_CHARS,
    min_chars: int = MIN_CHARS,
) -> list[Chunk]:
    """Cut one page's text into chunks. `carry_clause` is the clause the previous page ended
    under, for the text before this page's first clause heading. Offsets are into `text`,
    so `text[chunk.char_start:chunk.char_end] == chunk.text`."""
    chunks: list[Chunk] = []
    lines: list[tuple[int, str]] = []  # (offset, line)
    offset = 0
    for line in text.split("\n"):
        lines.append((offset, line))
        offset += len(line) + 1

    current: list[tuple[int, str]] = []
    current_clause = carry_clause
    own_clause_lines = 0  # clause headings inside the current chunk

    def flush() -> None:
        if not current:
            return
        start = current[0][0]
        end = current[-1][0] + len(current[-1][1])
        body = text[start:end]
        if body.strip():
            chunks.append(Chunk(page_no, current_clause, start, end, body))
        current.clear()

    def size() -> int:
        return (current[-1][0] + len(current[-1][1]) - current[0][0]) if current else 0

    for item in lines:
        clause = clause_of(item[1])
        if clause is not None:
            if size() >= min_chars:
                flush()
                own_clause_lines = 0
            # A short run of text before this heading (a part title, a carried-over line)
            # is merged into the clause and takes its number.
            if own_clause_lines == 0:
                current_clause = clause
            own_clause_lines += 1
        if current and size() + len(item[1]) + 1 > max_chars:
            flush()
        current.append(item)
    flush()
    return chunks


def last_clause(chunks: list[Chunk]) -> str | None:
    """The clause the page ends under, to carry into the next page."""
    return chunks[-1].clause if chunks else None
