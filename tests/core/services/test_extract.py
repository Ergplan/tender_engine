from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.llm.client import LLMCallError
from core.llm.registry import UnregisteredPromptError
from core.models import AuditLog, Candidate, EvidenceSpan, ExtractionRun, Job, LLMCallLog
from core.models.extraction import REVIEWABLE_STATUSES
from core.schemas import UnknownSchemaError
from core.services.extract import ExtractionError
from tests.conftest import Pipeline
from tests.fixtures.llm import GOOD_ANSWERS, ScriptedSDK
from tests.fixtures.pdfs import PAGE_1, PAGE_2, PAGE_3, make_pdf

MakePipeline = Callable[..., Pipeline]


def candidates(db: Session, run: ExtractionRun) -> dict[str, Candidate]:
    rows = db.scalars(select(Candidate).where(Candidate.extraction_run_id == run.id))
    return {row.field_path: row for row in rows}


def spans(db: Session, candidate: Candidate) -> list[EvidenceSpan]:
    return list(db.scalars(select(EvidenceSpan).where(EvidenceSpan.candidate_id == candidate.id)))


def answers(**overrides: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {**GOOD_ANSWERS, **overrides}


def test_each_group_gets_its_own_pages_as_a_native_pdf_and_the_registered_prompt(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    calls = pipeline.sdk.extract_calls()
    assert len(calls) == 3
    for call, (group, page_no) in zip(
        calls, [("identity", 1), ("dates", 2), ("security", 3)], strict=True
    ):
        document_block, text_block = call["messages"][0]["content"]
        assert document_block["type"] == "document"
        assert document_block["source"]["media_type"] == "application/pdf"
        assert f"group `{group}`" in text_block["text"]
        assert f"attached page 1 = document page {page_no}" in text_block["text"]
        assert "verbatim" in call["system"]
    assert "Dates are day-first." in calls[1]["messages"][0]["content"][1]["text"]
    assert "unit: INR" in calls[2]["messages"][0]["content"][1]["text"]
    logs = list(db.scalars(select(LLMCallLog).where(LLMCallLog.extraction_run_id == run.id)))
    assert sorted(log.output_schema for log in logs) == [
        "test.contract:v1:dates",
        "test.contract:v1:identity",
        "test.contract:v1:security",
    ]
    assert all(log.is_fixture for log in logs)


def test_candidates_carry_value_confidence_rationale_prompt_version_and_located_evidence(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    found = candidates(db, run)
    assert set(found) == {f.path for f in pipeline.schemas.get("test.contract", "v1").fields}
    emd = found["security.emd_per_mw"]
    assert (emd.value, emd.value_type, emd.confidence) == (928000, "decimal", 0.88)
    assert (emd.prompt_name, emd.prompt_version) == ("extract", "v1")
    assert emd.rationale == "EMD clause." and emd.window_pages == [3]
    assert emd.tenant_id == "ergplan" and emd.llm_call_log_id is not None
    [span] = spans(db, emd)
    assert (span.page_no, span.stated_page_no, span.resolution) == (3, 3, "stated_page")
    assert span.match_score == 100.0 and span.document_id == run.document_id
    assert span.char_start is not None and span.char_end is not None and span.bbox is not None
    assert span.quote == "The Earnest Money Deposit shall be INR 928000 per MW"
    assert 72 <= span.bbox[0] < span.bbox[2] <= 595 and 0 < span.bbox[1] < span.bbox[3] < 842


def test_every_reviewable_candidate_has_at_least_one_evidence_span(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(
        answers(
            issuer={"value": "Acme", "confidence": 0.9, "rationale": "r", "evidence": []},
            tenure_years={"value": None, "confidence": 0, "rationale": "none", "evidence": []},
        )
    )
    run = make_pipeline(sdk).extracted_run(db)
    counts = dict(
        db.execute(
            select(Candidate.id, func.count(EvidenceSpan.id))
            .outerjoin(EvidenceSpan, EvidenceSpan.candidate_id == Candidate.id)
            .where(Candidate.extraction_run_id == run.id)
            .group_by(Candidate.id)
        ).all()
    )
    for candidate in candidates(db, run).values():
        if candidate.status in (*REVIEWABLE_STATUSES, "raw"):
            assert counts[candidate.id] >= 1, candidate.field_path
        else:
            assert candidate.status in ("not_found", "rejected") and counts[candidate.id] == 0


def test_a_null_value_becomes_a_not_found_candidate_without_evidence(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK({key: value for key, value in GOOD_ANSWERS.items() if key != "issuer"})
    run = make_pipeline(sdk).extracted_run(db)
    issuer = candidates(db, run)["identity.issuer"]
    assert (issuer.status, issuer.value, issuer.confidence) == ("not_found", None, 0.0)
    assert issuer.rationale == "Not stated on these pages." and spans(db, issuer) == []


def test_a_value_without_evidence_is_rejected_and_never_reviewable(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(
        answers(
            issuer={
                "value": "Acme",
                "confidence": 0.99,
                "rationale": "r",
                "evidence": [{"page_no": 1, "quote": "  "}],
            }
        )
    )
    pipeline = make_pipeline(sdk)
    run = pipeline.extracted_run(db)
    issuer = candidates(db, run)["identity.issuer"]
    assert issuer.status == "rejected" and spans(db, issuer) == []
    state = pipeline.review_state.for_object(db, "document", run.document_id)
    assert next(f for f in state.fields if f.field_path == "identity.issuer").candidate is None


def test_a_quote_that_cannot_be_located_caps_confidence_and_keeps_the_stated_page(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(
        answers(
            issuer={
                "value": "Acme Power Limited",
                "confidence": 0.95,
                "rationale": "r",
                "evidence": [
                    {"page_no": 1, "quote": "the issuing authority is the Acme company of Delhi"}
                ],
            }
        )
    )
    run = make_pipeline(sdk).extracted_run(db)
    issuer = candidates(db, run)["identity.issuer"]
    assert issuer.confidence == 0.3 and issuer.status == "needs_review"
    [span] = spans(db, issuer)
    assert (span.resolution, span.page_no, span.char_start, span.bbox) == (
        "unresolved",
        1,
        None,
        None,
    )
    assert span.match_score is None


def test_a_low_confidence_is_not_raised_by_the_cap(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(
        answers(
            issuer={
                "value": "X",
                "confidence": 0.1,
                "rationale": "r",
                "evidence": [{"page_no": 1, "quote": "nowhere to be found at all"}],
            }
        )
    )
    run = make_pipeline(sdk).extracted_run(db)
    assert candidates(db, run)["identity.issuer"].confidence == 0.1


def test_a_quote_on_the_wrong_page_is_found_on_an_adjacent_page(
    make_pipeline: MakePipeline, db: Session
) -> None:
    """All three pages form one window; the model cites page 1 for text that is on page 2."""
    sdk = ScriptedSDK(
        answers(
            bid_deadline={
                **GOOD_ANSWERS["bid_deadline"],
                "evidence": [
                    {"page_no": 1, "quote": "Bids must be submitted on or before 30 March 2026"}
                ],
            }
        ),
        sections=[
            {
                "start_page": 1,
                "end_page": 3,
                "heading": "All",
                "kind": "dates_and_schedule",
                "confidence": 1,
            }
        ],
    )
    run = make_pipeline(sdk).extracted_run(db)
    deadline = candidates(db, run)["dates.bid_deadline"]
    [span] = spans(db, deadline)
    assert (span.resolution, span.stated_page_no, span.page_no) == ("adjacent_page", 1, 2)
    assert deadline.confidence == 0.92 and deadline.window_pages == [1, 2, 3]


def test_a_quote_is_found_elsewhere_in_the_window_when_not_adjacent(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(
        answers(
            capacity_mw={
                **GOOD_ANSWERS["capacity_mw"],
                "evidence": [
                    {
                        "page_no": 1,
                        "quote": "total contracted capacity under this agreement is 600 MW",
                    }
                ],
            },
            emd_per_mw={
                **GOOD_ANSWERS["emd_per_mw"],
                "evidence": [
                    {"page_no": 9, "quote": "The Earnest Money Deposit shall be INR 928000 per MW"}
                ],
            },
        ),
        sections=[
            {
                "start_page": 1,
                "end_page": 3,
                "heading": "All",
                "kind": "financial_security",
                "confidence": 1,
            }
        ],
    )
    run = make_pipeline(sdk).extracted_run(db)
    found = candidates(db, run)
    [capacity] = spans(db, found["security.capacity_mw"])
    assert (capacity.resolution, capacity.stated_page_no, capacity.page_no) == ("window_page", 1, 3)
    [emd] = spans(db, found["security.emd_per_mw"])
    assert (emd.resolution, emd.page_no) == ("window_page", 3)


def test_a_window_over_the_cap_is_split_and_each_chunk_can_yield_a_candidate(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(
        sections=[
            {
                "start_page": 1,
                "end_page": 3,
                "heading": "All",
                "kind": "financial_security",
                "confidence": 1,
            }
        ]
    )
    pipeline = make_pipeline(sdk, extract_max_pages_per_call=2)
    run = pipeline.extracted_run(db)
    security_calls = [
        c
        for c in sdk.extract_calls()
        if "group `security`" in c["messages"][0]["content"][1]["text"]
    ]
    assert len(security_calls) == 2
    assert "holds 2 of its pages" in security_calls[0]["messages"][0]["content"][1]["text"]
    assert (
        "attached page 1 = document page 3"
        in security_calls[1]["messages"][0]["content"][1]["text"]
    )
    rows = list(
        db.scalars(
            select(Candidate).where(
                Candidate.extraction_run_id == run.id, Candidate.field_path == "security.emd_per_mw"
            )
        )
    )
    assert sorted(row.window_pages for row in rows) == [[1, 2], [3]]
    located = [any(s.char_start is not None for s in spans(db, row)) for row in rows]
    assert sorted(located) == [False, True]
    state = pipeline.review_state.for_object(db, "document", run.document_id)
    emd = next(f for f in state.fields if f.field_path == "security.emd_per_mw")
    assert emd.candidate is not None and emd.candidate.evidence[0].resolution == "stated_page"
    assert emd.alternative_candidates == 1


def test_run_totals_come_from_the_call_log_and_the_run_ends_validated(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    assert run.status == "validated" and run.started_at and run.finished_at
    assert (run.token_in, run.token_out) == (3000, 300)
    assert float(run.cost_usd) == pytest.approx(3000 / 1e6 * 10 + 300 / 1e6 * 50)
    assert (run.object_type, run.object_id, run.object_version) == ("document", run.document_id, 1)
    assert run.model == "claude-fable-5-1" and run.prompt_version == "v1"
    kinds = [job.kind for job in db.scalars(select(Job).order_by(Job.created_at))]
    assert kinds == ["parse", "section_map", "extract", "validate"]


def test_every_candidate_insert_is_audited(pipeline: Pipeline, db: Session) -> None:
    run = pipeline.extracted_run(db)
    ids = {c.id for c in candidates(db, run).values()}
    inserts = list(
        db.scalars(
            select(AuditLog).where(AuditLog.table_name == "candidate", AuditLog.action == "insert")
        )
    )
    assert {row.row_id for row in inserts} == ids and len(inserts) == len(ids)
    sample = next(
        row for row in inserts if row.after and row.after["field_path"] == "security.emd_per_mw"
    )
    assert sample.actor == "extraction" and sample.tenant_id == "ergplan"
    assert sample.after["value"] == 928000 and sample.after["evidence_spans"] == 1


def test_a_failed_call_is_retried_and_finished_groups_are_not_run_again(
    make_pipeline: MakePipeline, db: Session
) -> None:
    def fail_second_extract_call(number: int, kwargs: dict[str, Any]) -> None:
        if number == 3:
            request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.InternalServerError(
                "boom", response=httpx2.Response(500, request=request), body=None
            )

    sdk = ScriptedSDK(before_call=fail_second_extract_call)
    pipeline = make_pipeline(sdk)
    run = pipeline.start_run(db, pipeline.parsed_document(db))
    with pytest.raises(LLMCallError):
        pipeline.extract.extract(db, run.id)
    db.rollback()
    db.refresh(run)
    assert run.status == "running"
    assert set(candidates(db, run)) == {"identity.agreement_number", "identity.issuer"}

    sdk.before_call = None
    pipeline.extract.extract(db, run.id)
    db.refresh(run)
    assert run.status == "extracted" and len(candidates(db, run)) == 7
    groups = [
        c["messages"][0]["content"][1]["text"].split("group `")[1].split("`")[0]
        for c in sdk.extract_calls()
    ]
    assert groups == ["identity", "dates", "dates", "security"]
    assert db.scalar(select(func.count()).select_from(Candidate)) == 7
    pipeline.extract.extract(db, run.id)
    assert len(sdk.extract_calls()) == 4


def test_a_second_run_supersedes_the_first_runs_candidates(pipeline: Pipeline, db: Session) -> None:
    first = pipeline.extracted_run(db)
    document = db.get_one(type(first), first.id).document_id
    from core.models import Document

    second = pipeline.start_run(db, db.get_one(Document, document))
    pipeline.runner.run_until_idle()
    db.expire_all()
    assert {c.status for c in candidates(db, first).values()} == {"superseded"}
    assert {c.status for c in candidates(db, second).values()} == {"validated"}
    superseded = list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.action == "status_change", AuditLog.table_name == "candidate"
            )
        )
    )
    assert sum(1 for row in superseded if row.after and row.after["status"] == "superseded") == 7
    state = pipeline.review_state.for_object(db, "document", document)
    assert state.run is not None and state.run.id == second.id


def test_a_run_cannot_start_on_an_unparsed_document_or_with_unknown_schema_or_prompt(
    pipeline: Pipeline, db: Session
) -> None:
    unparsed = pipeline.upload(db, make_pdf([PAGE_1]))
    with pytest.raises(ExtractionError, match="not parsed"):
        pipeline.start_run(db, unparsed)
    document = pipeline.parsed_document(db, make_pdf([PAGE_1, PAGE_2, PAGE_3, PAGE_1]))
    kwargs = {"document_id": document.id, "created_by": "pytest"}
    with pytest.raises(UnknownSchemaError):
        pipeline.extract.start_run(
            db, schema_name="nope", schema_version="v1", prompt_version="v1", **kwargs
        )
    with pytest.raises(UnregisteredPromptError):
        pipeline.extract.start_run(
            db, schema_name="test.contract", schema_version="v1", prompt_version="v9", **kwargs
        )
    with pytest.raises(LookupError):
        pipeline.extract.start_run(
            db,
            schema_name="test.contract",
            schema_version="v1",
            prompt_version="v1",
            document_id="0" * 32,
            created_by="x",
        )
    assert db.scalar(select(func.count()).select_from(ExtractionRun)) == 0


def test_an_older_run_that_finishes_after_a_newer_one_does_not_take_over(
    pipeline: Pipeline, db: Session
) -> None:
    """Two runs queued for one object; the newer finishes first. The older one must not
    supersede it, and must not leave the object without live candidates."""
    from core.models import Document, Job

    document = pipeline.parsed_document(db)
    older = pipeline.start_run(db, db.get_one(Document, document.id))
    newer = pipeline.start_run(db, db.get_one(Document, document.id))
    assert older.created_at < newer.created_at
    for job in db.scalars(select(Job).where(Job.status == "queued")):
        job.status = "done"
    db.commit()

    pipeline.extract.extract(db, newer.id)
    pipeline.extract.extract(db, older.id)
    pipeline.runner.run_until_idle()
    db.expire_all()

    assert {c.status for c in candidates(db, older).values()} == {"superseded"}
    assert {c.status for c in candidates(db, newer).values()} == {"validated"}
    state = pipeline.review_state.for_object(db, "document", document.id)
    assert state.run is not None and state.run.id == newer.id
    assert all(field.candidate is not None for field in state.fields)
