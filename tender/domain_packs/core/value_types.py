"""Value types the tender schemas use on top of core's. Deterministic, plain Python."""

from typing import Any

from core.schemas import FieldDef, ValueType, ValueTypeRegistry
from core.schemas.types import parse_number


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


def _record_list(raw: Any, field: FieldDef) -> list[dict[str, str]]:
    """A list of records. The model writes each item as `key: value | key: value`; a
    reviewer's edit may send the records themselves. Keys must be among the field's
    item_keys; the first item key is required in every record."""
    keys = field.item_keys or []
    if not isinstance(raw, list) or not raw:
        raise ValueError("expected a list with at least one item")
    records = []
    for item in raw:
        if isinstance(item, dict):
            record = {str(key).strip(): str(value).strip() for key, value in item.items()}
        elif isinstance(item, str):
            record = {}
            for part in item.split("|"):
                key, sep, value = part.partition(":")
                if not sep:
                    raise ValueError(f"expected `key: value | key: value`, got {item!r}")
                record[key.strip().lower()] = value.strip()
        else:
            raise ValueError(f"expected text items, got {item!r}")
        record = {key: value for key, value in record.items() if value}
        unknown = sorted(set(record) - set(keys))
        if unknown:
            raise ValueError(f"unknown key(s) {unknown}; expected {keys}")
        if not keys or keys[0] not in record:
            raise ValueError(f"every item needs `{keys[0] if keys else 'a key'}`")
        records.append(record)
    return records


VALUE_TYPES = (
    ValueType("money_inr", "number", _non_negative),
    ValueType("percent", "number", _percent),
    ValueType("duration_months", "integer", _months),
    ValueType("mw", "number", _non_negative),
    ValueType("mwh", "number", _non_negative),
    ValueType("kv", "number", _non_negative),
    ValueType("km", "number", _non_negative),
    ValueType("record_list", "string_list", _record_list),
)


def register_value_types(registry: ValueTypeRegistry) -> None:
    for value_type in VALUE_TYPES:
        registry.register(value_type)
