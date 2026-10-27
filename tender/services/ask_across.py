"""Cross-tender questions (Stage 7, Block 5 c): "which tenders allow thermal with RECs" is
a structured search over canonical facts, never retrieval. The question is read into one
query (field, operator, value) by the same field mapping `ask_tender` uses plus the value
words of the question; the query that was run is returned with the answer, so the caller
sees what was searched and can send the structured form directly. Only approved facts
count: a tender whose field is read but not reviewed is listed as such, not matched."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.schemas.model import ExtractionSchema, FieldDef
from tender.models import Tender
from tender.services.ask_fields import map_question, words
from tender.services.current_view import current_view
from tender.services.packs import Catalog

Operator = Literal["==", "!=", ">", ">=", "<", "<=", "contains", "in", "any"]
AUTHORITY_NOTE = (
    "Matched on approved facts only; a tender with a machine reading but no decision on "
    "the field is listed under `unreviewed`, not matched."
)

_COMPARATORS: tuple[tuple[Operator, tuple[str, ...]], ...] = (
    (">=", ("at least", "minimum of", "not less than", "or more", "or above", "from")),
    ("<=", ("at most", "not more than", "up to", "maximum of", "or less", "or below")),
    (
        ">",
        ("above", "over", "more than", "greater than", "exceeding", "larger than", "bigger than"),
    ),
    ("<", ("below", "under", "less than", "smaller than", "lower than")),
)
# Value types that hold one number (the power pack registers its own beside core's).
NUMERIC_TYPES = frozenset(
    {"int", "decimal", "money_inr", "mw", "mwh", "percent", "duration_months", "duration_days"}
)
_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w.])")
_NEGATION = (
    "not allow",
    "disallow",
    "prohibit",
    "bar ",
    "barred",
    "without",
    "do not permit",
    "no ",
)
_AFFIRM = ("allow", "permit", "accept", "with ", "may ", "can ")


class CrossQuery(BaseModel):
    field_path: str
    label: str | None = None
    operator: Operator = "any"
    value: Any = None


class CrossHit(BaseModel):
    tender_id: str
    slug: str | None
    title: str
    tender_type: str
    value: Any
    unit: str | None
    version_no: int | None
    evidence_pages: list[int]


class CrossAnswer(BaseModel):
    question: str | None
    query: CrossQuery
    matched: list[CrossHit]
    considered: int
    without_field: int
    unreviewed: list[str]
    answer: str
    is_fact: Literal[False] = False
    authority_note: str = AUTHORITY_NOTE


class CrossError(Exception):
    pass


def parse_cross_question(question: str, schema: ExtractionSchema) -> CrossQuery | None:
    """Read a question into one structured query over the schema's fields, or None when
    no field of the schema is what the question is about."""
    match = map_question(question, schema)
    if match is None:
        return None
    field = match.field
    lowered = " " + " ".join(question.lower().split()) + " "
    if field.enum_values:
        asked = set(words(question))
        chosen = [
            v
            for v in field.enum_values
            if set(words(v.replace("_", " "))) and set(words(v.replace("_", " "))) <= asked
        ]
        if len(chosen) == 1:
            return CrossQuery(
                field_path=field.path, label=field.label, operator="==", value=chosen[0]
            )
        if chosen:
            return CrossQuery(field_path=field.path, label=field.label, operator="in", value=chosen)
        return CrossQuery(field_path=field.path, label=field.label)
    if field.value_type in NUMERIC_TYPES:
        numbers = [float(n.replace(",", "")) for n in _NUMBER.findall(question)]
        if numbers:
            operator: Operator = "=="
            for op, phrases in _COMPARATORS:
                if any(p in lowered for p in phrases):
                    operator = op
                    break
            value = numbers[-1]
            return CrossQuery(
                field_path=field.path,
                label=field.label,
                operator=operator,
                value=int(value) if value.is_integer() else value,
            )
        return CrossQuery(field_path=field.path, label=field.label)
    if field.value_type == "bool":
        if any(n in lowered for n in _NEGATION):
            return CrossQuery(field_path=field.path, label=field.label, operator="==", value=False)
        if any(a in lowered for a in _AFFIRM):
            return CrossQuery(field_path=field.path, label=field.label, operator="==", value=True)
        return CrossQuery(field_path=field.path, label=field.label)
    if field.value_type in ("text", "long_text", "list_text"):
        # The words of the question that are not the field's own name are what to look for.
        from tender.services.ask_fields import label_words

        rest = [w for w in words(question) if w not in label_words(field)]
        if rest:
            return CrossQuery(
                field_path=field.path, label=field.label, operator="contains", value=" ".join(rest)
            )
    return CrossQuery(field_path=field.path, label=field.label)


def matches(value: Any, operator: Operator, wanted: Any) -> bool:
    if operator == "any":
        return value is not None
    if value is None:
        return False
    if operator == "in":
        options = {str(w).lower() for w in (wanted or [])}
        if isinstance(value, list):
            return any(str(v).lower() in options for v in value)
        return str(value).lower() in options
    if operator == "contains":
        haystack = " ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        return all(w in haystack.lower() for w in str(wanted).lower().split())
    if operator in ("==", "!="):
        if isinstance(value, list):
            same = any(_same(v, wanted) for v in value)
        else:
            same = _same(value, wanted)
        return same if operator == "==" else not same
    try:
        left, right = float(value), float(wanted)
    except (TypeError, ValueError):
        return False
    return {">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right}[
        operator
    ]


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return (
            bool(a) == bool(b)
            if isinstance(a, bool) and isinstance(b, bool)
            else str(a).lower() == str(b).lower()
        )
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def search_facts(
    session: Session,
    catalog: Catalog,
    tenders: Iterable[Tender],
    query: CrossQuery,
    *,
    question: str | None = None,
) -> CrossAnswer:
    """Every tender whose approved fact for the field satisfies the query."""
    matched: list[CrossHit] = []
    unreviewed: list[str] = []
    considered = without_field = 0
    unit: str | None = None
    for tender in tenders:
        considered += 1
        compiled = catalog.get(tender.tender_type)
        field: FieldDef | None = next(
            (f for f in compiled.schema.fields if f.path == query.field_path), None
        )
        if field is None:
            without_field += 1
            continue
        unit = unit or field.unit
        view = current_view(session, catalog, tender)
        fv = next((f for f in view.fields if f.field_path == field.path), None)
        if fv is None or not fv.decided or fv.withdrawn:
            unreviewed.append(tender.slug or tender.id)
            continue
        if matches(fv.value, query.operator, query.value):
            matched.append(
                CrossHit(
                    tender_id=tender.id,
                    slug=tender.slug,
                    title=tender.title,
                    tender_type=tender.tender_type,
                    value=fv.value,
                    unit=fv.unit,
                    version_no=fv.version_no,
                    evidence_pages=sorted(
                        {int(e["page_no"]) for e in fv.evidence if e.get("page_no")}
                    ),
                )
            )
    label = query.label or query.field_path
    condition = "has a value" if query.operator == "any" else f"{query.operator} {query.value}"
    text = (
        f"{len(matched)} of {considered} tenders match on approved facts: {label} {condition}"
        + (f" ({unit})" if unit and query.operator != "any" else "")
        + f". {len(unreviewed)} have no approved value for the field; "
        f"{without_field} have no such field."
    )
    return CrossAnswer(
        question=question,
        query=query,
        matched=matched,
        considered=considered,
        without_field=without_field,
        unreviewed=unreviewed,
        answer=text,
    )
