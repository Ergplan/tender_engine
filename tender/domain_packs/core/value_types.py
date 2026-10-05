"""Value types the tender schemas use on top of core's. Deterministic, plain Python."""

import re
from typing import Any

from core.schemas import FieldDef, KeyDef, ValueType, ValueTypeRegistry
from core.schemas.types import parse_number

# What a model or a reviewer writes for a key the document does not state.
_UNSTATED = {"", "null", "none", "not stated", "not specified", "n/a", "na", "-"}
_TIME = re.compile(r"^([01]?\d|2[0-4])[:.]?([0-5]\d)$")


def _non_negative(raw: Any, field: FieldDef) -> float | int:
    number = parse_number(raw)
    if number < 0:
        raise ValueError(f"expected a non-negative number, got {raw!r}")
    return number


def _percent(raw: Any, field: FieldDef) -> float | int:
    number = parse_number(raw)
    if not 0 <= number <= 100:
        raise ValueError(f"expected a percentage between 0 and 100, got {raw!r}")
    return number


def _months(raw: Any, field: FieldDef) -> int:
    number = parse_number(raw)
    if not isinstance(number, int) or number < 0:
        raise ValueError(f"expected a whole number of months, got {raw!r}")
    return number


def _time(raw: Any, field: FieldDef) -> str:
    """A time of day as HH:MM (24 hours)."""
    match = _TIME.match(str(raw).strip().lower().replace(" hrs", "").replace("hrs", ""))
    if not match:
        raise ValueError(f"expected a time as HH:MM, got {raw!r}")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


SCALAR_TYPES = (
    ValueType("money_inr", "number", _non_negative),
    ValueType("percent", "number", _percent),
    ValueType("duration_months", "integer", _months),
    ValueType("mw", "number", _non_negative),
    ValueType("mwh", "number", _non_negative),
    ValueType("kv", "number", _non_negative),
    ValueType("km", "number", _non_negative),
    ValueType("time", "string", _time),
)
NUMBER_KEY_TYPES = frozenset(
    {"int", "decimal", "money_inr", "percent", "duration_months", "mw", "mwh", "kv", "km"}
)
# The types a key of a record may have: core's scalars and the ones above.
_SCALARS = ValueTypeRegistry()
for _scalar in SCALAR_TYPES:
    _SCALARS.register(_scalar)


def _unstated(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and raw.strip().lower() in _UNSTATED)


def _key_value(raw: Any, key: KeyDef, where: str) -> Any:
    """One key's value in its type, or None when it is not stated."""
    if _unstated(raw):
        return None
    as_field = FieldDef(
        path=f"record.{key.name}",
        label=key.label or key.name,
        group="record",
        value_type=key.value_type,
        enum_values=key.enum_values,
    )
    if key.value_type in ("text", "long_text") and not isinstance(raw, str):
        raw = str(raw)
    try:
        value = _SCALARS.coerce(raw, as_field)
    except ValueError as exc:
        raise ValueError(f"{where}`{key.name}`: {exc}") from exc
    if isinstance(value, int | float) and not isinstance(value, bool):
        if key.min is not None and value < key.min:
            raise ValueError(f"{where}`{key.name}`: {value} is below {key.min}")
        if key.max is not None and value > key.max:
            raise ValueError(f"{where}`{key.name}`: {value} is above {key.max}")
    return value


def _pairs(text: str, outer: str, inner: str, what: str) -> dict[str, str]:
    """`key<inner>value<outer>key<inner>value` as a dict; keys in lower case."""
    record = {}
    for part in text.split(outer):
        if not part.strip():
            continue
        key, sep, value = part.partition(inner)
        if not sep:
            raise ValueError(f"expected {what}, got {text!r}")
        record[key.strip().lower()] = value.strip()
    return record


