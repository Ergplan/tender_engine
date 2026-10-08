"""The derivation rules on three records: the WBSEDCL RE-RTC tender (thermal allowed up
to 49% by a general clause, RECs required, BESS allowed if RE-charged and co-located), an
FDRE tender (storage mandatory, thermal prohibited) and an EPC works contract (nothing
addressed). Deterministic: the same decided fields give the same rows, and a row with no
decided clause behind it says not_addressed."""

from typing import Any

from core.services.review_state import EvidenceView
from tender.domain_packs.power.derivations import (
    Decided,
    Inputs,
    clause_of,
    optimizer_constraints,
    rule_for,
    rules,
    source_eligibility,
)

MIX = "sector.power.common.source_mix_rules"
CHARGING = "sector.power.common.bess_charging_rule"
GREEN = "sector.power.re_rtc.traceable_green_min_pct"
LINKED = "sector.power.re_rtc.linked_capacity_obligation"
STORAGE_MANDATORY = "sector.power.fdre.storage_mandatory"


def span(page: int, quote: str) -> EvidenceView:
    return EvidenceView(
        id=f"s{page}-{abs(hash(quote)) % 1000}",
        document_id="doc",
        page_no=page,
        bbox=None,
        char_start=10,
        char_end=10 + len(quote),
        quote=quote,
        resolution="located",
        match_score=100.0,
        match_method="exact",
    )


def decided(path: str, value: Any, *spans: EvidenceView, label: str = "") -> Decided:
    return Decided(
        path=path,
        label=label or path.rsplit(".", 1)[1],
        value=value,
        spans=list(spans),
        version_no=1,
    )


GENERAL = (
    "balance power supply can be met through alternate sources, from different and/or "
    "multiple RE/non-RE generation sources"
)
STORAGE = (
    "Energy Storage System (Charged through Renewable Energy only) ... the BESS must be "
    "co-located as per CERC Sharing Regulations"
)
GREEN_CLAUSE = "a minimum 51% shall be Traceable Green Power for each Accounting Year"
LINKED_CLAUSE = (
    "installation of Solar Power Capacity equivalent to twice the contracted Supply Capacity"
)


