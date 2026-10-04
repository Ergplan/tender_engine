"""Schemas and cross-field rules, registered by a domain layer and looked up by core.

An instance is built at process start and passed down; there is no module-level registry.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.schemas.model import ExtractionSchema
from core.schemas.types import ValueTypeRegistry

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from core.models import Candidate, ExtractionRun


class UnknownSchemaError(LookupError):
    pass


@dataclass(frozen=True)
class RuleOutcome:
    """Result of a cross-field rule for the fields it concerns."""

    field_paths: tuple[str, ...]
    passed: bool
    message: str


# A cross-field rule receives {field_path: coerced value} for the fields that have one.
CrossFieldRule = Callable[[dict[str, Any]], list[RuleOutcome]]


@dataclass(frozen=True)
class CandidateOutcome:
    """Result of a run rule for one candidate."""

    candidate_id: str
    passed: bool
    message: str


# A run rule receives the session, the run and the run's candidates that carry a value. It
# is plain Python over the database: it may read, it never writes and never calls a model.
RunRule = Callable[["Session", "ExtractionRun", Sequence["Candidate"]], list[CandidateOutcome]]


class SchemaRegistry:
    def __init__(self) -> None:
        self.value_types = ValueTypeRegistry()
        self._schemas: dict[tuple[str, str], ExtractionSchema] = {}
        self._rules: dict[str, CrossFieldRule] = {}
        self._run_rules: dict[str, RunRule] = {}

    def register_rule(self, name: str, rule: CrossFieldRule) -> None:
        if name in self._rules:
            raise ValueError(f"rule {name!r} is already registered")
        self._rules[name] = rule

    def rule(self, name: str) -> CrossFieldRule:
        return self._rules[name]

    def register_run_rule(self, name: str, rule: RunRule) -> None:
        if name in self._run_rules:
            raise ValueError(f"run rule {name!r} is already registered")
        self._run_rules[name] = rule

    def run_rule(self, name: str) -> RunRule:
        return self._run_rules[name]

    def register(self, schema: ExtractionSchema) -> None:
        key = (schema.name, schema.version)
        if key in self._schemas:
            raise ValueError(f"schema {schema.name} {schema.version} is already registered")
        for field in schema.fields:
            self.value_types.get(field.value_type)
            if field.value_type == "enum" and not field.enum_values:
                raise ValueError(f"{field.path} is an enum without enum_values")
        for rule_name in schema.cross_field_rules:
            if rule_name not in self._rules:
                raise ValueError(f"schema names unregistered rule {rule_name!r}")
        for rule_name in schema.run_rules:
            if rule_name not in self._run_rules:
                raise ValueError(f"schema names unregistered run rule {rule_name!r}")
        self._schemas[key] = schema

    def get(self, name: str, version: str) -> ExtractionSchema:
        try:
            return self._schemas[(name, version)]
        except KeyError:
            raise UnknownSchemaError(f"schema {name} {version} is not registered") from None

    def names(self) -> list[tuple[str, str]]:
        return sorted(self._schemas)
