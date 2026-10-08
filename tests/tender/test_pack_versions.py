"""A schema version that reads an earlier one is checked against it field by field."""

from pathlib import Path

import pytest
import yaml

from core.schemas import KeyDef
from scripts.release_schema import released_text
from tender.services.packs import (
    PACKS_ROOT,
    Catalog,
    PackError,
    TenderField,
    field_signature,
    read_released,
    released_file,
    type_signature,
    verify_versions,
)


def field(path: str, value_type: str = "text", **overrides: object) -> TenderField:
    values: dict[str, object] = {
        "path": path,
        "namespace": "core",
        "domain": None,
        "subdomain": None,
        "section": "s",
        "label": path,
        "value_type": value_type,
        "unit": None,
        "required": False,
        "help_text": "",
        "enum_values": None,
        "item_keys": None,
        "keys": None,
        "review_order": 1,
    }
    values.update(overrides)
    return TenderField(**values)  # type: ignore[arg-type]


V1 = [
    field("core.a.number", "text"),
    field("core.a.amount", "money_inr", unit="INR"),
    field("core.a.mode", "enum", enum_values=["x", "y"]),
    field("core.a.items", "record_list", item_keys=["name", "kv"]),
]


def release(
    pack_dir: Path, version: str, fields: list[TenderField], tender_type: str = "t"
) -> None:
    path = released_file(pack_dir, version)
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump({"types": {tender_type: type_signature(fields)}}))


