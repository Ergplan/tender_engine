"""Schema loading: every domain-pack YAML compiles, and malformed packs are refused."""

from pathlib import Path

import pytest

from core.llm.registry import load_prompt
from core.schemas import SchemaRegistry
from tender.models import DOCUMENT_ROLES, TENDER_TYPES
from tender.services.packs import PACKS_ROOT, Catalog, PackError, build_registry, compile_type

COMMON_SECTIONS = [
    "summary",
    "identity_and_scope",
    "key_dates",
    "eligibility",
    "guarantees",
    "commercial",
    "penalties",
    "connectivity_and_compliance",
    "documents",
]


def test_every_tender_type_has_a_yaml_that_loads(catalog: Catalog) -> None:
    assert sorted(catalog.types) == sorted(TENDER_TYPES)
    assert len(list((PACKS_ROOT / "power").glob("*.yaml"))) == len(TENDER_TYPES) + 1


def test_every_field_has_a_section_a_value_type_a_label_and_help(catalog: Catalog) -> None:
    registry = SchemaRegistry()
    catalog.register(registry)
    for compiled in catalog.types.values():
        section_names = [section.name for section in compiled.sections]
        assert section_names[:9] == COMMON_SECTIONS and len(section_names) == 10
        assert [field.review_order for field in compiled.fields] == list(
            range(1, len(compiled.fields) + 1)
        )
        for field in compiled.fields:
            assert field.section in section_names, field.path
            registry.value_types.get(field.value_type)
            assert field.label and field.help_text, field.path
            if field.value_type == "enum":
                assert field.enum_values, field.path
            if field.value_type == "record_list":
                assert field.item_keys, field.path
        for section in compiled.sections:
            assert set(section.roles) <= set(DOCUMENT_ROLES) and section.roles
            assert compiled.schema.fields_in(section.name), section.name


def test_field_paths_carry_their_origin(catalog: Catalog) -> None:
    for tender_type, compiled in catalog.types.items():
        for field in compiled.fields:
            parts = field.path.split(".")
            if field.namespace == "core":
                assert parts[0] == "core" and len(parts) == 3
                assert (field.domain, field.subdomain) == (None, None)
            else:
                assert parts[:2] == ["sector", "power"] and len(parts) == 4
                assert field.domain == "power" and field.subdomain in ("common", tender_type)
    fdre = {field.path for field in catalog.get("fdre").fields}
    assert {
        "core.identity.tender_number",
        "core.key_dates.bid_submission_deadline",
        "core.guarantees.emd_per_mw_inr",
        "sector.power.common.min_commissioned_mw",
        "sector.power.fdre.demand_profile",
    } <= fdre
    assert "sector.power.bess.capacity_mwh" not in fdre


def test_schemas_register_with_core_as_tender_type_v1_once(catalog: Catalog) -> None:
    registry, built = build_registry()
    assert registry.names() == sorted((f"tender.{name}", "v1") for name in TENDER_TYPES)
    built.register(registry)  # a second registration is a no-op, not an error
    schema = registry.get("tender.fdre", "v1")
    assert schema.cross_field_rules == ["date_order", "emd_pbg_within_10x", "bid_capacity_order"]
    assert registry.get("tender.transmission", "v1").cross_field_rules[-1] == "elements_have_kv"
    assert schema.run_rules == ["later_version_evidence"]
    assert schema.field("core.guarantees.emd_per_mw_inr").validation.min == 1000


def test_type_rules_are_required_fields(catalog: Catalog) -> None:
    """fdre requires demand_profile and availability penalty; bess requires mwh and
    cycles_per_day; transmission requires elements; hybrid requires the share per resource."""
    expected = {
        "fdre": {"demand_profile", "availability_shortfall_penalty"},
        "bess": {"capacity_mwh", "cycles_per_day"},
        "transmission": {"elements"},
        "hybrid": {"min_share_per_resource_percent"},
    }
    for tender_type, names in expected.items():
        required = {
            field.path.rsplit(".", 1)[1]
            for field in catalog.get(tender_type).fields
            if field.required and field.subdomain == tender_type
        }
        assert required == names, tender_type


def test_every_section_has_a_registered_prompt_that_extends_the_core_extract_prompt(
    catalog: Catalog,
) -> None:
    core_text = load_prompt("extract", "v1").text
    names = {s.prompt for compiled in catalog.types.values() for s in compiled.sections}
    assert len(names) == 18
    for name in names:
        prompt = load_prompt(name, "v1", catalog.prompt_roots)
        assert prompt.text.startswith(core_text) and "Domain guidance" in prompt.text
        assert "lakh" in prompt.text and "amendment, corrigendum or clarification" in prompt.text


def test_the_formula_and_deferral_fields_exist_beside_the_computed_ones(catalog: Catalog) -> None:
    fields = {field.path: field for field in catalog.get("fdre").fields}
    for path in ("core.guarantees.emd_formula", "core.guarantees.pbg_formula"):
        assert fields[path].value_type == "long_text" and not fields[path].required
    assert fields["core.key_dates.dates_deferred_note"].value_type == "long_text"


CORE = """
pack: core
version: v1
sections:
  identity: {label: Identity, prompt: extract, roles: [rfs]}
fields:
  core.identity.number: {section: identity, label: Number, type: text}
"""
PACK = """
pack: demo
version: v1
sector: demo
subdomains: [common, a, b, ab]
"""


def write_pack(tmp_path: Path, **types: str) -> Path:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "common.yaml").write_text(CORE)
    pack = tmp_path / "demo"
    pack.mkdir()
    (pack / "pack.yaml").write_text(PACK)
    for name, text in types.items():
        (pack / f"{name}.yaml").write_text(text)
    return pack


