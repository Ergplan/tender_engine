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
    assert rule_for(source_eligibility.FIELD).version == source_eligibility.VERSION == "v2"
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


PHES_CLAUSE = "SOLUTIONS OF 2000 MW / 12000 MWh WITH 500 MW (MIN) CAPACITY AT SINGLE LOCATION"
COMMON = "sector.power.common."


def ntpc_phes() -> Inputs:
    """The NTPC PHES tender as the owner read it (2026-10-13): the rule's v1 table held only
    the power capacity and the term; their edit listed what was missing."""

    def field(name: str, value: Any, page: int, quote: str) -> tuple[str, Decided]:
        path = name if "." in name else COMMON + name
        return path, decided(path, value, span(page, quote))

    return dict(
        [
            field("total_capacity_mw", 2000, 1, PHES_CLAUSE),
            field("total_capacity_mwh", 12000, 1, PHES_CLAUSE),
            field("min_bid_mw", 500, 1, PHES_CLAUSE),
            field("max_bid_mw", 2000, 3, "a bidder may quote up to the full 2000 MW (max)"),
            field("location_constraint", "ists_anywhere", 2, "located anywhere in India (ISTS)"),
            field("scod_months", 48, 4, "commissioning within 48 months from the ESSA signing"),
            field("scod_reference", "ppa_signing", 4, "counted from the signing of the ESSA"),
            field("ppa_signing_window_days", 30, 5, "the ESSA shall be signed within 30 days"),
            field("ppa_tenure_years", 25, 2, "for a period of 25 Years"),
            field("sector.power.bess.cycles_per_day", 2, 6, "two charge-discharge cycles per day"),
            field(
                "sector.power.bess.round_trip_efficiency_guarantee_percent",
                75,
                6,
                "round trip efficiency of not less than 75%",
            ),
            field("sector.power.bess.availability_floor_percent", 95, 6, "availability of 95%"),
        ]
    )


def test_phes_constraints_carry_energy_size_location_and_milestones_from_their_fields() -> None:
    derivation = optimizer_constraints.derive(ntpc_phes())
    by_subject = {row.value["subject"]: row.value for row in derivation.rows}
    assert set(by_subject) == {
        "contracted_capacity",
        "contracted_energy_capacity",
        "project_capacity_min",
        "project_capacity_max",
        "location_constraint",
        "scod",
        "ppa_signing",
        "contract_term",
        "storage_cycles_per_day",
        "round_trip_efficiency",
        "availability",
    }
    energy = by_subject["contracted_energy_capacity"]
    assert (energy["kind"], energy["comparator"], energy["value"], energy["unit"]) == (
        "quantity",
        "==",
        12000.0,
        "mwh",
    )
    assert energy["clause"] == f"p.1: “{PHES_CLAUSE}”"
    assert (
        by_subject["project_capacity_min"]["comparator"],
        by_subject["project_capacity_min"]["value"],
    ) == (">=", 500.0)
    assert (
        by_subject["project_capacity_max"]["comparator"],
        by_subject["project_capacity_max"]["value"],
    ) == ("<=", 2000.0)
    location = by_subject["location_constraint"]
    assert (location["kind"], location["holds"], location["condition"]) == (
        "obligation",
        True,
        "anywhere in India, connected to the ISTS",
    )
    scod = by_subject["scod"]
    assert (scod["kind"], scod["relative_to"], scod["offset_months"]) == (
        "temporal",
        "ppa_signing",
        48.0,
    )
    assert scod["derived_from"] == f"{COMMON}scod_months, {COMMON}scod_reference", (
        "the milestone names the field that gives its event as well"
    )
    assert scod["clause"].startswith("p.4:")
    ppa = by_subject["ppa_signing"]
    assert (ppa["relative_to"], ppa["offset_days"]) == ("loa", 30.0)
    assert by_subject["storage_cycles_per_day"]["period"] == "daily"
    assert by_subject["availability"]["unit"] == "percent"
    assert all(row.value["basis"] == "stated" for row in derivation.rows)
    assert derivation.note == "11 constraint(s) from 12 decided field(s)"
    assert (
        optimizer_constraints.VERSION == "v3"
        and rule_for(optimizer_constraints.FIELD).version == "v3"
    )


