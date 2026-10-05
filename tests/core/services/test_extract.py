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


def test_a_run_limited_to_groups_extracts_only_those_groups(
    pipeline: Pipeline, db: Session
) -> None:
    document = pipeline.parsed_document(db)
    run = pipeline.start_run(db, document, groups=["dates"])
    pipeline.runner.run_until_idle()
    db.refresh(run)
    assert run.status == "validated" and run.groups == ["dates"]
    assert len(pipeline.sdk.extract_calls()) == 1
    assert sorted(candidates(db, run)) == ["dates.bid_deadline", "dates.pre_bid_date"]
    with pytest.raises(ExtractionError, match="no group"):
        pipeline.start_run(db, document, groups=["nope"])
    with pytest.raises(ExtractionError, match="no group"):
        pipeline.start_run(db, document, groups=[])


def test_a_later_run_supersedes_only_the_fields_it_covers(pipeline: Pipeline, db: Session) -> None:
    full = pipeline.extracted_run(db)
    from core.models import Document

    partial = pipeline.start_run(db, db.get_one(Document, full.document_id), groups=["dates"])
    pipeline.runner.run_until_idle()
    db.expire_all()
    statuses = {path: c.status for path, c in candidates(db, full).items()}
    assert {path for path, status in statuses.items() if status == "superseded"} == {
        "dates.bid_deadline",
        "dates.pre_bid_date",
    }
    assert {c.status for c in candidates(db, partial).values()} == {"validated"}
    state = pipeline.review_state.for_object(db, "document", full.document_id)
    assert [r.id for r in state.runs] == [partial.id, full.id]
    live = {f.field_path: f.candidate.id for f in state.fields if f.candidate}
    assert len(live) == 7
    assert live["dates.bid_deadline"] == candidates(db, partial)["dates.bid_deadline"].id
    assert live["security.emd_per_mw"] == candidates(db, full)["security.emd_per_mw"].id


def test_runs_on_two_documents_of_one_object_keep_both_documents_candidates(
    pipeline: Pipeline, db: Session
) -> None:
    """An object version may hold several documents: a run on one of them leaves the
    candidates from the other alone, and review state reads across both."""
    first = pipeline.parsed_document(db)
    second = pipeline.parsed_document(db, make_pdf([PAGE_1, PAGE_2, PAGE_3, ["Appendix"]]))
    run_a = pipeline.start_run(db, first, object_type="thing", object_id="a" * 32)
    pipeline.runner.run_until_idle()
    run_b = pipeline.start_run(
        db, second, object_type="thing", object_id="a" * 32, groups=["security"]
    )
    pipeline.runner.run_until_idle()
    db.expire_all()
    assert {c.status for c in candidates(db, run_a).values()} == {"validated"}
    assert {c.status for c in candidates(db, run_b).values()} == {"validated"}
    state = pipeline.review_state.for_object(db, "thing", "a" * 32)
    emd = next(f for f in state.fields if f.field_path == "security.emd_per_mw")
    assert emd.candidate is not None and emd.alternative_candidates == 1
    assert emd.candidate.document_id in (first.id, second.id)
    assert {r.document_id for r in state.runs} == {first.id, second.id}
    issuer = next(f for f in state.fields if f.field_path == "identity.issuer")
    assert issuer.candidate is not None and issuer.candidate.document_id == first.id
    assert issuer.alternative_candidates == 0


ONE_SECTION = [
    {
        "start_page": 1,
        "end_page": 3,
        "heading": "Agreement no, key dates and security",
        "kind": "other",
        "confidence": 1,
    }
]


def group_of(call: dict[str, Any]) -> str:
    text: str = call["messages"][0]["content"][-1]["text"]
    return text.split("group `")[1].split("`")[0]


