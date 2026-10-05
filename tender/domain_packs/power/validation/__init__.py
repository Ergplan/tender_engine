"""Validators whose meaning is specific to the power sector."""

from core.schemas import CrossFieldRule, RunRule
from tender.domain_packs.power.validation.rules import (
    bid_capacity_order,
    elements_have_kv,
    power_structured_agrees_with_scalar,
)

CROSS_FIELD_RULES: dict[str, CrossFieldRule] = {
    "bid_capacity_order": bid_capacity_order,
    "elements_have_kv": elements_have_kv,
    "power_structured_agrees_with_scalar": power_structured_agrees_with_scalar,
}
RUN_RULES: dict[str, RunRule] = {}
