"""ask_tender (Stage 7, Block 5 b): a field question answered from the record, a free
question answered from retrieved passages with every quote located, the amendment note,
and the honest answer when nothing is found."""

from sqlalchemy.orm import Session

from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE, amended_tender, extracted_tender

PBG_LINE = "Performance Bank Guarantee (PBG) of INR 2320000 per MW shall be furnished."


def test_a_field_question_is_answered_from_the_engines_reading_until_a_reviewer_decides(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    calls = len(pipeline.sdk.calls)
    answer = pipeline.ask.ask(
        db, tender, "What is the bid submission deadline?", created_by="pytest"
    )
    assert (answer.mode, answer.source, answer.field_path) == ("field", "machine", DEADLINE)
    assert answer.value == "30.03.2026" and answer.version_no == 1
    assert answer.confidence is not None and "not yet reviewed" in answer.answer
    assert (answer.citations_total, answer.citations_resolved) == (1, 1)
    citation = answer.citations[0]
    assert (citation.page_no, citation.resolved, citation.filename) == (2, True, "rfs.pdf")
    assert citation.bbox is not None and citation.char_start is not None
    assert answer.is_fact is False and answer.cost_usd == 0
    assert len(pipeline.sdk.calls) == calls, "no model call for a field of the record"
    assert not answer.amendment_changed and answer.amendment_note is None


def test_a_free_question_is_answered_from_passages_and_each_quote_is_resolved_or_not(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    pipeline.sdk.ask_answer = {
        "answer": "A PBG of INR 2320000 per MW is to be furnished. It is five crore in all.",
        "answered": True,
        "claims": [
            {
                "statement": "A PBG of INR 2320000 per MW is to be furnished.",
                "passage": 1,
                "quote": PBG_LINE,
            },
            {
                "statement": "It is five crore in all.",
                "passage": 1,
                "quote": "PBG of INR 5 crore in all",
            },
            {
                "statement": "A claim on a passage that was not sent.",
                "passage": 9,
                "quote": "nothing",
            },
        ],
        "amendment_changed": False,
        "amendment_note": None,
    }
    answer = pipeline.ask.ask(
        db,
        tender,
        "What performance bank guarantee must the successful bidder furnish?",
        created_by="pytest",
    )
    assert (answer.mode, answer.source, answer.retrieval) == ("retrieval", "machine", "keyword")
    assert answer.passages_read == 1, "only the page that holds the words"
    assert (answer.citations_total, answer.citations_resolved) == (2, 1)
    located, missing = answer.citations
    assert (located.resolved, located.page_no, located.quote) == (True, 3, PBG_LINE)
    assert located.bbox is not None and located.version_no == 1
    assert missing.resolved is False and missing.reason and missing.bbox is None
    assert [c.citations for c in answer.claims] == [[1], [2], []]
    assert answer.cost_usd > 0 and answer.call_log_id and answer.is_fact is False
    sent = pipeline.sdk.calls[-1]["messages"][0]["content"][-1]["text"]
    assert "[1] rfs.pdf p.3" in sent and PBG_LINE in sent and "Question:" in sent


def test_an_amendment_moves_the_answer_and_the_note_says_which_version(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    amended_tender(pipeline, db, tender)
    answer = pipeline.ask.ask(
        db, tender, "When is the last date of bid submission?", created_by="pytest"
    )
    assert (answer.mode, answer.value, answer.version_no) == ("field", "15.04.2026", 2)
    assert answer.amendment_changed and answer.amendment_note
    assert "Version 2" in answer.amendment_note and "30.03.2026" in answer.amendment_note
    assert answer.citations and answer.citations[0].filename == "amendment-01.pdf"
    assert answer.citations[0].resolved


def test_a_question_nothing_answers_is_said_to_be_unanswered_without_a_model_call(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    calls = len(pipeline.sdk.calls)
    answer = pipeline.ask.ask(
        db, tender, "Which pooling substation evacuates the power?", created_by="pytest"
    )
    assert (answer.mode, answer.source, answer.answered) == ("retrieval", "none", False)
    assert "No passage" in answer.answer and answer.citations == []
    assert len(pipeline.sdk.calls) == calls
