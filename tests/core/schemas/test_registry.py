import pytest
from pydantic import ValidationError

from core.schemas import (
    ExtractionSchema,
    FieldDef,
    FieldGroup,
    SchemaRegistry,
    UnknownSchemaError,
)
from tests.fixtures.schemas import contract_schema, date_order, make_registry


def schema(**overrides: object) -> ExtractionSchema:
    fields = {
        "name": "s",
        "version": "v1",
        "groups": [FieldGroup(name="g")],
        "fields": [FieldDef(path="g.a", label="A", group="g", value_type="text")],
    }
    fields.update(overrides)
    return ExtractionSchema(**fields)  # type: ignore[arg-type]


def test_registry_returns_a_registered_schema_and_refuses_others() -> None:
    registry = make_registry()
    assert registry.get("test.contract", "v1").name == "test.contract"
    assert registry.names() == [("test.contract", "v1")]
    with pytest.raises(UnknownSchemaError, match="test.contract v2 is not registered"):
        registry.get("test.contract", "v2")


def test_fields_in_group_are_in_review_order_and_keys_are_last_segments() -> None:
    fields = contract_schema().fields_in("security")
    assert [f.key for f in fields] == ["emd_per_mw", "capacity_mw", "tenure_years"]
    assert contract_schema().field("dates.bid_deadline").required is True
    with pytest.raises(KeyError):
        contract_schema().field("dates.nope")


def test_registering_twice_is_refused() -> None:
    registry = make_registry()
    with pytest.raises(ValueError, match="already registered"):
        registry.register(contract_schema())
    with pytest.raises(ValueError, match="already registered"):
        registry.register_rule("date_order", date_order)


def test_schema_with_an_unregistered_rule_or_type_is_refused() -> None:
    registry = SchemaRegistry()
    with pytest.raises(ValueError, match="unregistered rule 'date_order'"):
        registry.register(contract_schema())
    with pytest.raises(ValueError, match="unknown value type 'money'"):
        registry.register(
            schema(fields=[FieldDef(path="g.a", label="A", group="g", value_type="money")])
        )
    with pytest.raises(ValueError, match="enum without enum_values"):
        registry.register(
            schema(fields=[FieldDef(path="g.a", label="A", group="g", value_type="enum")])
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"groups": [FieldGroup(name="g"), FieldGroup(name="g")]}, "duplicate group name"),
        (
            {"fields": [FieldDef(path="g.a", label="A", group="g", value_type="text")] * 2},
            "duplicate field path",
        ),
        (
            {"fields": [FieldDef(path="g.a", label="A", group="other", value_type="text")]},
            "unknown group",
        ),
        ({"groups": [FieldGroup(name="g"), FieldGroup(name="empty")]}, "has no fields"),
        (
            {
                "fields": [
                    FieldDef(path="x.a", label="A", group="g", value_type="text"),
                    FieldDef(path="y.a", label="A2", group="g", value_type="text"),
                ]
            },
            "same key",
        ),
    ],
)
def test_inconsistent_schemas_are_refused(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        schema(**overrides)


def test_field_path_must_be_dotted_snake_case() -> None:
    with pytest.raises(ValidationError):
        FieldDef(path="NoDots", label="A", group="g", value_type="text")
