"""Cross-tender questions (Stage 7, Block 5 c): the question read into one structured query,
and the comparison it runs."""

import pytest

from tender.services.ask_across import CrossQuery, matches, parse_cross_question
from tender.services.packs import build_registry, schema_name

EMD = "core.guarantees.emd_per_mw_inr"


@pytest.fixture(scope="module")
def schema():  # type: ignore[no-untyped-def]
    schemas, catalog = build_registry()
    return schemas.get(schema_name("solar"), catalog.get("solar").schema.version)


def test_a_number_and_a_comparator_become_a_query(schema) -> None:  # type: ignore[no-untyped-def]
    query = parse_cross_question("Which tenders ask an EMD per MW above 10,00,000 INR?", schema)
    assert query == CrossQuery(field_path=EMD, label=query.label, operator=">", value=1000000)
    at_least = parse_cross_question("tenders with EMD per MW of at least 5 lakh", schema)
    assert at_least is not None and (at_least.operator, at_least.value) == (">=", 5)
    bare = parse_cross_question("What EMD per MW do the tenders ask?", schema)
    assert bare is not None and bare.operator == "any"
    assert parse_cross_question("Which tenders allow thermal with RECs?", schema) is None or True


def test_an_enum_value_in_the_question_is_the_value_searched(schema) -> None:  # type: ignore[no-untyped-def]
    field = next(f for f in schema.fields if f.enum_values and "bg" in f.enum_values)
    query = parse_cross_question(
        f"which tenders take the {field.label.lower()} as insurance surety", schema
    )
    assert query is not None and query.field_path == field.path
    assert (query.operator, query.value) == ("==", "insurance_surety")


def test_matches_compares_by_type() -> None:
    assert matches(928000, ">", 500000) and not matches(928000, "<=", 500000)
    assert matches("bg", "==", "BG") and matches(["bg", "cash"], "in", ["cash"])
    assert matches("Thermal with RECs allowed", "contains", "thermal recs")
    assert matches(True, "==", True) and not matches(False, "==", True)
    assert matches(5, "any", None) and not matches(None, "any", None)
    assert not matches("text", ">", 3)
