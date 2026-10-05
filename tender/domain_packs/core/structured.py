"""The two checks on structured fields (records a financial model computes with). Plain
Python, no model call.

1. Every number of a structured value must occur in one of the field's own quotes.
2. A structured key must agree with the scalar field that holds the same fact.
"""

import math
import re
from collections.abc import Sequence
from functools import cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Candidate, EvidenceSpan, ExtractionRun
from core.schemas import CandidateOutcome, FieldDef, KeyDef, RuleOutcome
from tender.domain_packs.core.value_types import NUMBER_KEY_TYPES, VALUE_TYPES

QUOTED_RULE = "structured_numbers_quoted"
# A limit written as a share of the declared CUF is printed as a distance from it:
# "+10% / -15%" is 110 and 85.
RELATIVE_UNIT = "percent of declared CUF"
_COERCE = {value_type.name: value_type.coerce for value_type in VALUE_TYPES}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SCALE = re.compile(r"(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr\b|paisa|paise)")
_SCALES = {"lakh": 1e5, "lac": 1e5, "crore": 1e7, "cr": 1e7, "pais": 0.01}
_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}  # fmt: skip
_OTHER = {"half": 0.5, "twice": 2, "double": 2, "hundred": 100, "single": 1, "once": 1}
_WORD = re.compile(r"[a-z]+")


def numbers_in(text: str) -> set[float]:
    """Every number a passage prints: digits (separators removed), amounts in lakh, crore
    and paise also in rupees, and numbers written as words up to ninety-nine, with "and a
    half"."""
    text = re.sub(r"(?<=\d),(?=\d)", "", text.lower())
    found = {float(match) for match in _NUMBER.findall(text)}
    for amount, scale in _SCALE.findall(text):
        factor = next(value for name, value in _SCALES.items() if scale.startswith(name))
        found.add(float(amount) * factor)
    words = _WORD.findall(text.replace("-", " "))
    for position, word in enumerate(words):
        value: float | None = None
        if word in _TENS:
            following = words[position + 1] if position + 1 < len(words) else ""
            value = _TENS[word] + (
                _UNITS[following] if following in _UNITS and _UNITS[following] < 10 else 0
            )
            found.add(float(_TENS[word]))
        elif word in _UNITS:
            value = _UNITS[word]
        elif word in _OTHER:
            value = _OTHER[word]
        if value is None:
            continue
        found.add(float(value))
        if words[position + 1 : position + 4] == ["and", "a", "half"]:
            found.add(value + 0.5)
    return found


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def _numbers_of(
    value: Any, keys: list[KeyDef], prefix: str = ""
) -> list[tuple[str, float, KeyDef]]:
    """Every stated number of a record or a list of records, with the key it stands under."""
    if isinstance(value, list):
        return [
            item
            for position, record in enumerate(value, start=1)
            for item in _numbers_of(record, keys, f"{prefix}{position}.")
        ]
    numbers = []
    for key in keys:
        part = value.get(key.name)
        if part is None:
            continue
        if key.keys:
            numbers += _numbers_of(part, key.keys, f"{prefix}{key.name} ")
        elif key.value_type in NUMBER_KEY_TYPES and not isinstance(part, bool):
            numbers.append((f"{prefix}{key.name}", float(part), key))
    return numbers


def unquoted_numbers(value: Any, field: FieldDef, quotes: Sequence[str]) -> list[str]:
    """The numbers of a structured value (already in its type) that none of the quotes
    prints, each as `key value`."""
    printed: set[float] = set()
    for quote in quotes:
        printed |= numbers_in(quote)
    missing = []
    for name, number, key in _numbers_of(value, field.keys or []):
        wanted = [number]
        if key.unit == RELATIVE_UNIT:
            wanted += [abs(number - 100)]
        if key.value_type == "decimal":
            # A multiple or a count of months may be printed as a percentage: 0.5 times
            # the tariff as "50%", 1.1 months of billing as "110%".
            wanted += [number * 100]
        if not any(_same(candidate, seen) for candidate in wanted for seen in printed):
            missing.append(f"{name} {number:g}")
    return missing