def type_yaml(name: str, field: str, label: str = "X", inherits: str = "") -> str:
    return f"""
type: {name}
pack: demo
includes: [identity]
{inherits}
sections:
  s_{name}: {{label: S, prompt: extract, roles: [rfs]}}
fields:
  {field}: {{section: s_{name}, label: {label}, type: text}}
"""


def test_a_combined_type_inherits_both_parents_and_is_frozen_at_compile_time(
    tmp_path: Path,
) -> None:
    pack = write_pack(
        tmp_path,
        a=type_yaml("a", "sector.demo.a.x"),
        b=type_yaml("b", "sector.demo.b.y"),
        ab="type: ab\npack: demo\ninherits: [a, b]\n",
    )
    compiled = compile_type(pack, "ab", tmp_path / "core")
    assert [field.path for field in compiled.fields] == [
        "core.identity.number",
        "sector.demo.a.x",
        "sector.demo.b.y",
    ]
    assert [section.name for section in compiled.sections] == ["identity", "s_a", "s_b"]
    assert compiled.schema.name == "tender.ab"


def test_a_conflict_between_inherited_types_is_an_error(tmp_path: Path) -> None:
    clash = type_yaml("b", "sector.demo.a.x", label="Different").replace("s_b", "s_a")
    pack = write_pack(
        tmp_path,
        a=type_yaml("a", "sector.demo.a.x"),
        b=clash,
        ab="type: ab\npack: demo\ninherits: [a, b]\n",
    )
    with pytest.raises(PackError, match="conflicting definitions of field 'sector.demo.a.x'"):
        compile_type(pack, "ab", tmp_path / "core")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (type_yaml("a", "identity.x"), "neither core"),
        (type_yaml("a", "core.identity.x"), "must be sector.demo"),
        (type_yaml("a", "sector.other.a.x"), "must be sector.demo"),
        (type_yaml("a", "sector.demo.zzz.x"), "must be sector.demo"),
        (type_yaml("a", "sector.demo.a.x").replace("[identity]", "[nope]"), "unknown section"),
        (type_yaml("a", "sector.demo.a.x").replace("section: s_a", "section: gone"), "unknown"),
        (type_yaml("a", "sector.demo.a.x").replace("[rfs]", "[novel]"), "unknown role"),
        (type_yaml("a", "sector.demo.a.x") + "surprise: 1\n", "Extra inputs"),
        (
            type_yaml("a", "sector.demo.a.x") + "required: [sector.demo.a.nope]\n",
            "requires unknown",
        ),
        (type_yaml("a", "sector.demo.a.x", inherits="inherits: [a]"), "inherits itself"),
    ],
)
def test_malformed_type_files_are_refused(tmp_path: Path, text: str, message: str) -> None:
    pack = write_pack(tmp_path, a=text)
    with pytest.raises(PackError, match=message):
        compile_type(pack, "a", tmp_path / "core")


def test_epc_leaves_out_the_ppa_tenure_and_the_ceiling_tariff(catalog: Catalog) -> None:
    """An EPC works contract has no PPA and no tariff; its O&M period is in epc_scope."""
    epc = {field.path for field in catalog.get("epc").fields}
    dropped = {
        "sector.power.common.ppa_tenure_years",
        "sector.power.common.tariff_ceiling_inr_per_kwh",
    }
    assert not dropped & epc
    assert {
        "sector.power.epc.om_period_months",
        "sector.power.epc.milestone_payment_schedule",
        "core.commercial.payment_security_mechanism",
    } <= epc
    for tender_type in ("solar", "fdre", "bess", "transmission"):
        assert dropped <= {field.path for field in catalog.get(tender_type).fields}


def test_a_period_or_amount_that_can_be_stated_two_ways_carries_its_basis(
    catalog: Catalog,
) -> None:
    fields = {field.path: field for field in catalog.get("solar").fields}
    pairs = {
        "core.key_dates.bid_validity": ("core.key_dates.bid_validity_unit", ["days", "months"]),
        "sector.power.common.financial_closure_months": (
            "sector.power.common.financial_closure_reference",
            ["effective_date", "ppa_signing", "loa", "before_scod"],
        ),
        "core.eligibility.turnover_requirement_inr": (
            "core.eligibility.turnover_basis",
            ["absolute", "per_mw"],
        ),
        "core.eligibility.liquidity_requirement_inr": (
            "core.eligibility.liquidity_basis",
            ["absolute", "per_mw"],
        ),
    }
    for value_path, (basis_path, values) in pairs.items():
        assert fields[value_path].section == fields[basis_path].section
        assert fields[basis_path].value_type == "enum"
        assert fields[basis_path].enum_values == values
        assert fields[basis_path].review_order == fields[value_path].review_order + 1
    assert "core.key_dates.bid_validity_days" not in fields


def test_a_type_can_only_exclude_a_common_field_it_would_otherwise_have(tmp_path: Path) -> None:
    good = type_yaml("a", "sector.demo.a.x") + "excludes: [core.identity.number]\n"
    pack = write_pack(tmp_path, a=good)
    extra = "  core.identity.title: {section: identity, label: Title, type: text}\n"
    (tmp_path / "core" / "common.yaml").write_text(CORE + extra)
    compiled = compile_type(pack, "a", tmp_path / "core")
    assert [field.path for field in compiled.fields] == ["core.identity.title", "sector.demo.a.x"]
    (pack / "a.yaml").write_text(type_yaml("a", "sector.demo.a.x") + "excludes: [core.x.y]\n")
    with pytest.raises(PackError, match="excludes field"):
        compile_type(pack, "a", tmp_path / "core")