def test_groups_with_the_same_pages_share_one_cached_window(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(sections=ONE_SECTION)
    pipeline = make_pipeline(sdk)
    run = pipeline.extracted_run(db)

    calls = sdk.extract_calls()
    assert [group_of(call) for call in calls] == ["identity", "dates", "security"]
    documents = [call["messages"][0]["content"][0] for call in calls]
    assert all(block["cache_control"] == {"type": "ephemeral"} for block in documents)
    assert len({block["source"]["data"] for block in documents}) == 1
    assert len({call["system"] for call in calls}) == 1
    # One output schema for the whole window, or the cached prefix would differ per call.
    assert {call["output_format"].__name__ for call in calls} == {"SharedAnswer"}
    assert all(
        "Return one entry in `fields`" in call["messages"][0]["content"][-1]["text"]
        for call in calls
    )
    logs = list(
        db.scalars(
            select(LLMCallLog)
            .where(LLMCallLog.extraction_run_id == run.id)
            .order_by(LLMCallLog.created_at)
        )
    )
    assert [(log.cache_write_tokens, log.cache_read_tokens) for log in logs] == [
        (800, 0),
        (0, 800),
        (0, 800),
    ]
    assert (run.token_in, run.token_cached, run.token_out) == (3000, 1600, 300)
    expected = (600 * 10 + 800 * 12.5 + 1600 * 0.25 + 300 * 50) / 1e6
    assert float(run.cost_usd) == pytest.approx(expected, abs=1e-4)
    rows = candidates(db, run)
    assert len(rows) == 7 and run.status == "validated"
    assert all(row.window_pages == [1, 2, 3] for row in rows.values())
    assert all(any(s.char_start is not None for s in spans(db, row)) for row in rows.values())


def test_windows_are_not_shared_when_sharing_is_switched_off(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(sections=ONE_SECTION)
    pipeline = make_pipeline(sdk, extract_share_windows=False)
    run = pipeline.extracted_run(db)
    assert all(
        "cache_control" not in call["messages"][0]["content"][0] for call in sdk.extract_calls()
    )
    assert (run.token_in, run.token_cached) == (3000, 0)


def test_an_interrupted_run_reads_the_calls_it_already_paid_for_from_the_log(
    make_pipeline: MakePipeline, db: Session
) -> None:
    def fail_second_extract_call(number: int, kwargs: dict[str, Any]) -> None:
        if number == 3:
            request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.InternalServerError(
                "boom", response=httpx2.Response(500, request=request), body=None
            )

    sdk = ScriptedSDK(sections=ONE_SECTION, before_call=fail_second_extract_call)
    pipeline = make_pipeline(sdk)
    run = pipeline.start_run(db, pipeline.parsed_document(db))
    with pytest.raises(LLMCallError):
        pipeline.extract.extract(db, run.id)
    db.rollback()
    assert candidates(db, run) == {}  # a shared window is committed as a whole

    sdk.before_call = None
    pipeline.extract.extract(db, run.id)
    assert [group_of(call) for call in sdk.extract_calls()] == [
        "identity",
        "dates",
        "dates",
        "security",
    ]
    assert len(candidates(db, run)) == 7
    identity = candidates(db, run)["identity.issuer"]
    first_ok = db.scalars(
        select(LLMCallLog)
        .where(LLMCallLog.extraction_run_id == run.id, LLMCallLog.status == "ok")
        .order_by(LLMCallLog.created_at)
    ).first()
    assert first_ok is not None and identity.llm_call_log_id == first_ok.id


def test_a_batch_run_sends_the_cache_writer_first_and_the_readers_second(
    make_pipeline: MakePipeline, db: Session
) -> None:
    from core.models import LLMBatch

    sdk = ScriptedSDK(sections=ONE_SECTION)
    sdk.batch_polls = 1
    pipeline = make_pipeline(sdk, llm_batch_poll_seconds=0)
    run = pipeline.start_run(db, pipeline.parsed_document(db), mode="batch")
    pipeline.runner.run_until_idle()
    db.refresh(run)

    assert sdk.extract_calls() == []  # nothing was called directly
    batches = list(db.scalars(select(LLMBatch).order_by(LLMBatch.wave)))
    assert [(b.wave, b.request_count, b.status) for b in batches] == [
        (1, 1, "collected"),
        (2, 2, "collected"),
    ]
    first, second = (sdk.submitted[b.provider_batch_id] for b in batches)
    document = first[0]["params"]["messages"][0]["content"][0]
    assert document["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert all(
        r["params"]["messages"][0]["content"][0]["source"] == document["source"] for r in second
    )
    logs = list(db.scalars(select(LLMCallLog).where(LLMCallLog.extraction_run_id == run.id)))
    assert len(logs) == 3 and all(log.mode == "batch" and log.batch_id for log in logs)
    assert sorted(log.cache_read_tokens for log in logs) == [0, 800, 800]
    assert run.status == "validated" and run.mode == "batch"
    assert len(candidates(db, run)) == 7
    # Half the price of the same run made with direct calls and a five-minute cache write.
    assert float(run.cost_usd) == pytest.approx(
        (600 * 10 + 800 * 20 + 1600 * 0.25 + 300 * 50) / 1e6 / 2, abs=1e-4
    )
    extract_jobs = list(db.scalars(select(Job).where(Job.kind == "extract")))
    assert len(extract_jobs) >= 3 and all(job.status == "done" for job in extract_jobs)


def test_a_call_that_fails_inside_a_batch_is_made_directly(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(sections=ONE_SECTION)
    pipeline = make_pipeline(sdk, llm_batch_poll_seconds=0)
    run = pipeline.start_run(db, pipeline.parsed_document(db), mode="batch")
    assert pipeline.runner.run_once()  # submits the first wave
    [first] = sdk.submitted.values()
    sdk.batch_failures = {first[0]["custom_id"]}
    pipeline.runner.run_until_idle()
    db.refresh(run)

    assert [group_of(call) for call in sdk.extract_calls()] == ["identity"]
    statuses = sorted(
        (log.mode, log.status)
        for log in db.scalars(select(LLMCallLog).where(LLMCallLog.extraction_run_id == run.id))
    )
    assert statuses == [("batch", "error"), ("batch", "ok"), ("batch", "ok"), ("sync", "ok")]
    assert run.status == "validated" and len(candidates(db, run)) == 7


def test_a_run_mode_other_than_sync_or_batch_is_refused(pipeline: Pipeline, db: Session) -> None:
    with pytest.raises(ExtractionError):
        pipeline.start_run(db, pipeline.parsed_document(db), mode="later")


def test_the_same_pages_always_give_the_same_pdf_bytes() -> None:
    import time

    import pymupdf

    from core.services.extract import _sub_pdf

    with pymupdf.open(stream=make_pdf(), filetype="pdf") as source:
        first = _sub_pdf(source, [1, 3])
        time.sleep(1.1)  # a file id made from the clock would differ by now
        assert _sub_pdf(source, [1, 3]) == first
        assert _sub_pdf(source, [1, 2]) != first


def test_a_shared_window_answer_that_is_not_complete_is_asked_again_with_the_typed_model(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(sections=ONE_SECTION)
    sdk.empty_entries = {"dates"}
    pipeline = make_pipeline(sdk)
    run = pipeline.extracted_run(db)

    calls = sdk.extract_calls()
    assert [(group_of(c), c["output_format"].__name__) for c in calls] == [
        ("identity", "SharedAnswer"),
        ("dates", "SharedAnswer"),
        ("dates", "Extract_dates"),
        ("security", "SharedAnswer"),
    ]
    alone = calls[2]
    assert "cache_control" not in alone["messages"][0]["content"][0]
    assert "Return one entry in `fields`" not in alone["messages"][0]["content"][-1]["text"]
    rows = candidates(db, run)
    assert len(rows) == 7 and rows["dates.bid_deadline"].value == "2026-03-30"
    assert run.status == "validated"


def test_a_shared_answer_passes_only_as_a_complete_typed_answer_of_the_group() -> None:
    from core.services.extract import SharedAnswer, build_group_model, typed_answer
    from tests.fixtures.schemas import contract_schema, make_registry

    schema = contract_schema()
    model = build_group_model(schema, schema.groups[2], make_registry())  # security

    def entry(key: str, value: Any) -> dict[str, Any]:
        return {"key": key, "value": value, "confidence": 0.9, "rationale": "r", "evidence": []}

    good = [entry("emd_per_mw", 928000), entry("capacity_mw", 600.0), entry("tenure_years", None)]
    typed = typed_answer(SharedAnswer.model_validate({"fields": good}), model)
    assert typed is not None
    assert typed.emd_per_mw.value == 928000 and typed.tenure_years.value is None  # type: ignore[attr-defined]

    extra = typed_answer(SharedAnswer.model_validate({"fields": [*good, entry("x", 1)]}), model)
    assert extra == typed, "an entry that is no field of the group is dropped"

    for bad in (
        good[:2],  # a field missing
        [*good, entry("emd_per_mw", 1)],  # a field twice
        [*good[:2], entry("tenure", 25)],  # a field under another name
        [*good[:2], entry("tenure_years", "twenty-five")],  # the wrong kind of value
        [*good[:2], entry("tenure_years", ["25"])],
    ):
        assert typed_answer(SharedAnswer.model_validate({"fields": bad}), model) is None
