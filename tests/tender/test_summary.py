"""The summary of a tender is written from its record, in a second pass after extraction:
every sentence inherits the evidence of the fields it draws on."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import AuditLog, Candidate, EvidenceSpan, ExtractionRun, ValidationResult
from core.services.extract import ExtractionError
from core.services.review_state import EvidenceView
from tender.services.summary import (
    HEADINGS,
    SUMMARY_FIELD,
    RecordSummary,
    Source,
    SummaryError,
    compose,
    narrative_sources,
)
from tender.services.worker_jobs import summary_writer
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE, EMD, amended_tender, extracted_tender


def span(page: int, start: int, ordinal: int | None = None, document: str = "d1") -> EvidenceView:
    return EvidenceView(
        id=f"e-{document}-{page}-{start}",
        document_id=document,
        page_no=page,
        bbox=[1.0, 2.0, 3.0, 4.0],
        char_start=start,
        char_end=start + 10,
        quote=f"quote at {page}:{start}",
        resolution="stated_page",
        match_score=100.0,
        match_method="exact",
        ordinal=ordinal,
    )


def summary(told: dict[str, list[tuple[str, list[str]]]]) -> RecordSummary:
    return RecordSummary.model_validate(
        {
            "paragraphs": [
                {
                    "heading": heading,
                    "sentences": [
                        {"text": text, "sources": sources}
                        for text, sources in told.get(
                            heading, [("The record does not state this.", [])]
                        )
                    ],
                }
                for heading in HEADINGS
            ],
            "confidence": 0.9,
            "rationale": "r",
        }
    )


SOURCES = {
    "F1": Source("F1", "", "Total capacity", [span(1, 10)]),
    "F2": Source("F2", "", "EMD per MW", [span(3, 5), span(3, 50)]),
    "F3": Source("F3", "", "PBG per MW", [span(3, 50)]),
    "N1": Source("N1", "", "page summary, what is procured", [span(1, 10), span(2, 7)]),
}


def test_each_sentence_gets_the_numbers_of_the_evidence_its_sources_bring() -> None:
    text, spans, drawn, unknown = compose(
        summary(
            {
                "What is procured": [("Acme buys 600 MW [9] .", ["N1", "F1"])],
                "Money at risk": [
                    ("The EMD is 9.28 lakh per MW.", ["F2"]),
                    ("So is the PBG.", ["F3"]),
                ],
            }
        ),
        SOURCES,
    )
    paragraphs = text.split("\n\n")
    assert len(paragraphs) == 8
    # Markers the model wrote itself are removed; ours follow the sentence.
    assert paragraphs[0] == "What is procured: Acme buys 600 MW . [1][2]"
    assert paragraphs[5] == "Money at risk: The EMD is 9.28 lakh per MW. [3][4] So is the PBG. [4]"
    assert paragraphs[4] == "Eligibility: The record does not state this."
    # A passage two sources share is one span with one number.
    assert [(s["ordinal"], s["page_no"], s["char_start"]) for s in spans] == [
        (1, 1, 10),
        (2, 2, 7),
        (3, 3, 5),
        (4, 3, 50),
    ]
    assert all(s["document_id"] == "d1" and s["quote"] and s["bbox"] for s in spans)
    assert drawn == [
        ("page summary, what is procured", [1, 2]),
        ("Total capacity", [1]),
        ("EMD per MW", [3, 4]),
        ("PBG per MW", [4]),
    ]
    assert unknown == []


def test_a_source_that_does_not_exist_is_reported_and_brings_no_evidence() -> None:
    text, spans, _, unknown = compose(
        summary({"Timeline": [("Bids are due in March.", ["F99", "F1"])]}), SOURCES
    )
    assert unknown == ["F99"] and len(spans) == 1
    assert "Timeline: Bids are due in March. [1]" in text


def test_a_summary_that_is_not_the_eight_paragraphs_or_has_no_evidence_is_refused() -> None:
    wrong = summary({})
    wrong.paragraphs = wrong.paragraphs[:7]
    with pytest.raises(SummaryError, match="expected the headings"):
        compose(wrong, SOURCES)
    with pytest.raises(SummaryError, match="names a source"):
        compose(summary({}), SOURCES)


def test_narrative_sentences_come_from_the_first_three_topics_with_their_quotes() -> None:
    text = (
        "What is procured: Acme invites bids for 600 MW [1]. Each bidder may offer 50 MW "
        "to 300 MW [2][3]. A closing remark without a quote.\n\n"
        "Buyer and offtaker: Acme signs the PPA. [4]\n\n"
        "Location: Not stated on these pages.\n\n"
        "Money at risk: The EMD is INR 9.28 lakh per MW. [5]"
    )
    spans = [span(1, 10, 1), span(1, 40, 2), span(2, 5, 3), span(1, 70, 4), span(3, 5, 5)]
    spans[2].char_start = None  # the third quote was not located
    sources = narrative_sources(text, spans)
    assert [(s.id, s.line) for s in sources] == [
        ("N1", "What is procured | Acme invites bids for 600 MW."),
        ("N2", "What is procured | Each bidder may offer 50 MW to 300 MW."),
        ("N3", "Buyer and offtaker | Acme signs the PPA."),
    ]
    assert [[e.char_start for e in s.spans] for s in sources] == [[10], [40], [70]]


def live_summary(
    db: Session, tender_id: str
) -> tuple[Candidate, ExtractionRun, list[EvidenceSpan]]:
    candidate, run = db.execute(
        select(Candidate, ExtractionRun)
        .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
        .where(
            ExtractionRun.object_id == tender_id,
            Candidate.field_path == SUMMARY_FIELD,
            Candidate.status.in_(("validated", "needs_review")),
        )
    ).one()
    spans = list(
        db.scalars(
            select(EvidenceSpan)
            .where(EvidenceSpan.candidate_id == candidate.id)
            .order_by(EvidenceSpan.ordinal)
        )
    )
    return candidate, run, spans


def test_after_extraction_the_summary_is_written_from_the_fields_without_a_document(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    candidate, run, spans = live_summary(db, tender.id)

    assert (run.mode, run.status, run.object_version, run.groups) == (
        "record",
        "validated",
        1,
        ["summary"],
    )
    assert (candidate.prompt_name, candidate.prompt_version) == ("summary_record", "v1")
    assert candidate.status == "validated" and candidate.window_pages == []
    assert run.token_in > 0 and run.cost_usd > 0

    # One call, text only: the fields of the record and the narrative sentences.
    (call,) = pipeline.sdk.summary_calls()
    blocks = call["messages"][0]["content"]
    assert [block["type"] for block in blocks] == ["text"]
    sent = blocks[0]["text"]
    assert (
        "F7 | Guarantees | EMD per MW (INR per MW) | 928000 (that is INR 9.28 lakh) | "
        "original tender" in sent
    )
    assert "| Key dates | Bid submission deadline | 30.03.2026 | original tender" in sent
    assert "N1 | What is procured | Acme Renewables Agency invites solar developers" in sent
    assert "plain_english_summary" not in sent and "Plain-English summary" not in sent
    assert "Money at risk | The earnest money deposit" not in sent, "only narrative topics"
    assert "You are not reading the tender" in call["system"]

    # Every span is a located copy of a field's span.
    emd = db.scalars(
        select(EvidenceSpan)
        .join(Candidate, EvidenceSpan.candidate_id == Candidate.id)
        .where(Candidate.field_path == EMD)
    ).one()
    assert [s.ordinal for s in spans] == [1, 2, 3]
    copy = spans[-1]
    assert (copy.document_id, copy.page_no, copy.char_start, copy.char_end, copy.quote) == (
        emd.document_id, emd.page_no, emd.char_start, emd.char_end, emd.quote,
    )  # fmt: skip
    assert (
        "Money at risk: The earnest money deposit is as the record gives it. [3]" in candidate.value
    )
    assert (
        "[3] EMD per MW" in candidate.rationale
        and "Written from the extracted fields" in candidate.rationale
    )
    rules = {
        r.rule_name: r.passed
        for r in db.scalars(
            select(ValidationResult).where(ValidationResult.candidate_id == candidate.id)
        )
    }
    assert rules["evidence_located"] is True and rules["type"] is True

    # The summary read from the pages has left review, with an audit line.
    page_read = list(
        db.scalars(
            select(Candidate).where(
                Candidate.field_path == SUMMARY_FIELD, Candidate.prompt_name == "summary"
            )
        )
    )
    assert page_read and all(row.status == "superseded" for row in page_read)
    changes = db.scalars(
        select(AuditLog).where(
            AuditLog.row_id == page_read[0].id, AuditLog.action == "status_change"
        )
    )
    assert {"status": "superseded", "superseded_by_run": run.id} in [row.after for row in changes]
    inserted = db.scalars(
        select(AuditLog).where(AuditLog.row_id == candidate.id, AuditLog.action == "insert")
    ).one()
    assert inserted.after is not None and inserted.after["evidence_spans"] == 3


def test_after_an_amendment_the_summary_is_written_again_from_the_record_as_amended(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    first, _, _ = live_summary(db, tender.id)
    amended_tender(pipeline, db, tender)
    candidate, run, spans = live_summary(db, tender.id)

    assert candidate.id != first.id and run.object_version == 2 and run.mode == "record"
    db.refresh(first)
    assert first.status == "superseded"
    sent = pipeline.sdk.summary_calls()[-1]["messages"][0]["content"][0]["text"]
    assert (
        "Bid submission deadline | 15.04.2026 | current value, from version 2 (amendment)" in sent
    )
    # The deadline's evidence is the amendment's; the EMD's is still the RfS's.
    amendment = db.scalars(
        select(EvidenceSpan.document_id)
        .join(Candidate, EvidenceSpan.candidate_id == Candidate.id)
        .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
        .where(Candidate.field_path == DEADLINE, ExtractionRun.object_version == 2)
    ).one()
    assert amendment in {s.document_id for s in spans} and len({s.document_id for s in spans}) == 2
    # A value written from the record is not held to the rule that a later version's
    # value must be evidenced in that version's own document.
    assert candidate.status == "validated"
    rules = {
        r.rule_name
        for r in db.scalars(
            select(ValidationResult).where(ValidationResult.candidate_id == candidate.id)
        )
    }
    assert "later_version_evidence" not in rules


def test_the_summary_is_not_written_twice_from_the_same_record_and_follows_an_edit(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    writer = summary_writer(
        pipeline.llm,
        pipeline.catalog,
        pipeline.extract,
        pipeline.schemas,
        pipeline.settings.tenant_id,
    )
    assert writer.write(db, tender.id, is_fixture=True) is None
    assert len(pipeline.sdk.summary_calls()) == 1

    # A reviewer corrects the EMD: the record has changed, and the summary reads the
    # reviewer's value.
    emd = db.scalars(select(Candidate).where(Candidate.field_path == EMD)).one()
    pipeline.approvals.approve(
        db, candidate_id=emd.id, decision="edited", final_value=1000000, reviewer="Asha"
    )
    run = writer.write(db, tender.id, is_fixture=True)
    assert run is not None and run.status == "extracted"
    sent = pipeline.sdk.summary_calls()[-1]["messages"][0]["content"][0]["text"]
    assert "EMD per MW (INR per MW) | 1000000 (that is INR 10 lakh) | original tender" in sent
    pipeline.runner.run_until_idle()
    assert live_summary(db, tender.id)[1].id == run.id


def test_a_summary_the_model_gets_wrong_stores_nothing_and_leaves_the_earlier_one(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    before, _, _ = live_summary(db, tender.id)
    emd = db.scalars(select(Candidate).where(Candidate.field_path == EMD)).one()
    pipeline.approvals.approve(
        db, candidate_id=emd.id, decision="edited", final_value=1000000, reviewer="Asha"
    )
    original = pipeline.sdk.record_summary

    def no_sources(params: dict[str, Any]) -> dict[str, Any]:
        answer = original(params)
        for paragraph in answer["paragraphs"]:
            for sentence in paragraph["sentences"]:
                sentence["sources"] = []
        return answer

    pipeline.sdk.record_summary = no_sources  # type: ignore[method-assign]
    writer = summary_writer(
        pipeline.llm,
        pipeline.catalog,
        pipeline.extract,
        pipeline.schemas,
        pipeline.settings.tenant_id,
    )
    with pytest.raises(SummaryError):
        writer.write(db, tender.id, is_fixture=True)
    db.rollback()
    # Nothing is stored but the call: no run, and the earlier summary is still in review.
    runs = list(db.scalars(select(ExtractionRun).where(ExtractionRun.mode == "record")))
    assert [run.status for run in runs] == ["validated"]
    assert live_summary(db, tender.id)[0].id == before.id


def test_only_a_record_run_takes_a_candidate_from_the_record_and_only_with_located_evidence(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    _, record_run, spans = live_summary(db, tender.id)
    page_run = db.scalars(select(ExtractionRun).where(ExtractionRun.mode != "record")).first()
    assert page_run is not None
    good = {
        "document_id": spans[0].document_id, "page_no": 1, "stated_page_no": 1, "bbox": None,
        "char_start": 0, "char_end": 5, "quote": "q", "resolution": "stated_page",
        "match_score": 100.0, "match_method": "exact", "ordinal": 1,
    }  # fmt: skip
    common: dict[str, Any] = {
        "value": "x", "confidence": 0.5, "rationale": "r", "call_log_id": None,
        "prompt_name": "summary_record", "prompt_version": "v1",
    }  # fmt: skip
    with pytest.raises(ExtractionError, match="only a record run"):
        pipeline.extract.record_candidate(db, page_run, SUMMARY_FIELD, spans=[good], **common)
    with pytest.raises(ExtractionError, match="located evidence"):
        pipeline.extract.record_candidate(db, record_run, SUMMARY_FIELD, spans=[], **common)
    with pytest.raises(ExtractionError, match="located evidence"):
        pipeline.extract.record_candidate(
            db, record_run, SUMMARY_FIELD, spans=[{**good, "char_start": None}], **common
        )


def test_amounts_are_also_given_the_way_tenders_write_them() -> None:
    from tender.services.summary import rupees

    assert rupees(13000000) == "INR 1.3 crore"
    assert rupees(928000) == "INR 9.28 lakh"
    assert rupees(100000000) == "INR 10 crore"
    assert rupees(59000) == "INR 59,000"
    assert rupees(0.02) == "INR 0.02"


def test_a_field_the_reviewer_corrected_brings_the_reviewers_evidence_to_the_summary(
    pipeline: Pipeline, db: Session
) -> None:
    """The corrected value must not be summarised against the quote of the value it
    replaced; and a field the model could not evidence joins the summary once a reviewer
    has given the page and the words."""
    tender = extracted_tender(pipeline, db)
    writer = summary_writer(
        pipeline.llm,
        pipeline.catalog,
        pipeline.extract,
        pipeline.schemas,
        pipeline.settings.tenant_id,
    )
    emd = db.scalars(select(Candidate).where(Candidate.field_path == EMD)).one()
    quote = "Performance Bank Guarantee (PBG) of INR 2320000 per MW"
    pipeline.approvals.approve(
        db,
        candidate_id=emd.id,
        decision="edited",
        final_value=2320000,
        reviewer="Asha",
        evidence=[{"page_no": 3, "quote": quote}],
    )
    # A field the model left empty, filled by the reviewer with evidence.
    empty = db.scalars(
        select(Candidate).where(Candidate.field_path == "core.identity.portal")
    ).one()
    assert empty.value is None
    pipeline.approvals.approve(
        db,
        candidate_id=empty.id,
        decision="edited",
        final_value="Acme e-tender portal",
        reviewer="Asha",
        evidence=[{"page_no": 1, "quote": "Issued by Acme Renewables Agency"}],
    )

    run = writer.write(db, tender.id, is_fixture=True)
    assert run is not None
    sent = pipeline.sdk.summary_calls()[-1]["messages"][0]["content"][0]["text"]
    assert "EMD per MW (INR per MW) | 2320000 (that is INR 23.2 lakh) | original tender" in sent
    assert "| Acme e-tender portal | original tender" in sent
    pipeline.runner.run_until_idle()
    candidate, _, spans = live_summary(db, tender.id)
    inherited = next(span for span in spans if span.page_no == 3)
    assert inherited.quote == quote and inherited.char_start is not None
    original = db.scalars(select(EvidenceSpan).where(EvidenceSpan.candidate_id == emd.id)).one()
    assert inherited.char_start != original.char_start, "not the quote of the value it replaced"
    assert candidate.status == "validated"
