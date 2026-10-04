"""Generic per-field rules. Each returns (rule_name, passed, message) or None if not applicable."""

import re
from typing import Any

from core.schemas import FieldDef

RuleResult = tuple[str, bool, str]


def range_rule(field: FieldDef, value: Any) -> RuleResult | None:
    low, high = field.validation.min, field.validation.max
    if low is None and high is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if low is not None and value < low:
        return ("range", False, f"{value} is below the minimum {low:g}")
    if high is not None and value > high:
        return ("range", False, f"{value} is above the maximum {high:g}")
    return ("range", True, "within range")


def regex_rule(field: FieldDef, value: Any) -> RuleResult | None:
    pattern = field.validation.regex
    if pattern is None or not isinstance(value, str):
        return None
    if re.fullmatch(pattern, value):
        return ("regex", True, "matches the expected pattern")
    return ("regex", False, f"{value!r} does not match the expected pattern {pattern!r}")


FIELD_RULES = (range_rule, regex_rule)
