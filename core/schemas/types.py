"""Value types: how a raw model value becomes a normalised, JSON-storable value.

Coercion is deterministic, plain Python. A domain layer may register more types.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from core.schemas.model import FieldDef

JsonKind = Literal["string", "number", "integer", "boolean", "string_list"]
Coercer = Callable[[Any, FieldDef], Any]

_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DMY = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")
_D_MON_Y = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-.,]+([a-z]+)[\s\-.,]+(\d{4})$")
_MON_D_Y = re.compile(r"^([a-z]+)[\s\-.]+(\d{1,2})(?:st|nd|rd|th)?[\s,]+(\d{4})$")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


@dataclass(frozen=True)
class ValueType:
    name: str
    json_kind: JsonKind
    coerce: Coercer


def _text(raw: Any, field: FieldDef) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("expected non-empty text")
    return raw.strip()


def _number(raw: Any) -> float | int:
    if isinstance(raw, bool):
        raise ValueError("expected a number, got a boolean")
    if isinstance(raw, int | float):
        number: float | int = raw
    elif isinstance(raw, str) and _NUMBER.match(raw.replace(",", "").strip()):
        number = float(raw.replace(",", "").strip())
    else:
        raise ValueError(f"expected a number, got {raw!r}")
    return int(number) if float(number).is_integer() else float(number)


def _decimal(raw: Any, field: FieldDef) -> float | int:
    return _number(raw)


def _int(raw: Any, field: FieldDef) -> int:
    number = _number(raw)
    if not isinstance(number, int):
        raise ValueError(f"expected a whole number, got {raw!r}")
    return number


def _date(raw: Any, field: FieldDef) -> str:
    """Accepts ISO and the day-first forms Indian documents use. Returns YYYY-MM-DD."""
    if not isinstance(raw, str):
        raise ValueError(f"expected a date string, got {raw!r}")
    text = raw.strip().lower()
    year = month = day = 0
    if match := _ISO.match(text):
        year, month, day = (int(part) for part in match.groups())
    elif match := _DMY.match(text):
        day, month, year = (int(part) for part in match.groups())
    elif match := _D_MON_Y.match(text):
        day, year = int(match.group(1)), int(match.group(3))
        month = _MONTHS.get(match.group(2), 0)
    elif match := _MON_D_Y.match(text):
        day, year = int(match.group(2)), int(match.group(3))
        month = _MONTHS.get(match.group(1), 0)
    else:
        raise ValueError(f"unrecognised date {raw!r}")
    try:
        return date(year, month, day).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid date {raw!r}") from exc


def _bool(raw: Any, field: FieldDef) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().lower() in {"yes", "true"}:
        return True
    if isinstance(raw, str) and raw.strip().lower() in {"no", "false"}:
        return False
    raise ValueError(f"expected yes/no, got {raw!r}")


def _enum(raw: Any, field: FieldDef) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"expected one of {field.enum_values}, got {raw!r}")
    value = re.sub(r"[\s\-]+", "_", raw.strip().lower())
    if value not in (field.enum_values or []):
        raise ValueError(f"expected one of {field.enum_values}, got {raw!r}")
    return value


def _list_text(raw: Any, field: FieldDef) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("expected a list of text items")
    items = [item.strip() for item in raw if item.strip()]
    if not items:
        raise ValueError("expected at least one item")
    return items


class ValueTypeRegistry:
    def __init__(self) -> None:
        self._types: dict[str, ValueType] = {}
        for value_type in (
            ValueType("text", "string", _text),
            ValueType("long_text", "string", _text),
            ValueType("int", "integer", _int),
            ValueType("decimal", "number", _decimal),
            ValueType("date", "string", _date),
            ValueType("bool", "boolean", _bool),
            ValueType("enum", "string", _enum),
            ValueType("list_text", "string_list", _list_text),
        ):
            self.register(value_type)

    def register(self, value_type: ValueType) -> None:
        if value_type.name in self._types:
            raise ValueError(f"value type {value_type.name!r} is already registered")
        self._types[value_type.name] = value_type

    def get(self, name: str) -> ValueType:
        try:
            return self._types[name]
        except KeyError:
            raise ValueError(f"unknown value type {name!r}") from None

    def coerce(self, raw: Any, field: FieldDef) -> Any:
        """Normalise raw to the field's type, or raise ValueError with a plain message."""
        return self.get(field.value_type).coerce(raw, field)