def test_a_milestone_without_its_reference_field_says_so() -> None:
    inputs = {
        COMMON + "scod_months": decided(
            COMMON + "scod_months", 24, span(4, "commissioning within 24 months")
        )
    }
    (row,) = optimizer_constraints.derive(inputs).rows
    assert (row.value["relative_to"], row.value["derived_from"]) == (
        "unspecified",
        COMMON + "scod_months",
    )


def everything_decided() -> Inputs:
    """One decided value per field the optimiser rule reads, shaped so that every branch of
    the rule writes its row."""
    oc = optimizer_constraints
    records: dict[str, Any] = {
        oc.PEAK_WINDOW: {"hours_per_day": 4, "set_by": "procurer", "stretches": "multiple"},
        oc.REC: {"applies_to": "all_non_re_energy"},
        oc.CHARGING: {"re_only": True, "co_located_required": True, "regulation_reference": "r"},
        oc.LINKED: {
            "technology": "solar",
            "multiple_of_contracted": 2,
            "capacity_mw": 3000,
            "acres_per_mw": 4,
            "location": "in the state",
            "stages": [{"months_from_loa": 3, "share_pct": 50, "documents": "land"}],
        },
        oc.TARIFF_SPLIT: {
            "fixed_pct": 70,
            "variable_pct": 30,
            "merit_order_treatment": "merit_order_on_variable_charge",
        },
        oc.MIX: [{"source": "thermal", "treatment": "prohibited"}],
        oc.LOCATION: "state_specific",
        oc.SCOD_REFERENCE: "effective_date",
        oc.FC_REFERENCE: "before_scod",
        oc.SUPPLY_START: "2028-07-01",
        oc.GREENSHOE_SSD: "2029-04-01",
        oc.GREENSHOE_OFFER: "2028-01-31",
        oc.STORAGE_MANDATORY: True,
    }
    found = {
        path: decided(path, records.get(path, 42), span(1, "the clause")) for path in oc.INPUTS
    }
    # One input withdrawn by a later version: its branch writes nothing, the table a
    # `withdrawn` row under the same subject.
    found[oc.AVAILABILITY_FLOOR] = withdrawn(
        oc.AVAILABILITY_FLOOR, 5, "availability clause deleted"
    )
    return found


def withdrawn(path: str, by: int, quote: str) -> Decided:
    return Decided(
        path=path,
        label=path.rsplit(".", 1)[1],
        value=None,
        spans=[span(2, quote)],
        version_no=by,
        withdrawn=True,
        withdrawn_by=by,
    )


def test_every_row_the_optimiser_rule_can_write_fits_the_tables_keys() -> None:
    """The rule's subjects, units, periods and events are literals; the table's keys are
    enums in the pack. A row outside them would fail validation on every tender that
    reaches the rule (found by the independent review of rule v2, 2026-10-13)."""
    from tender.services.packs import load_catalog

    table = load_catalog().get("solar").schema.field(optimizer_constraints.FIELD)
    keys = {key.name: key for key in table.keys or []}
    derivation = optimizer_constraints.derive(everything_decided())
    branches = {row.value["subject"] for row in derivation.rows}
    assert len(branches) >= 30, f"the inputs do not reach every branch: {sorted(branches)}"
    for row in derivation.rows:
        for name, value in row.value.items():
            assert name in keys, f"{row.value['subject']} writes a key the table lacks: {name}"
            allowed = keys[name].enum_values
            if allowed:
                assert value in allowed, f"{row.value['subject']}.{name} = {value!r} not allowed"