def wbsedcl() -> Inputs:
    return {
        MIX: decided(
            MIX,
            [
                {"source": "any_non_re", "treatment": "allowed"},
                {"source": "bess", "treatment": "allowed", "condition": "charged from RE only"},
                {"source": "solar", "treatment": "allowed"},
                {"source": "wind", "treatment": "allowed"},
                {"source": "hydro", "treatment": "allowed"},
                {"source": "biomass", "treatment": "allowed"},
                {"source": "pumped_storage", "treatment": "allowed"},
            ],
            span(10, GENERAL),
            span(11, STORAGE),
            span(
                9,
                "Traceable Green Power means ... (Solar, Wind, Hydro, Biomass,) ... storage "
                "(PSP, BESS",
            ),
        ),
        CHARGING: decided(
            CHARGING,
            {
                "re_only": True,
                "co_located_required": True,
                "regulation_reference": "CERC Sharing Regulations",
            },
            span(11, STORAGE),
        ),
        GREEN: decided(GREEN, 51, span(10, GREEN_CLAUSE)),
        LINKED: decided(
            LINKED,
            {
                "technology": "solar",
                "multiple_of_contracted": 2,
                "capacity_mw": 3000,
                "acres_per_mw": 4,
                "location": "anywhere in India",
                "stages": [
                    {"share_pct": 50, "months_from_loa": 3, "documents": "both"},
                    {"share_pct": 50, "months_from_loa": 6, "documents": "both"},
                ],
            },
            span(11, LINKED_CLAUSE),
            span(48, "at least 4 Acres/MW ... within 3 months of LOA issuance ... within 6 months"),
        ),
        "sector.power.re_rtc.rec_obligation": decided(
            "sector.power.re_rtc.rec_obligation",
            {"applies_to": "all_non_re_energy", "cost_borne_by": "supplier"},
            span(
                47,
                "provide Renewable Energy Certificates (“REC”) equivalent to such non RE- "
                "power supplied",
            ),
        ),
        "sector.power.re_rtc.cuf_annual_min_pct": decided(
            "sector.power.re_rtc.cuf_annual_min_pct",
            80,
            span(10, "minimum 80% CUF for each Accounting Year"),
        ),
        "sector.power.re_rtc.cuf_monthly_min_pct": decided(
            "sector.power.re_rtc.cuf_monthly_min_pct",
            70,
            span(10, "minimum 70% CUF on monthly basis"),
        ),
        "sector.power.re_rtc.cuf_peak_min_pct": decided(
            "sector.power.re_rtc.cuf_peak_min_pct",
            90,
            span(10, "minimum 90% CUF during Peak hours"),
        ),
        "sector.power.re_rtc.peak_window": decided(
            "sector.power.re_rtc.peak_window",
            {"hours_per_day": 4, "stretches": "procurer_discretion", "set_by": "procurer"},
            span(
                10,
                "Discharging 4 Hours Daily - single stretch of 4 hours or 4 hours in total in "
                "multiple stretches, as decided by WBSEDCL",
            ),
        ),
        "sector.power.re_rtc.supply_start_date": decided(
            "sector.power.re_rtc.supply_start_date", "2028-07-01", span(10, "1500 MW: 01.07.2028")
        ),
        "sector.power.re_rtc.greenshoe_ssd": decided(
            "sector.power.re_rtc.greenshoe_ssd",
            "2029-04-01",
            span(10, "Supply Start Date of 01.04.2029"),
        ),
        "sector.power.re_rtc.non_re_tariff_split": decided(
            "sector.power.re_rtc.non_re_tariff_split",
            {
                "fixed_pct": 70,
                "variable_pct": 30,
                "merit_order_treatment": "merit_order_on_variable_charge",
            },
            span(
                15,
                "70% of Applicable Tariff shall be deemed to be the Fixed Charge component and "
                "balance 30% ... Variable Charge",
            ),
            span(12, "sources other than RE sources would follow Merit Order Despatch"),
        ),
        "sector.power.common.ppa_tenure_years": decided(
            "sector.power.common.ppa_tenure_years", 25, span(1, "for a period of 25 years")
        ),
    }


def fdre_ix() -> Inputs:
    return {
        MIX: decided(
            MIX,
            [
                {"source": "bess", "treatment": "required"},
                {
                    "source": "thermal",
                    "treatment": "prohibited",
                    "condition": "no fossil fuel based generation",
                },
                {"source": "solar", "treatment": "allowed"},
                {"source": "wind", "treatment": "allowed"},
            ],
            span(
                20,
                "the Project shall include an Energy Storage System; thermal or fossil fuel "
                "based generation is not permitted",
            ),
        ),
        STORAGE_MANDATORY: decided(
            STORAGE_MANDATORY, True, span(20, "shall include an Energy Storage System")
        ),
    }


def rows_by_source(derivation: Any) -> dict[str, dict[str, Any]]:
    return {row.value["source"]: row.value for row in derivation.rows}


def test_the_rules_are_registered_for_the_two_derived_fields() -> None:
    assert [rule.field_path for rule in rules()] == [
        source_eligibility.FIELD,
        optimizer_constraints.FIELD,
    ]
    assert rule_for(source_eligibility.FIELD).version == "v1"
    assert rule_for(optimizer_constraints.FIELD).module.endswith(".optimizer_constraints")


