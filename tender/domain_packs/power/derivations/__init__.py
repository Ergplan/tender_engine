"""Derivation rules of the power pack: deterministic code that writes the fields of the
`derived` section from the tender's decided fields (producer DERIVED).

A rule names the fields it reads, and gives back rows that each carry the clause they rest
on. It never reads a page, never calls a model, and never fills a row from what is usual
for the tender type: a row with no decided clause behind it says so (`not_addressed`, no
constraint). Each rule module has a VERSION; the candidate stores it as its prompt version
so that a change of rule is a new reading.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.services.review_state import EvidenceView


@dataclass(frozen=True)
class Decided:
    """A decided field of the tender: the value that stands (the reviewer's where they
    edited), the located evidence behind it, and where it comes from."""

    path: str
    label: str
    value: Any
    spans: list[EvidenceView]
    version_no: int


@dataclass(frozen=True)
class Row:
    """One row of a derived table and the decided fields it rests on. `inherited` marks a
    row read off a general clause rather than one naming its subject."""

    value: dict[str, Any]
    inputs: tuple[str, ...]
    inherited: bool = False


@dataclass(frozen=True)
class Derivation:
    rows: list[Row]
    # What the rule had to say about the record, for the candidate's rationale.
    note: str = ""


Inputs = dict[str, Decided]


@dataclass(frozen=True)
class Rule:
    field_path: str
    module: str
    version: str
    inputs: tuple[str, ...]
    derive: Callable[[Inputs], Derivation]
    # The record of the rows, for the reader: the key that names a row.
    row_key: str = "source"
    extra: dict[str, Any] = field(default_factory=dict)


def clause_of(decided: Decided, keyword: str | None = None) -> str:
    """The clause a row cites: page and quote of the span that mentions `keyword`, else of
    the first located span."""
    spans = decided.spans
    if keyword:
        wanted = keyword.lower()
        spans = [s for s in decided.spans if wanted in s.quote.lower()] or decided.spans
    if not spans:
        return ""
    span = spans[0]
    quote = " ".join(span.quote.split())
    if len(quote) > 240:
        quote = quote[:237].rstrip() + "..."
    return f"p.{span.page_no}: “{quote}”"


def record_of(decided: Decided | None) -> dict[str, Any]:
    value = decided.value if decided is not None else None
    return value if isinstance(value, dict) else {}


def records_of(decided: Decided | None) -> list[dict[str, Any]]:
    value = decided.value if decided is not None else None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _registry() -> dict[str, Rule]:
    from tender.domain_packs.power.derivations import optimizer_constraints, source_eligibility

    return {rule.field_path: rule for rule in (source_eligibility.RULE, optimizer_constraints.RULE)}


def rules() -> list[Rule]:
    return list(_registry().values())


def rule_for(field_path: str) -> Rule:
    try:
        return _registry()[field_path]
    except KeyError:
        raise LookupError(f"no derivation rule writes {field_path!r}") from None
