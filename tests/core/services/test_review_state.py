from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Candidate
from tests.conftest import Pipeline
from tests.fixtures.llm import GOOD_ANSWERS, ScriptedSDK
from tests.fixtures.schemas import SCHEMA_NAME, SCHEMA_VERSION

MakePipeline = Callable[..., Pipeline]


def test_state_of_an_object_without_a_run_is_empty(pipeline: Pipeline, db: Session) -> None:
    state = pipeline.review_state.for_object(db, "document", "0" * 32)
    assert state.run is None and state.fields == [] and (state.decided, state.total) == (0, 0)


def test_every_schema_field_appears_in_review_order_with_candidate_evidence_and_validation(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    state = pipeline.review_state.for_object(db, "document", run.document_id)
    assert state.run is not None and (state.run.id, state.run.status) == (run.id, "validated")
    assert [f.field_path for f in state.fields] == [
        "identity.agreement_number",
        "identity.issuer",
        "dates.pre_bid_date",
        "dates.bid_deadline",
        "security.emd_per_mw",
        "security.capacity_mw",
        "security.tenure_years",
    ]
    assert (state.decided, state.total, state.required_undecided) == (0, 7, 3)
    emd = state.fields[4]
    assert (emd.label, emd.group, emd.value_type, emd.unit, emd.required) == (
        "EMD per MW", "security", "decimal", "INR", False,
    )  # fmt: skip
    assert emd.candidate is not None and emd.approval is None
    assert (emd.candidate.value, emd.candidate.confidence, emd.candidate.status) == (
        928000,
        0.88,
        "validated",
    )
    assert emd.candidate.prompt_version == "v1"
    [evidence] = emd.candidate.evidence
    assert (
        evidence.page_no == 3 and evidence.bbox is not None and evidence.resolution == "stated_page"
    )
    assert {v.rule_name for v in emd.candidate.validation} == {"evidence_located", "type", "range"}


def test_decisions_show_on_the_field_and_drive_the_progress_counts(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK({k: v for k, v in GOOD_ANSWERS.items() if k != "issuer"})
    pipeline = make_pipeline(sdk)
    run = pipeline.extracted_run(db)
    by_path = {
        c.field_path: c.id
        for c in db.scalars(select(Candidate).where(Candidate.extraction_run_id == run.id))
    }
    approve = pipeline.approvals.approve
    approve(
        db, candidate_id=by_path["identity.agreement_number"], decision="approved", reviewer="Asha"
    )
    approve(
        db, candidate_id=by_path["identity.issuer"], decision="not_in_document", reviewer="Asha"
    )
    approve(db, candidate_id=by_path["dates.bid_deadline"], decision="rejected", reviewer="Asha")

    state = pipeline.review_state.for_object(db, "document", run.document_id, version=1)
    fields = {f.field_path: f for f in state.fields}
    assert (state.decided, state.total, state.required_undecided) == (2, 7, 2)
    number = fields["identity.agreement_number"].approval
    assert number is not None and (number.decision, number.final_value, number.reviewer) == (
        "approved", "ACME/2026/001", "Asha",
    )  # fmt: skip
    issuer = fields["identity.issuer"]
    assert issuer.candidate is not None and issuer.candidate.status == "not_found"
    assert issuer.approval is not None and issuer.approval.decision == "not_in_document"
    assert fields["dates.bid_deadline"].approval is not None
    assert fields["security.emd_per_mw"].approval is None

    facts = pipeline.review_state.canonical(db, "document", run.document_id)
    assert [(f.field_path, f.value) for f in facts] == [
        ("identity.agreement_number", "ACME/2026/001"),
        ("identity.issuer", None),
    ]
    assert pipeline.review_state.canonical(db, "document", run.document_id, version=2) == []


def test_a_newer_run_that_has_not_finished_does_not_hide_the_validated_one(
    pipeline: Pipeline, db: Session
) -> None:
    from core.models import Document, ExtractionRun

    run = pipeline.extracted_run(db)
    document = db.get_one(Document, run.document_id)
    queued = pipeline.start_run(db, document)
    state = pipeline.review_state.for_object(db, "document", document.id)
    assert state.run is not None and state.run.id == run.id
    assert all(field.candidate is not None for field in state.fields)

    db.get_one(ExtractionRun, queued.id).status = "failed"
    db.commit()
    state = pipeline.review_state.for_object(db, "document", document.id)
    assert state.run is not None and state.run.id == run.id


def test_of_two_equally_confident_candidates_the_one_with_more_located_quotes_is_shown() -> None:
    from types import SimpleNamespace
    from typing import Any, cast

    from core.services.review_state import _best

    def candidate(name: str) -> Candidate:
        return cast(Candidate, SimpleNamespace(id=name, status="validated", confidence=0.7))

    def spans(*located: bool) -> list[Any]:
        return [SimpleNamespace(char_start=0 if found else None) for found in located]

    thin, full = candidate("z-thin"), candidate("a-full")
    evidence = {"z-thin": spans(True, False), "a-full": spans(True, True, True)}
    assert _best([thin, full], cast(Any, evidence)) is full
    # Confidence still comes first.
    thin.confidence = 0.8
    assert _best([thin, full], cast(Any, evidence)) is thin


def _run_security_under(pipeline: Pipeline, db: Session, document_id: str, version: str) -> str:
    run = pipeline.extract.start_run(
        db,
        document_id=document_id,
        schema_name=SCHEMA_NAME,
        schema_version=version,
        prompt_version="v1",
        created_by="pytest",
        is_fixture=True,
        groups=["security"],
    )
    pipeline.runner.run_until_idle()
    return run.id


def test_runs_of_an_earlier_schema_version_are_read_under_a_later_one_that_only_adds(
    pipeline: Pipeline, db: Session
) -> None:
    """A later version registered with the same content reads the earlier version's runs:
    a section that was not read again keeps its fields in the review."""
    first = pipeline.extracted_run(db)
    schema = pipeline.schemas.get(SCHEMA_NAME, SCHEMA_VERSION)
    pipeline.schemas.register(schema.model_copy(update={"version": "v2"}))
    assert pipeline.schemas.versions_read_as(SCHEMA_NAME, "v2") == {"v1", "v2"}
    second = _run_security_under(pipeline, db, first.document_id, "v2")

    state = pipeline.review_state.for_object(db, "document", first.document_id)
    assert state.run is not None and state.run.id == second
    by_path = {field.field_path: field for field in state.fields}
    assert all(f.candidate is not None and f.candidate.value is not None for f in state.fields)
    assert len(by_path) == 7
    # The section read again shows the new run's candidate; the others the first run's.
    run_of = dict(db.execute(select(Candidate.id, Candidate.extraction_run_id)).all())
    assert run_of[by_path["security.emd_per_mw"].candidate.id] == second  # type: ignore[union-attr]
    assert run_of[by_path["dates.bid_deadline"].candidate.id] == first.id  # type: ignore[union-attr]
    assert run_of[by_path["identity.issuer"].candidate.id] == first.id  # type: ignore[union-attr]


def test_runs_of_a_schema_version_with_other_fields_are_not_mixed_in(
    pipeline: Pipeline, db: Session
) -> None:
    first = pipeline.extracted_run(db)
    schema = pipeline.schemas.get(SCHEMA_NAME, SCHEMA_VERSION)
    changed = schema.model_copy(
        update={
            "version": "v3",
            "fields": [f for f in schema.fields if f.path != "identity.issuer"],
        }
    )
    pipeline.schemas.register(changed)
    assert pipeline.schemas.versions_read_as(SCHEMA_NAME, "v3") == {"v3"}
    assert pipeline.schemas.versions_read_as(SCHEMA_NAME, "v1") == {"v1"}
    _run_security_under(pipeline, db, first.document_id, "v3")

    state = pipeline.review_state.for_object(db, "document", first.document_id)
    with_candidate = {f.field_path for f in state.fields if f.candidate is not None}
    assert with_candidate == {
        "security.emd_per_mw",
        "security.capacity_mw",
        "security.tenure_years",
    }
    assert "identity.issuer" not in {f.field_path for f in state.fields}


def test_a_field_the_later_version_changed_is_not_read_from_the_earlier_versions_run(
    pipeline: Pipeline, db: Session
) -> None:
    """The later version reads the earlier one except for a field it redefined: that field's
    earlier candidate is left out even though it is still live."""
    first = pipeline.extracted_run(db)
    schema = pipeline.schemas.get(SCHEMA_NAME, SCHEMA_VERSION)
    pipeline.schemas.register(schema.model_copy(update={"version": "v2"}))
    pipeline.schemas.exclude_fields(SCHEMA_NAME, SCHEMA_VERSION, ("identity.issuer",))
    assert pipeline.schemas.excluded_fields(SCHEMA_NAME, "v2") == frozenset()
    _run_security_under(pipeline, db, first.document_id, "v2")

    state = pipeline.review_state.for_object(db, "document", first.document_id)
    by_path = {field.field_path: field for field in state.fields}
    assert by_path["identity.issuer"].candidate is None
    assert by_path["identity.agreement_number"].candidate is not None
    assert by_path["dates.bid_deadline"].candidate is not None
    live = db.scalar(
        select(Candidate.status).where(
            Candidate.extraction_run_id == first.id, Candidate.field_path == "identity.issuer"
        )
    )
    assert live == "validated", "the earlier candidate is kept; it is only not read"


def _two_windows(make_pipeline: MakePipeline, db: Session, second_emd: int | None) -> Pipeline:
    """The security section read in two windows (one page each); the second window may
    give another value for the EMD."""
    answers = dict(GOOD_ANSWERS)
    pipeline = make_pipeline(
        ScriptedSDK(
            answers,
            sections=[
                {
                    "start_page": 1,
                    "end_page": 1,
                    "heading": "Cover",
                    "kind": "cover_and_notice",
                    "confidence": 1,
                },
                {
                    "start_page": 2,
                    "end_page": 3,
                    "heading": "Dates and security",
                    "kind": "financial_security",
                    "confidence": 1,
                },
            ],
        ),
        extract_max_pages_per_call=1,
    )
    calls = 0

    def vary(number: int, kwargs: object) -> None:
        nonlocal calls
        text = kwargs["messages"][0]["content"][-1]["text"] if isinstance(kwargs, dict) else ""  # type: ignore[index]
        if "group `security`" in text:
            calls += 1
            if calls == 2 and second_emd is not None:
                pipeline.sdk.answers["emd_per_mw"] = {
                    **GOOD_ANSWERS["emd_per_mw"],
                    "value": second_emd,
                    "confidence": 0.6,
                    "evidence": [
                        {
                            "page_no": 1,
                            "quote": "The total contracted capacity under this agreement is 600 MW",
                        }
                    ],
                }
            else:
                pipeline.sdk.answers["emd_per_mw"] = GOOD_ANSWERS["emd_per_mw"]

    pipeline.sdk.before_call = vary
    return pipeline


def test_a_second_reading_with_another_value_is_listed_with_its_evidence(
    make_pipeline: MakePipeline, db: Session
) -> None:
    pipeline = _two_windows(make_pipeline, db, second_emd=930000)
    run = pipeline.extracted_run(db)
    state = pipeline.review_state.for_object(db, "document", run.document_id)
    emd = next(f for f in state.fields if f.field_path == "security.emd_per_mw")
    assert emd.candidate is not None and emd.candidate.value == 928000
    assert emd.alternative_candidates == 1
    [other] = emd.alternatives
    assert (other.value, other.confidence) == (930000, 0.6)
    assert other.evidence and other.evidence[0].page_no == 3
    assert other.id != emd.candidate.id
    assert all(f.alternatives == [] for f in state.fields if f.field_path != "security.emd_per_mw")


def test_a_second_reading_with_the_same_value_is_not_listed(
    make_pipeline: MakePipeline, db: Session
) -> None:
    pipeline = _two_windows(make_pipeline, db, second_emd=None)
    run = pipeline.extracted_run(db)
    state = pipeline.review_state.for_object(db, "document", run.document_id)
    emd = next(f for f in state.fields if f.field_path == "security.emd_per_mw")
    assert emd.candidate is not None and emd.alternatives == [] and emd.alternative_candidates == 0
    assert (
        db.scalar(
            select(func.count())
            .select_from(Candidate)
            .where(Candidate.field_path == "security.emd_per_mw")
        )
        == 2
    )


def test_the_reading_the_reviewer_decided_on_becomes_the_fields_reading(
    make_pipeline: MakePipeline, db: Session
) -> None:
    pipeline = _two_windows(make_pipeline, db, second_emd=930000)
    run = pipeline.extracted_run(db)
    state = pipeline.review_state.for_object(db, "document", run.document_id)
    emd = next(f for f in state.fields if f.field_path == "security.emd_per_mw")
    [other] = emd.alternatives
    pipeline.approvals.approve(db, candidate_id=other.id, decision="approved", reviewer="Asha")
    state = pipeline.review_state.for_object(db, "document", run.document_id)
    emd = next(f for f in state.fields if f.field_path == "security.emd_per_mw")
    assert (
        emd.candidate is not None and emd.candidate.id == other.id and emd.candidate.value == 930000
    )
    assert [c.value for c in emd.alternatives] == [928000]
    assert emd.approval is not None and emd.approval.candidate_id == other.id
    facts = pipeline.review_state.canonical(db, "document", run.document_id)
    assert [(f.field_path, f.value) for f in facts] == [("security.emd_per_mw", 930000)]
    # Cleared: the best-evidenced reading is shown again, the other listed.
    pipeline.approvals.approve(db, candidate_id=other.id, decision="cleared", reviewer="Asha")
    state = pipeline.review_state.for_object(db, "document", run.document_id)
    emd = next(f for f in state.fields if f.field_path == "security.emd_per_mw")
    assert emd.candidate is not None and emd.candidate.value == 928000
    assert [c.value for c in emd.alternatives] == [930000]
