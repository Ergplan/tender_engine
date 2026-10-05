import pytest

from core.schemas import FieldDef, KeyDef, SchemaRegistry
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


def record_field(value_type: str = "record") -> FieldDef:
    block = KeyDef(
        name="blocks",
        value_type="list",
        keys=[KeyDef(name="start", value_type="time"), KeyDef(name="hours", value_type="decimal")],
    )
    keys = [
        KeyDef(name="basis", value_type="enum", enum_values=["per_mw", "lump_sum"]),
        KeyDef(name="rate_inr", value_type="money_inr"),
        KeyDef(name="share_pct", value_type="percent", max=50),
        KeyDef(name="revolving", value_type="bool"),
        KeyDef(name="payer", value_type="text"),
        block,
    ]
    return FieldDef(path="t.r", label="R", group="g", value_type=value_type, keys=keys)


def test_a_record_is_read_from_lines_with_every_key_typed_or_none(registry: SchemaRegistry) -> None:
    parsed = registry.value_types.coerce(
        [
            "Basis: per MW",
            "rate_inr: 9,28,000",
            "revolving: yes",
            "payer: null",
            "blocks: start=05:00; hours=2",
            "blocks: start=1800 hrs; hours=2.5",
        ],
        record_field(),
    )
    assert parsed == {
        "basis": "per_mw",
        "rate_inr": 928000,
        "share_pct": None,
        "revolving": True,
        "payer": None,
        "blocks": [{"start": "05:00", "hours": 2}, {"start": "18:00", "hours": 2.5}],
    }
    # What is stored is read back unchanged (a reviewer's edit sends the record itself).
    assert registry.value_types.coerce(parsed, record_field()) == parsed


@pytest.mark.parametrize(
    "raw",
    [
        ["basis: per_mw", "colour: red"],
        ["basis: per_mw", "basis: lump_sum"],
        ["rate_inr: about nine lakh"],
        ["share_pct: 60"],
        ["blocks: start=25:99"],
        ["blocks: start=05:00; width=3"],
        ["no separator"],
        ["payer: null", "rate_inr: not stated"],
        "basis: per_mw",
        [],
    ],
)
def test_a_malformed_or_empty_record_is_refused(registry: SchemaRegistry, raw: object) -> None:
    with pytest.raises(ValueError):
        registry.value_types.coerce(raw, record_field())


def test_a_typed_record_list_gives_every_item_every_key(registry: SchemaRegistry) -> None:
    field_def = record_field("record_list")
    parsed = registry.value_types.coerce(
        ["basis: lump_sum | rate_inr: 500 | revolving: no", {"basis": "per_mw", "share_pct": 5}],
        field_def,
    )
    assert [item["basis"] for item in parsed] == ["lump_sum", "per_mw"]
    assert parsed[0]["rate_inr"] == 500 and parsed[0]["revolving"] is False
    assert parsed[1]["share_pct"] == 5 and parsed[1]["rate_inr"] is None
    with pytest.raises(ValueError, match="every item needs `basis`"):
        registry.value_types.coerce(["rate_inr: 5"], field_def)