def test_wbsedcl_thermal_and_market_are_limited_by_the_general_clause_and_say_so() -> None:
    table = rows_by_source(source_eligibility.derive(wbsedcl()))
    assert [r for r in table] == list(source_eligibility.SOURCES)
    for source in ("thermal", "market_purchase"):
        row = table[source]
        assert (row["status"], row["basis"]) == ("allowed_with_limit", "inherited")
        assert (row["limit_value"], row["limit_unit"]) == (49, "percent_of_annual_energy")
        assert row["condition"].startswith("not named; covered by the general clause")
        assert row["derived_from"] == f"{MIX}, {GREEN}"
        assert row["clause"].startswith("p.10:") and "alternate sources" in row["clause"]
    bess = table["bess"]
    assert (bess["status"], bess["basis"]) == ("allowed", "stated")
    assert "charged from RE only" in bess["condition"] and "co-located" in bess["condition"]
    assert "CERC Sharing Regulations" in bess["condition"]
    assert bess["clause"].startswith("p.11:")
    solar = table["solar"]
    assert (solar["status"], solar["basis"]) == ("required", "stated")
    assert "2x the contracted capacity" in solar["condition"]
    assert LINKED in solar["derived_from"] and MIX in solar["derived_from"]
    for source in ("wind", "hydro", "biomass", "pumped_storage"):
        assert (table[source]["status"], table[source]["basis"]) == ("allowed", "stated")
    assert (table["other"]["status"], table["other"]["basis"]) == ("not_addressed", "none")
    assert "clause" not in table["other"]


def test_fdre_ix_storage_is_required_and_thermal_prohibited_by_clauses_naming_them() -> None:
    derivation = source_eligibility.derive(fdre_ix())
    table = rows_by_source(derivation)
    assert (table["bess"]["status"], table["bess"]["basis"]) == ("required", "stated")
    assert STORAGE_MANDATORY in table["bess"]["derived_from"]
    assert (table["thermal"]["status"], table["thermal"]["basis"]) == ("prohibited", "stated")
    assert table["thermal"]["condition"] == "no fossil fuel based generation"
    # No general clause: market purchase is not addressed, not inferred from the type.
    assert (table["market_purchase"]["status"], table["market_purchase"]["basis"]) == (
        "not_addressed",
        "none",
    )
    assert not any(row.inherited for row in derivation.rows)
    assert derivation.note.startswith("4 of 9 sources addressed")


def test_an_epc_contract_addresses_no_source_and_the_rule_says_so() -> None:
    derivation = source_eligibility.derive({})
    assert [row.value["status"] for row in derivation.rows] == ["not_addressed"] * 9
    assert all(row.value["basis"] == "none" and row.inputs == () for row in derivation.rows)
    assert derivation.note.startswith("no decided clause addresses a source of supply")
    assert optimizer_constraints.derive({}).rows == []


def test_the_stricter_of_two_clauses_on_one_source_stands_with_both_conditions() -> None:
    inputs = fdre_ix()
    inputs[MIX] = decided(
        MIX,
        [{"source": "bess", "treatment": "allowed", "condition": "co-located"}],
        span(20, "storage may be co-located"),
    )
    table = rows_by_source(source_eligibility.derive(inputs))
    assert table["bess"]["status"] == "required"
    assert table["bess"]["condition"] == "co-located"
    assert table["bess"]["derived_from"] == f"{STORAGE_MANDATORY}, {MIX}"


def constraint(derivation: Any, subject: str) -> dict[str, Any]:
    found = [row.value for row in derivation.rows if row.value["subject"] == subject]
    assert len(found) == 1, subject
    return found[0]


