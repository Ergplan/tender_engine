"""Extraction schemas: data that tells core which fields to extract and how to check them."""

from core.schemas.model import (
    ExtractionSchema,
    FieldDef,
    FieldGroup,
    FieldValidation,
    RoutingHints,
)
from core.schemas.registry import CrossFieldRule, RuleOutcome, SchemaRegistry, UnknownSchemaError
from core.schemas.types import ValueType, ValueTypeRegistry

__all__ = [
    "CrossFieldRule",
    "ExtractionSchema",
    "FieldDef",
    "FieldGroup",
    "FieldValidation",
    "RoutingHints",
    "RuleOutcome",
    "SchemaRegistry",
    "UnknownSchemaError",
    "ValueType",
    "ValueTypeRegistry",
]
