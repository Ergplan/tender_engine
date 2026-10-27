"""Which field a question is about (Stage 7, Block 5 b): the deterministic mapping."""

import pytest

from tender.services.ask_fields import map_question, question_words, words
from tender.services.packs import build_registry, schema_name

DEADLINE = "core.key_dates.bid_submission_deadline"
EMD = "core.guarantees.emd_per_mw_inr"
PBG = "core.guarantees.pbg_per_mw_inr"


@pytest.fixture(scope="module")
def schema():  # type: ignore[no-untyped-def]
    schemas, catalog = build_registry()
    compiled = catalog.get("solar")
    return schemas.get(schema_name("solar"), compiled.schema.version)


def test_words_drop_stopwords_and_plurals_and_aliases_expand() -> None:
    assert words("What is the bid submission deadline?") == ["bid", "submission", "deadline"]
    assert "penalty" in question_words("What penalties apply?")
    assert {"earnest", "money", "deposit"} <= question_words("How much is the EMD?")


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What is the bid submission deadline?", DEADLINE),
        ("When is the last date for bid submission?", DEADLINE),
        ("How much EMD per MW is payable?", EMD),
        ("What is the earnest money deposit per MW in INR?", EMD),
        ("What PBG per MW must the bidder furnish?", PBG),
    ],
)
def test_questions_that_name_a_field_map_to_it(schema, question: str, expected: str) -> None:  # type: ignore[no-untyped-def]
    match = map_question(question, schema)
    assert match is not None and match.field.path == expected, (question, match)


@pytest.mark.parametrize(
    "question",
    [
        "Which transmission licensee operates the pooling substation?",
        "How is the bid evaluated when two bidders quote the same tariff?",
        "Summarise the dispute resolution clause.",
        "deadline",
    ],
)
def test_questions_that_name_no_field_or_are_ambiguous_map_to_none(schema, question: str) -> None:  # type: ignore[no-untyped-def]
    match = map_question(question, schema)
    assert match is None, (question, match.field.path if match else None)