def test_of_two_limits_on_one_source_the_lower_stands_and_a_higher_status_beats_either() -> None:
    """Two clauses limit thermal, 49% and 30% of annual energy: the 30% row stands, naming
    both clauses. A prohibition beats any limit (addendum review run 2, 2026-10-13)."""
    limited = decided(
        MIX,
        [
            {
                "source": "thermal",
                "treatment": "allowed_with_limit",
                "limit_value": 49,
                "limit_unit": "percent_of_annual_energy",
                "condition": "overall",
            },  # noqa: E501
            {
                "source": "thermal",
                "treatment": "allowed_with_limit",
                "limit_value": 30,
                "limit_unit": "percent_of_annual_energy",
                "condition": "in peak hours",
            },  # noqa: E501
        ],
        span(3, "thermal power up to 49% ... thermal supply in peak hours up to 30%"),
    )
    rows = {r.value["source"]: r.value for r in source_eligibility.derive({MIX: limited}).rows}
    thermal = rows["thermal"]
    assert (thermal["status"], thermal["limit_value"]) == ("allowed_with_limit", 30)
    assert thermal["condition"] == "in peak hours; overall", "both clauses' conditions kept"
    reversed_order = decided(MIX, list(reversed(limited.value)), *limited.spans)
    rows = {
        r.value["source"]: r.value for r in source_eligibility.derive({MIX: reversed_order}).rows
    }
    assert rows["thermal"]["limit_value"] == 30, "whichever clause comes first"
    prohibited = decided(
        MIX,
        [*limited.value, {"source": "thermal", "treatment": "prohibited"}],
        *limited.spans,
    )
    rows = {r.value["source"]: r.value for r in source_eligibility.derive({MIX: prohibited}).rows}
    assert rows["thermal"]["status"] == "prohibited" and "limit_value" not in rows["thermal"]


def test_a_withdrawn_input_is_a_typed_row_of_the_optimiser_table_not_an_absence() -> None:
    """The owner's rule: a ceiling removed last week is told apart from one that never
    existed. A withdrawn input constrains nothing and gets one `withdrawn` row under the
    subject it would have constrained, with the removing words as its clause."""
    oc = optimizer_constraints
    capacity = "sector.power.common.total_capacity_mw"
    tenure = "sector.power.common.ppa_tenure_years"
    rows = oc.derive(
        {
            capacity: withdrawn(capacity, 5, "the contracted capacity clause stands deleted"),
            tenure: decided(tenure, 25, span(1, "for a period of 25 years")),
        }
    )
    by_subject = {row.value["subject"]: row for row in rows.rows}
    assert set(by_subject) == {"contract_term", "contracted_capacity"}
    gone = by_subject["contracted_capacity"]
    assert (gone.value["kind"], gone.value["holds"], gone.value["condition"]) == (
        "withdrawn",
        False,
        "withdrawn by v5",
    )
    assert (gone.value["basis"], gone.value["derived_from"]) == ("stated", capacity)
    assert gone.value["clause"] == "p.2: \u201cthe contracted capacity clause stands deleted\u201d"
    assert "value" not in gone.value and "unit" not in gone.value
    assert rows.note == "2 constraint(s) from 2 decided field(s); 1 withdrawn by amendment"
    assert oc.VERSION == "v3" and rule_for(oc.FIELD).inputs_at("v2") == oc.INPUTS
    assert set(oc.SUBJECT_OF_INPUT) == set(oc.INPUTS)


def test_a_withdrawn_storage_obligation_reads_bess_as_withdrawn_unless_a_clause_stands() -> None:
    se = source_eligibility
    gone = withdrawn(STORAGE_MANDATORY, 3, "the storage requirement is withdrawn")
    rows = {r.value["source"]: r.value for r in se.derive({STORAGE_MANDATORY: gone}).rows}
    assert (rows["bess"]["status"], rows["bess"]["basis"], rows["bess"]["condition"]) == (
        "withdrawn",
        "stated",
        "withdrawn by v3",
    )
    assert rows["bess"]["clause"] == "p.2: \u201cthe storage requirement is withdrawn\u201d"
    assert rows["bess"]["derived_from"] == STORAGE_MANDATORY
    assert all(rows[s]["status"] == "not_addressed" for s in se.SOURCES if s != "bess")
    assert se.derive({STORAGE_MANDATORY: gone}).note.endswith("storage_mandatory withdrawn by v3")
    # A clause still naming BESS stands; the withdrawn charging rule is noted on it.
    standing = decided(
        MIX, [{"source": "bess", "treatment": "allowed"}], span(10, "storage is allowed")
    )
    rows = {
        r.value["source"]: r.value
        for r in se.derive(
            {MIX: standing, CHARGING: withdrawn(CHARGING, 4, "charging rule deleted")}
        ).rows
    }
    assert rows["bess"]["status"] == "allowed"
    assert "bess_charging_rule withdrawn by v4" in rows["bess"]["condition"]
    assert rows["bess"]["derived_from"] == f"{MIX}, {CHARGING}"
    assert se.VERSION == "v2" and rule_for(se.FIELD).inputs_at("v1") == se.INPUTS
