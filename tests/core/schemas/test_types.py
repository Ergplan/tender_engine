import pytest

from core.schemas import FieldDef, ValueType, ValueTypeRegistry

TYPES = ValueTypeRegistry()


def field(value_type: str, **kwargs: object) -> FieldDef:
    return FieldDef(path="g.f", label="F", group="g", value_type=value_type, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-12", "2026-03-12"),
        ("12/03/2026", "2026-03-12"),
        ("12.03.2026", "2026-03-12"),
        ("12-03-2026", "2026-03-12"),
        ("12-Mar-2026", "2026-03-12"),
        ("12th March 2026", "2026-03-12"),
        ("12 March, 2026", "2026-03-12"),
        ("1st Sept 2026", "2026-09-01"),
        ("March 12, 2026", "2026-03-12"),
        ("  30 March 2026 ", "2026-03-30"),
    ],
)
def test_date_accepts_iso_and_indian_day_first_forms(raw: str, expected: str) -> None:
    assert TYPES.coerce(raw, field("date")) == expected


@pytest.mark.parametrize(
    "raw", ["31/02/2026", "13/13/2026", "soon", "12 Foo 2026", 20260312, None, ""]
)
def test_date_rejects_invalid_values(raw: object) -> None:
    with pytest.raises(ValueError):
        TYPES.coerce(raw, field("date"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (928000, 928000),
        (9.28, 9.28),
        ("9,28,000", 928000),
        ("12.5", 12.5),
        (600.0, 600),
        ("-3", -3),
    ],
)
def test_decimal_accepts_numbers_and_numeric_strings(raw: object, expected: float) -> None:
    result = TYPES.coerce(raw, field("decimal"))
    assert result == expected and type(result) is type(expected)


@pytest.mark.parametrize("raw", ["9.28 lakh", "abc", True, None, [1]])
def test_decimal_rejects_non_numbers(raw: object) -> None:
    with pytest.raises(ValueError):
        TYPES.coerce(raw, field("decimal"))


def test_int_accepts_whole_numbers_only() -> None:
    assert TYPES.coerce(25, field("int")) == 25
    assert TYPES.coerce("25", field("int")) == 25
    assert TYPES.coerce(25.0, field("int")) == 25
    with pytest.raises(ValueError, match="whole number"):
        TYPES.coerce(25.5, field("int"))


def test_text_is_stripped_and_must_not_be_empty() -> None:
    assert TYPES.coerce("  SECI  ", field("text")) == "SECI"
    assert TYPES.coerce("a\nb", field("long_text")) == "a\nb"
    for bad in ("", "   ", 5, None):
        with pytest.raises(ValueError):
            TYPES.coerce(bad, field("text"))


def test_bool_accepts_booleans_and_yes_no() -> None:
    assert TYPES.coerce(True, field("bool")) is True
    assert TYPES.coerce("Yes", field("bool")) is True
    assert TYPES.coerce("no", field("bool")) is False
    with pytest.raises(ValueError):
        TYPES.coerce("maybe", field("bool"))
    with pytest.raises(ValueError):
        TYPES.coerce(1, field("bool"))


def test_enum_normalises_and_checks_membership() -> None:
    f = field("enum", enum_values=["effective_date", "ppa_signing"])
    assert TYPES.coerce("Effective Date", f) == "effective_date"
    assert TYPES.coerce("ppa-signing", f) == "ppa_signing"
    with pytest.raises(ValueError, match="expected one of"):
        TYPES.coerce("loa", f)
    with pytest.raises(ValueError):
        TYPES.coerce(3, f)


def test_list_text_drops_blanks_and_requires_an_item() -> None:
    assert TYPES.coerce([" a ", "", "b"], field("list_text")) == ["a", "b"]
    for bad in ([], ["  "], "a", [1, 2]):
        with pytest.raises(ValueError):
            TYPES.coerce(bad, field("list_text"))


def test_unknown_type_is_refused_and_a_domain_type_can_be_added() -> None:
    registry = ValueTypeRegistry()
    with pytest.raises(ValueError, match="unknown value type"):
        registry.coerce(1, field("mw"))
    registry.register(ValueType("mw", "number", lambda raw, f: float(raw)))
    assert registry.coerce("600", field("mw")) == 600.0
    with pytest.raises(ValueError, match="already registered"):
        registry.register(ValueType("mw", "number", lambda raw, f: raw))
