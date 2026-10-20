"""Validators of the result pack: deterministic checks on an imported award table."""

from core.schemas import CrossFieldRule, RunRule
from tender.domain_packs.result.validation.rules import (
    WINNERS,
    award_adopted_within_awarded,
    award_capacity_positive,
    award_price_in_band,
    award_rows_have_status,
    award_rows_located,
    award_unit_matches_kind,
)

CROSS_FIELD_RULES: dict[str, CrossFieldRule] = {
    "award_rows_have_status": award_rows_have_status,
    "award_capacity_positive": award_capacity_positive,
    "award_adopted_within_awarded": award_adopted_within_awarded,
    "award_price_in_band": award_price_in_band,
    "award_unit_matches_kind": award_unit_matches_kind,
}
RUN_RULES: dict[str, RunRule] = {"award_rows_located": award_rows_located}
# Which fields each run rule concerns, for the field trace.
RUN_RULE_FIELDS: dict[str, object] = {
    "award_rows_located": lambda field: field.path == WINNERS,
}
