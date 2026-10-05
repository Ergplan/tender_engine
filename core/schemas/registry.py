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
    """Result of a cross-field rule for the fields it concerns. A failed outcome marked
    `warning` is shown to the reviewer but does not send the candidate to needs_review:
    it is for a pattern that is unusual, not wrong."""

    field_paths: tuple[str, ...]
    passed: bool
    message: str
    warning: bool = False


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
        self._excluded: dict[tuple[str, str], frozenset[str]] = {}
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

    def versions_read_as(self, name: str, version: str) -> set[str]:
        """The versions of a schema whose runs are read together with this one: those
        registered with the same groups, fields and rules. A version that only adds to an
        earlier one is registered a second time under the earlier version, so the runs of
        sections that were not read again stay part of the object's record. A version that
        changes or removes a field has other content and is read on its own."""
        content = self.get(name, version).model_dump(exclude={"version"})
        return {
            other_version
            for (other_name, other_version), schema in self._schemas.items()
            if other_name == name and schema.model_dump(exclude={"version"}) == content
        }

    def exclude_fields(self, name: str, version: str, paths: tuple[str, ...]) -> None:
        """Fields of a registered version that are not read from its runs: a later version
        changed them and reads their sections again."""
        self.get(name, version)
        self._excluded[(name, version)] = frozenset(paths)

    def excluded_fields(self, name: str, version: str) -> frozenset[str]:
        return self._excluded.get((name, version), frozenset())

    def names(self) -> list[tuple[str, str]]:
        return sorted(self._schemas)
