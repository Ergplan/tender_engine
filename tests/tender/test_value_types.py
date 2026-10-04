import pytest

from core.schemas import FieldDef, SchemaRegistry
from tender.services.packs import Catalog


@pytest.fixture()
def registry(catalog: Catalog) -> SchemaRegistry:
    registry = SchemaRegistry()
    catalog.register(registry)
    return registry


def field(value_type: str, **extra: object) -> FieldDef:
    return FieldDef(path="core.x.y", label="Y", group="x", value_type=value_type, **extra)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value_type", "raw", "expected"),
    [
        ("money_inr", "9,28,000", 928000),
        ("money_inr", 2420000.0, 2420000),
        ("percent", "17.5", 17.5),
        ("percent", 100, 100),
        ("duration_months", 24, 24),
        ("duration_months", "18", 18),
        ("mw", 1200, 1200),
        ("mwh", "4800", 4800),
        ("kv", 765, 765),
        ("km", 120.5, 120.5),
    ],
)
def test_numeric_tender_types_coerce(
    registry: SchemaRegistry, value_type: str, raw: object, expected: object
) -> None:
    assert registry.value_types.coerce(raw, field(value_type)) == expected


@pytest.mark.parametrize(
    ("value_type", "raw"),
    [
        ("money_inr", -1),
        ("money_inr", "nine lakh"),
        ("percent", 101),
        ("percent", -0.5),
        ("duration_months", 18.5),
        ("duration_months", -3),
        ("mw", -10),
        ("mw", True),
    ],
)
def test_numeric_tender_types_refuse_bad_values(
    registry: SchemaRegistry, value_type: str, raw: object
) -> None:
    with pytest.raises(ValueError):
        registry.value_types.coerce(raw, field(value_type))


def test_record_list_parses_the_line_form_and_accepts_records(registry: SchemaRegistry) -> None:
    elements = field("record_list", item_keys=["name", "kind", "kv", "route_km"])
    parsed = registry.value_types.coerce(
        [
            "name: Beed - Parli 400 kV D/c line | kind: line | kv: 400 | route_km: 62",
            "Name: 400/220 kV Beed substation | Kind: substation | kv: 400",
        ],
        elements,
    )
    assert parsed == [
        {"name": "Beed - Parli 400 kV D/c line", "kind": "line", "kv": "400", "route_km": "62"},
        {"name": "400/220 kV Beed substation", "kind": "substation", "kv": "400"},
    ]
    assert registry.value_types.coerce(parsed, elements) == parsed


@pytest.mark.parametrize(
    "raw",
    [
        [],
        "name: x",
        ["no separator here"],
        ["name: x | colour: red"],
        ["kind: line | kv: 400"],
        [42],
    ],
)
def test_record_list_refuses_malformed_items(registry: SchemaRegistry, raw: object) -> None:
    with pytest.raises(ValueError):
        registry.value_types.coerce(
            raw, field("record_list", item_keys=["name", "kind", "kv", "route_km"])
        )