def _typed(record: dict[str, Any], keys: list[KeyDef], where: str = "") -> dict[str, Any]:
    """Every key of `keys`, in their order, each in its type or None. A key that is not
    among them is an error."""
    unknown = sorted(set(record) - {key.name for key in keys})
    if unknown:
        raise ValueError(f"{where}unknown key(s) {unknown}; expected {[k.name for k in keys]}")
    typed: dict[str, Any] = {}
    for key in keys:
        raw = record.get(key.name)
        if key.keys is None:
            typed[key.name] = _key_value(raw, key, where)
            continue
        items = [] if _unstated(raw) else raw
        if not isinstance(items, list):
            raise ValueError(f"{where}`{key.name}`: expected a list")
        rows = []
        for item in items:
            row = (
                item
                if isinstance(item, dict)
                else _pairs(str(item), ";", "=", "`key=value; key=value`")
            )
            row = _typed(row, key.keys, f"{where}`{key.name}`: ")
            if any(value is not None for value in row.values()):
                rows.append(row)
        typed[key.name] = rows or None
    return typed


def parse_record(raw: Any, keys: list[KeyDef]) -> dict[str, Any]:
    """A record from what the model writes (a list of `key: value` lines; a key that holds
    a list is written once per item, as `key: sub=value; sub=value`) or from a record
    itself (a reviewer's edit, a stored value)."""
    lists = {key.name for key in keys if key.keys is not None}
    if isinstance(raw, dict):
        record: dict[str, Any] = {str(key).strip().lower(): value for key, value in raw.items()}
    elif isinstance(raw, list) and all(isinstance(line, str) for line in raw):
        record = {}
        for line in raw:
            if not line.strip():
                continue
            key, sep, value = line.partition(":")
            key = key.strip().lower()
            if not sep:
                raise ValueError(f"expected `key: value`, got {line!r}")
            if key in lists:
                if not _unstated(value):
                    record.setdefault(key, []).append(value.strip())
            elif key in record:
                raise ValueError(f"`{key}` is given twice")
            else:
                record[key] = value.strip()
    else:
        raise ValueError("expected a list of `key: value` lines")
    typed = _typed(record, keys)
    if all(value is None for value in typed.values()):
        raise ValueError("no key has a value; a record nothing is stated for must be null")
    return typed


def _record(raw: Any, field: FieldDef) -> dict[str, Any]:
    if not field.keys:
        raise ValueError(f"{field.path} is a record without keys")
    return parse_record(raw, field.keys)


def _record_list(raw: Any, field: FieldDef) -> list[dict[str, Any]]:
    """A list of records. The model writes each item as `key: value | key: value`; a
    reviewer's edit may send the records themselves. With typed `keys` every record has
    all of them, each in its type or None, and the first must be stated. With `item_keys`
    only (schema v1) values stay text and the first item key is required."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("expected a list with at least one item")
    names = [key.name for key in field.keys] if field.keys else (field.item_keys or [])
    records: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            record = {str(key).strip(): value for key, value in item.items()}
        elif isinstance(item, str):
            record = dict(_pairs(item, "|", ":", "`key: value | key: value`"))
        else:
            raise ValueError(f"expected text items, got {item!r}")
        if field.keys:
            typed = _typed(record, field.keys)
            if typed[names[0]] is None:
                raise ValueError(f"every item needs `{names[0]}`")
            records.append(typed)
            continue
        record = {key: str(value).strip() for key, value in record.items()}
        record = {key: value for key, value in record.items() if value}
        unknown = sorted(set(record) - set(names))
        if unknown:
            raise ValueError(f"unknown key(s) {unknown}; expected {names}")
        if not names or names[0] not in record:
            raise ValueError(f"every item needs `{names[0] if names else 'a key'}`")
        records.append(record)
    return records


VALUE_TYPES = (
    *SCALAR_TYPES,
    ValueType("record_list", "string_list", _record_list),
    ValueType("record", "string_list", _record),
)


def register_value_types(registry: ValueTypeRegistry) -> None:
    for value_type in VALUE_TYPES:
        registry.register(value_type)
