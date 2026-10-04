"""The 12-field schema of the Stage 1 end-to-end test. It lives with the tests, not in
core: core receives it like any other schema. Stage 2 replaces it with tender/schemas/."""

from typing import Any

from core.schemas import (
    ExtractionSchema,
    FieldDef,
    FieldGroup,
    FieldValidation,
    RoutingHints,
    RuleOutcome,
    SchemaRegistry,
)

SCHEMA_NAME, SCHEMA_VERSION = "test.fdre12", "v1"


def pre_bid_before_deadline(values: dict[str, Any]) -> list[RuleOutcome]:
    pre_bid = values.get("key_dates.pre_bid_date")
    deadline = values.get("key_dates.bid_deadline")
    if pre_bid is None or deadline is None:
        return []
    paths = ("key_dates.pre_bid_date", "key_dates.bid_deadline")
    if pre_bid <= deadline:
        return [RuleOutcome(paths, True, "pre-bid date is not after the bid deadline")]
    return [RuleOutcome(paths, False, f"pre-bid date {pre_bid} is after bid deadline {deadline}")]


def fdre12_schema() -> ExtractionSchema:
    def field(path: str, label: str, value_type: str, order: int, **extra: Any) -> FieldDef:
        return FieldDef(
            path=path,
            label=label,
            group=path.split(".", 1)[0],
            value_type=value_type,
            review_order=order,
            **extra,
        )

    return ExtractionSchema(
        name=SCHEMA_NAME,
        version=SCHEMA_VERSION,
        groups=[
            FieldGroup(
                name="identity",
                routing=RoutingHints(
                    section_kinds=["cover_and_notice", "introduction_and_scope"],
                    keywords=["rfs no", "bid information sheet"],
                ),
            ),
            FieldGroup(
                name="key_dates",
                routing=RoutingHints(
                    section_kinds=["cover_and_notice", "dates_and_schedule"],
                    keywords=["pre-bid meeting", "bid submission"],
                ),
                guidance="Dates are day-first. Give a date only if the pages print it.",
            ),
            FieldGroup(
                name="security",
                routing=RoutingHints(
                    section_kinds=["financial_security"],
                    keywords=["earnest money deposit", "performance bank guarantee"],
                ),
                guidance="Amounts are in INR per MW. Convert lakh and crore to plain rupees.",
            ),
            FieldGroup(
                name="commercial",
                routing=RoutingHints(
                    section_kinds=["commercial_terms", "technical_requirements"],
                    keywords=[
                        "scheduled commencement of supply",
                        "power purchase agreement",
                        "capacity utilization factor",
                    ],
                ),
            ),
        ],
        fields=[
            field("identity.tender_number", "Tender (RfS) number", "text", 1, required=True),
            field("identity.issuing_agency", "Issuing agency", "text", 2, required=True),
            field(
                "identity.capacity_mw",
                "Total capacity offered under the tender",
                "decimal",
                3,
                unit="MW",
                required=True,
                validation=FieldValidation(min=1, max=100_000),
            ),
            field(
                "identity.connectivity_type",
                "Grid the projects must connect to",
                "enum",
                4,
                enum_values=["ists", "intra_state", "ists_or_intra_state"],
            ),
            field("key_dates.pre_bid_date", "Pre-bid meeting date", "date", 5),
            field("key_dates.bid_deadline", "Bid submission deadline", "date", 6),
            field(
                "security.emd_per_mw",
                "Earnest money deposit per MW",
                "decimal",
                7,
                unit="INR per MW",
                validation=FieldValidation(min=1_000, max=100_000_000),
            ),
            field(
                "security.pbg_per_mw",
                "Performance bank guarantee per MW",
                "decimal",
                8,
                unit="INR per MW",
                validation=FieldValidation(min=1_000, max=100_000_000),
            ),
            field(
                "commercial.scod_months",
                "Months from the effective date of the PPA to scheduled commencement of supply",
                "int",
                9,
                unit="months",
                validation=FieldValidation(min=1, max=120),
            ),
            field(
                "commercial.ppa_tenure_years",
                "PPA tenure",
                "int",
                10,
                unit="years",
                validation=FieldValidation(min=1, max=50),
            ),
            field(
                "commercial.tariff_ceiling",
                "Ceiling tariff, if the tender sets one",
                "decimal",
                11,
                unit="INR per kWh",
                validation=FieldValidation(min=0.1, max=50),
            ),
            field(
                "commercial.min_cuf_percent",
                "Minimum capacity utilisation factor, if the tender sets one",
                "decimal",
                12,
                unit="percent",
                validation=FieldValidation(min=1, max=100),
            ),
        ],
        cross_field_rules=["pre_bid_before_deadline"],
    )


def make_fdre_registry() -> SchemaRegistry:
    registry = SchemaRegistry()
    registry.register_rule("pre_bid_before_deadline", pre_bid_before_deadline)
    registry.register(fdre12_schema())
    return registry
