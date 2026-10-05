from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Candidate
from tests.conftest import Pipeline
from tests.fixtures.llm import GOOD_ANSWERS, ScriptedSDK

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
