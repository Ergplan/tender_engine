from core.schemas import FieldDef, FieldValidation
from core.validation.rules import range_rule, regex_rule


def field(**validation: object) -> FieldDef:
    return FieldDef(
        path="g.f",
        label="F",
        group="g",
        value_type="decimal",
        validation=FieldValidation(**validation),  # type: ignore[arg-type]
    )


def test_range_passes_inside_and_at_the_bounds() -> None:
    f = field(min=10, max=35)
    assert range_rule(f, 10) == ("range", True, "within range")
    assert range_rule(f, 35) == ("range", True, "within range")
    assert range_rule(f, 25.5) == ("range", True, "within range")


def test_range_fails_below_and_above_with_a_plain_message() -> None:
    f = field(min=10, max=35)
    assert range_rule(f, 9) == ("range", False, "9 is below the minimum 10")
    assert range_rule(f, 36) == ("range", False, "36 is above the maximum 35")


def test_range_with_one_bound() -> None:
    assert range_rule(field(min=1), 5) == ("range", True, "within range")
    assert range_rule(field(max=15), 16) == ("range", False, "16 is above the maximum 15")


def test_range_does_not_apply_without_bounds_or_to_non_numbers() -> None:
    assert range_rule(field(), 5) is None
    assert range_rule(field(min=1), "5") is None
    assert range_rule(field(min=1), True) is None


def test_regex_must_match_the_whole_value() -> None:
    f = field(regex=r"ACME/\d{4}/\d{3}")
    assert regex_rule(f, "ACME/2026/001") == ("regex", True, "matches the expected pattern")
    name, passed, message = regex_rule(f, "ACME/2026/001-A")  # type: ignore[misc]
    assert (name, passed) == ("regex", False) and "does not match" in message


def test_regex_does_not_apply_without_a_pattern_or_to_non_text() -> None:
    assert regex_rule(field(), "x") is None
    assert regex_rule(field(regex="x"), 5) is None
