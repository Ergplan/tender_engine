"""A small, non-tender schema: proves core works with any schema plugged in."""

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

SCHEMA_NAME, SCHEMA_VERSION = "test.contract", "v1"


def date_order(values: dict[str, Any]) -> list[RuleOutcome]:
    pre_bid, deadline = values.get("dates.pre_bid_date"), values.get("dates.bid_deadline")
    if pre_bid is None or deadline is None:
        return []
    paths = ("dates.pre_bid_date", "dates.bid_deadline")
    if pre_bid <= deadline:
        return [RuleOutcome(paths, True, "pre-bid date is not after the bid deadline")]
    return [RuleOutcome(paths, False, f"pre-bid date {pre_bid} is after bid deadline {deadline}")]


def contract_schema() -> ExtractionSchema:
    return ExtractionSchema(
        name=SCHEMA_NAME,
        version=SCHEMA_VERSION,
        groups=[
            FieldGroup(
                name="identity",
                routing=RoutingHints(section_kinds=["cover_and_notice"], keywords=["agreement no"]),
            ),
            FieldGroup(
                name="dates",
                routing=RoutingHints(section_kinds=["dates_and_schedule"], keywords=["key dates"]),
                guidance="Dates are day-first.",
            ),
            FieldGroup(
                name="security",
                routing=RoutingHints(section_kinds=["financial_security"], keywords=["security"]),
            ),
        ],
        fields=[
            FieldDef(
                path="identity.agreement_number",
                label="Agreement number",
                group="identity",
                value_type="text",
                required=True,
                validation=FieldValidation(regex=r"ACME/\d{4}/\d{3}"),
                review_order=1,
            ),
            FieldDef(
                path="identity.issuer",
                label="Issuer",
                group="identity",
                value_type="text",
                review_order=2,
            ),
            FieldDef(
                path="dates.pre_bid_date",
                label="Pre-bid meeting date",
                group="dates",
                value_type="date",
                review_order=3,
            ),
            FieldDef(
                path="dates.bid_deadline",
                label="Bid deadline",
                group="dates",
                value_type="date",
                required=True,
                review_order=4,
            ),
            FieldDef(
                path="security.emd_per_mw",
                label="EMD per MW",
                group="security",
                value_type="decimal",
                unit="INR",
                validation=FieldValidation(min=1, max=10_000_000),
                review_order=5,
            ),
            FieldDef(
                path="security.capacity_mw",
                label="Capacity",
                group="security",
                value_type="decimal",
                unit="MW",
                required=True,
                review_order=6,
            ),
            FieldDef(
                path="security.tenure_years",
                label="Tenure",
                group="security",
                value_type="int",
                unit="years",
                validation=FieldValidation(min=10, max=35),
                review_order=7,
            ),
        ],
        cross_field_rules=["contract_date_order"],
    )


def make_registry() -> SchemaRegistry:
    registry = SchemaRegistry()
    registry.register_rule("contract_date_order", date_order)
    registry.register(contract_schema())
    return registry