def verify(
    pack_dir: Path,
    fields: list[TenderField],
    read_again: dict[str, list[str]] | None = None,
    reads: tuple[str, ...] = ("v1",),
    version: str = "v2",
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return verify_versions(pack_dir, "t", version, reads, read_again or {}, fields)


def test_a_version_that_only_adds_fields_reads_the_earlier_one(tmp_path: Path) -> None:
    release(tmp_path, "v1", V1)
    assert verify(tmp_path, [*V1, field("core.a.new", "decimal")]) == ()


def test_labels_help_bounds_section_and_required_may_change(tmp_path: Path) -> None:
    release(tmp_path, "v1", V1)
    relabelled = [
        f.model_copy(
            update={"label": "New", "help_text": "h", "section": "other", "required": True}
        )
        for f in V1
    ]
    assert verify(tmp_path, relabelled) == ()


def test_a_removed_field_fails_the_load_because_its_candidates_would_be_orphaned(
    tmp_path: Path,
) -> None:
    release(tmp_path, "v1", V1)
    with pytest.raises(PackError, match=r"cannot read v1.*orphaned: \['core.a.amount'\]"):
        verify(tmp_path, [f for f in V1 if f.path != "core.a.amount"])


@pytest.mark.parametrize(
    ("path", "change"),
    [
        ("core.a.number", {"value_type": "int"}),
        ("core.a.amount", {"unit": "INR per MW"}),
        ("core.a.mode", {"enum_values": ["x", "z"]}),
        ("core.a.items", {"item_keys": ["name"]}),
        (
            "core.a.items",
            {"keys": [KeyDef(name="name"), KeyDef(name="kv", value_type="decimal", unit="kV")]},
        ),
    ],
)
def test_a_field_defined_differently_fails_the_load_unless_declared(
    tmp_path: Path, path: str, change: dict[str, object]
) -> None:
    release(tmp_path, "v1", V1)
    changed = [f.model_copy(update=change) if f.path == path else f for f in V1]
    with pytest.raises(PackError, match=rf"defined differently than in v1.*\['{path}'\]"):
        verify(tmp_path, changed)
    assert verify(tmp_path, changed, {"v1": [path]}) == (("v1", (path,)),)


def test_every_field_at_fault_is_named_at_once(tmp_path: Path) -> None:
    release(tmp_path, "v1", V1)
    broken = [f.model_copy(update={"value_type": "int"}) for f in V1 if f.path != "core.a.mode"]
    with pytest.raises(PackError) as caught:
        verify(tmp_path, broken)
    message = str(caught.value)
    assert "orphaned: ['core.a.mode']" in message
    assert "['core.a.amount', 'core.a.items', 'core.a.number']" in message


def test_a_declaration_for_an_unchanged_field_or_an_unread_version_is_refused(
    tmp_path: Path,
) -> None:
    release(tmp_path, "v1", V1)
    with pytest.raises(PackError, match=r"read_again but unchanged since v1: \['core.a.mode'\]"):
        verify(tmp_path, V1, {"v1": ["core.a.mode"]})
    with pytest.raises(PackError, match=r"read_again names version\(s\) \['v0'\]"):
        verify(tmp_path, V1, {"v0": ["core.a.mode"]})
    # A path of another tender type is not this type's business.
    assert verify(tmp_path, V1, {"v1": ["sector.x.other.field"]}) == ()


def test_reading_a_version_that_was_never_released_fails_the_load(tmp_path: Path) -> None:
    with pytest.raises(PackError, match=r"reads v1, but released/v1.yaml does not exist"):
        verify(tmp_path, V1)
    assert verify(tmp_path, V1, reads=()) == ()


def test_a_tender_type_that_the_earlier_version_did_not_have_has_nothing_to_orphan(
    tmp_path: Path,
) -> None:
    release(tmp_path, "v1", V1, tender_type="another")
    assert verify(tmp_path, [field("core.b.only")]) == ()


def test_a_released_version_is_frozen(tmp_path: Path) -> None:
    release(tmp_path, "v2", V1)
    assert verify(tmp_path, V1, reads=()) == ()
    with pytest.raises(PackError, match=r"version v2 is released and frozen.*\['core.a.new'\]"):
        verify(tmp_path, [*V1, field("core.a.new")], reads=())
    with pytest.raises(PackError, match=r"released and frozen.*\['core.a.number'\]"):
        verify(tmp_path, [f for f in V1 if f.path != "core.a.number"], reads=())


def test_signature_holds_type_unit_values_and_record_keys_only() -> None:
    record = field(
        "core.a.rec",
        "record",
        keys=[
            KeyDef(name="rate", label="Rate", value_type="money_inr", unit="INR", min=0, max=9),
            KeyDef(
                name="parts",
                value_type="list",
                keys=[KeyDef(name="part", value_type="enum", enum_values=["a"])],
            ),
        ],
    )
    assert field_signature(record) == {
        "type": "record",
        "keys": {
            "rate": {"type": "money_inr", "unit": "INR"},
            "parts": {"type": "list", "keys": {"part": {"type": "enum", "enum": ["a"]}}},
        },
    }
    assert field_signature(field("core.a.x", "text", label="L", help_text="h")) == {"type": "text"}


# --- the real packs


def test_the_power_pack_reads_v1_with_one_declared_change(catalog: Catalog) -> None:
    for name, compiled in catalog.types.items():
        assert compiled.reads_versions == ("v1", "v2"), name
        expected = (
            (("v1", ("sector.power.transmission.elements",)),) if name == "transmission" else ()
        )
        assert compiled.not_read_from == expected, name


def test_the_power_pack_would_not_load_without_its_declaration(catalog: Catalog) -> None:
    transmission = catalog.types["transmission"]
    with pytest.raises(PackError, match=r"not listed under read_again.*transmission.elements"):
        verify_versions(
            PACKS_ROOT / "power", "transmission", "v3", ("v1",), {}, transmission.fields
        )


def test_every_v1_field_of_every_type_is_still_present_in_the_current_version(
    catalog: Catalog,
) -> None:
    released = read_released(PACKS_ROOT / "power", "v1")
    # Types added since v1 (re_rtc, 2026-10-08) have nothing in v1 to keep.
    assert released is not None and set(released) == set(catalog.types) - {"re_rtc"}
    for name in released:
        compiled = catalog.types[name]
        current = type_signature(compiled.fields)
        assert set(released[name]) <= set(current), name
        changed = [path for path, sig in released[name].items() if current[path] != sig]
        assert changed == (["sector.power.transmission.elements"] if name == "transmission" else [])


def test_the_release_file_round_trips(catalog: Catalog) -> None:
    version = next(iter(catalog.types.values())).schema.version
    data = yaml.safe_load(released_text(catalog, "power", version))
    assert (data["pack"], data["version"]) == ("power", version)
    for name, compiled in catalog.types.items():
        assert data["types"][name] == type_signature(compiled.fields)
