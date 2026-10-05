"""Extraction schemas: data that tells core which fields to extract and how to check them."""

from core.schemas.model import (
    ExtractionSchema,
    FieldDef,
    FieldGroup,
    FieldValidation,
    KeyDef,
    RoutingHints,
)
from core.schemas.registry import (
    CandidateOutcome,
    CrossFieldRule,
    RuleOutcome,
    RunRule,
    SchemaRegistry,
    UnknownSchemaError,
)
from core.schemas.types import ValueType, ValueTypeRegistry

__all__ = [
    "CandidateOutcome",
    "CrossFieldRule",
    "ExtractionSchema",
    "FieldDef",
    "FieldGroup",
    "FieldValidation",
    "KeyDef",
    "RoutingHints",
    "RuleOutcome",
    "RunRule",
    "SchemaRegistry",
    "UnknownSchemaError",
    "ValueType",
    "ValueTypeRegistry",
]