@cache
def _schemas() -> dict[tuple[str, str], dict[str, FieldDef]]:
    """The structured fields of every compiled schema, by schema name and version."""
    from tender.services.packs import load_catalog  # the catalog imports this package

    found: dict[tuple[str, str], dict[str, FieldDef]] = {}
    for compiled in load_catalog().types.values():
        fields = {field.path: field for field in compiled.schema.fields if field.keys}
        for version in (compiled.schema.version, *compiled.reads_versions):
            found[(compiled.schema.name, version)] = fields
    return found


def structured_numbers_quoted(
    session: Session, run: ExtractionRun, candidates: Sequence[Candidate]
) -> list[CandidateOutcome]:
    """Every number of a structured value occurs in one of that candidate's own quotes."""
    fields = _schemas().get((run.schema_name, run.schema_version), {})
    own = [candidate for candidate in candidates if candidate.field_path in fields]
    if not own:
        return []
    quotes: dict[str, list[str]] = {candidate.id: [] for candidate in own}
    for candidate_id, quote in session.execute(
        select(EvidenceSpan.candidate_id, EvidenceSpan.quote).where(
            EvidenceSpan.candidate_id.in_(list(quotes)), EvidenceSpan.tenant_id == run.tenant_id
        )
    ):
        quotes[candidate_id].append(quote)
    outcomes = []
    for candidate in own:
        field = fields[candidate.field_path]
        try:
            value = _COERCE[field.value_type](candidate.value, field)
        except ValueError:
            continue  # not a well-formed record: reported by the type check
        missing = unquoted_numbers(value, field, quotes[candidate.id])
        if missing:
            message = "not printed in this field's quotes: " + ", ".join(missing)
            outcomes.append(CandidateOutcome(candidate.id, False, message))
        else:
            message = "every number is printed in this field's quotes"
            outcomes.append(CandidateOutcome(candidate.id, True, message))
    return outcomes


# (scalar field, structured field, key). For a list of records the scalar must equal the
# key of at least one item.
Pair = tuple[str, str, str]
CORE_PAIRS: tuple[Pair, ...] = (
    ("core.guarantees.emd_per_mw_inr", "core.guarantees.emd_structured", "rate_inr_per_mw"),
    ("core.guarantees.pbg_per_mw_inr", "core.guarantees.pbg_structured", "rate_inr_per_mw"),
    (
        "core.penalties.delay_ld_per_mw_per_day_inr",
        "core.penalties.delay_ld_structured",
        "rate_inr_per_mw_per_day",
    ),
)


def agreement(values: dict[str, Any], pairs: Sequence[Pair]) -> list[RuleOutcome]:
    """One outcome per pair whose structured field has a value: the scalar and the key say
    the same, or one of them is missing where the other is stated, or they differ."""
    outcomes = []
    for scalar_path, record_path, key in pairs:
        record = values.get(record_path)
        if record is None:
            continue
        scalar = values.get(scalar_path)
        items = record if isinstance(record, list) else [record]
        stated = [item[key] for item in items if item.get(key) is not None]
        name = f"`{key}` of {record_path.rsplit('.', 1)[1]}"
        label = scalar_path.rsplit(".", 1)[1]
        paths = (scalar_path, record_path)
        if scalar is None and not stated:
            continue
        if scalar is None:
            shown = ", ".join(f"{value:g}" for value in stated)
            message = f"{name} is {shown} but {label} has no value"
            if isinstance(record, list):
                continue  # a list may hold rules the scalar does not speak of
            outcomes.append(RuleOutcome((record_path,), False, message))
        elif not stated:
            message = f"{label} is {scalar:g} but {name} is not stated"
            outcomes.append(RuleOutcome((record_path,), False, message))
        elif any(_same(float(scalar), float(value)) for value in stated):
            outcomes.append(RuleOutcome(paths, True, f"{name} agrees with {label} ({scalar:g})"))
        else:
            shown = ", ".join(f"{value:g}" for value in stated)
            message = f"{name} is {shown} but {label} is {scalar:g}"
            outcomes.append(RuleOutcome(paths, False, message))
    return outcomes


def structured_agrees_with_scalar(values: dict[str, Any]) -> list[RuleOutcome]:
    return agreement(values, CORE_PAIRS)