def test_wbsedcl_constraints_are_typed_and_each_names_its_field_and_clause() -> None:
    derivation = optimizer_constraints.derive(wbsedcl())
    green = constraint(derivation, "traceable_green_share")
    assert (green["kind"], green["comparator"], green["value"], green["unit"], green["period"]) == (
        "quantity", ">=", 51, "percent_of_annual_energy", "annual",
    )  # fmt: skip
    assert green["basis"] == "stated" and green["derived_from"] == GREEN
    assert green["clause"] == "p.10: “" + GREEN_CLAUSE + "”"
    non_re = constraint(derivation, "non_re_share")
    assert (non_re["comparator"], non_re["value"], non_re["basis"]) == ("<=", 49, "inherited")
    for subject, value, unit, period in (
        ("cuf_annual", 80, "percent_of_annual_energy", "annual"),
        ("cuf_monthly", 70, "percent_of_monthly_energy", "monthly"),
        ("cuf_peak", 90, "percent_of_peak_energy", "peak_hours"),
    ):
        row = constraint(derivation, subject)
        assert (row["kind"], row["comparator"], row["value"], row["unit"], row["period"]) == (
            "quantity", ">=", value, unit, period,
        )  # fmt: skip
    window = constraint(derivation, "peak_window_hours")
    assert (window["value"], window["unit"], window["period"]) == (4, "hours_per_day", "daily")
    procurer = constraint(derivation, "peak_window_set_by_procurer")
    assert procurer["kind"] == "obligation" and procurer["holds"] is True
    assert "procurer's discretion" in procurer["condition"]
    rec = constraint(derivation, "rec_for_non_re_supply")
    assert rec["holds"] is True and rec["clause"].startswith("p.47:")
    assert constraint(derivation, "bess_re_charged_only")["holds"] is True
    co_located = constraint(derivation, "bess_co_located")
    assert co_located["condition"] == "per CERC Sharing Regulations"
    install = constraint(derivation, "linked_capacity_installation")
    assert (install["kind"], install["source"], install["condition"]) == (
        "obligation", "solar", "anywhere in India",
    )  # fmt: skip
    multiple = constraint(derivation, "linked_capacity_multiple")
    assert (multiple["value"], multiple["unit"]) == (2, "multiple_of_contracted_mw")
    assert constraint(derivation, "linked_capacity")["value"] == 3000
    assert constraint(derivation, "linked_land_per_mw")["unit"] == "acres_per_mw"
    stages = [
        row.value for row in derivation.rows if row.value["subject"] == "linked_capacity_documents"
    ]
    assert [
        (s["relative_to"], s["offset_months"], s["share_pct"], s["condition"]) for s in stages
    ] == [
        ("loa", 3, 50, "both"),
        ("loa", 6, 50, "both"),
    ]
    assert constraint(derivation, "supply_start")["on_date"] == "2028-07-01"
    assert constraint(derivation, "supply_start_greenshoe")["on_date"] == "2029-04-01"
    fixed = constraint(derivation, "non_re_tariff_fixed_share")
    assert (fixed["value"], fixed["unit"]) == (70, "percent_of_tariff")
    assert constraint(derivation, "non_re_tariff_variable_share")["value"] == 30
    merit = constraint(derivation, "non_re_merit_order_despatch")
    assert merit["holds"] is True and merit["condition"] == "on the variable charge"
    assert merit["clause"].startswith("p.12:"), "the clause that mentions merit order"
    term = constraint(derivation, "contract_term")
    assert (term["value"], term["unit"], term["period"]) == (25, "years", "contract_term")
    ids = [row.value["id"] for row in derivation.rows]
    assert ids == [f"c{n}" for n in range(1, len(ids) + 1)]
    assert all(
        row.value["kind"] in ("quantity", "temporal", "obligation") for row in derivation.rows
    )
    assert derivation.rows == optimizer_constraints.derive(wbsedcl()).rows, "deterministic"


def test_fdre_ix_constraints_hold_storage_and_the_prohibition() -> None:
    derivation = optimizer_constraints.derive(fdre_ix())
    mandatory = constraint(derivation, "storage_mandatory")
    assert (mandatory["kind"], mandatory["holds"], mandatory["source"]) == (
        "obligation",
        True,
        "bess",
    )
    prohibited = constraint(derivation, "source_prohibited")
    assert (prohibited["source"], prohibited["condition"]) == (
        "thermal",
        "no fossil fuel based generation",
    )
    assert len(derivation.rows) == 2


def test_the_clause_cited_is_the_span_that_mentions_the_subject_else_the_first() -> None:
    field = decided("x.y.z", 1, span(3, "something about wind"), span(7, "the thermal share"))
    assert clause_of(field, "thermal") == "p.7: “the thermal share”"
    assert clause_of(field, "hydro") == "p.3: “something about wind”"
    assert clause_of(field) == "p.3: “something about wind”"
    assert clause_of(decided("x.y.z", 1)) == ""
    long = decided("x.y.z", 1, span(1, "w " * 200))
    assert clause_of(long).endswith("...”") and len(clause_of(long)) < 260
