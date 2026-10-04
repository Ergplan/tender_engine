from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import AuditLog, Candidate, ExtractionRun, ValidationResult
from core.services.validate import ValidationService
from tests.conftest import Pipeline
from tests.fixtures.llm import GOOD_ANSWERS, ScriptedSDK

MakePipeline = Callable[..., Pipeline]


def results(db: Session, run: ExtractionRun, path: str) -> tuple[str, dict[str, tuple[bool, str]]]:
    candidate = db.scalar(
        select(Candidate).where(Candidate.extraction_run_id == run.id, Candidate.field_path == path)
    )
    assert candidate is not None
    rows = db.scalars(select(ValidationResult).where(ValidationResult.candidate_id == candidate.id))
    return candidate.status, {row.rule_name: (row.passed, row.message) for row in rows}


def run_with(
    make_pipeline: MakePipeline, db: Session, **overrides: dict[str, Any]
) -> ExtractionRun:
    return make_pipeline(ScriptedSDK({**GOOD_ANSWERS, **overrides})).extracted_run(db)


def test_clean_candidates_are_validated_with_a_result_per_rule(
    pipeline: Pipeline, db: Session
) -> None:
    run = pipeline.extracted_run(db)
    status, rules = results(db, run, "security.emd_per_mw")
    assert status == "validated"
    assert {name: passed for name, (passed, _) in rules.items()} == {
        "evidence_located": True,
        "type": True,
        "range": True,
    }
    status, rules = results(db, run, "identity.agreement_number")
    assert status == "validated" and rules["regex"][0] is True
    status, rules = results(db, run, "dates.pre_bid_date")
    assert status == "validated" and rules["contract_date_order"][0] is True
    assert all(
        row.tenant_id == "ergplan" and row.created_by == "validation"
        for row in db.scalars(select(ValidationResult))
    )


def test_a_value_of_the_wrong_type_needs_review_with_the_rule_name(
    make_pipeline: MakePipeline, db: Session
) -> None:
    run = run_with(
        make_pipeline, db, bid_deadline={**GOOD_ANSWERS["bid_deadline"], "value": "end of March"}
    )
    status, rules = results(db, run, "dates.bid_deadline")
    assert status == "needs_review"
    assert rules["type"] == (False, "not a valid date: unrecognised date 'end of March'")
    assert "contract_date_order" not in rules


def test_out_of_range_and_pattern_failures_need_review(
    make_pipeline: MakePipeline, db: Session
) -> None:
    run = run_with(
        make_pipeline,
        db,
        tenure_years={**GOOD_ANSWERS["tenure_years"], "value": 99},
        agreement_number={
            **GOOD_ANSWERS["agreement_number"],
            "value": "Agreement No. ACME/2026/001",
        },
    )
    status, rules = results(db, run, "security.tenure_years")
    assert status == "needs_review" and rules["range"] == (False, "99 is above the maximum 35")
    status, rules = results(db, run, "identity.agreement_number")
    assert status == "needs_review" and rules["regex"][0] is False


def test_a_cross_field_failure_marks_both_fields(make_pipeline: MakePipeline, db: Session) -> None:
    run = run_with(
        make_pipeline, db, pre_bid_date={**GOOD_ANSWERS["pre_bid_date"], "value": "12.04.2026"}
    )
    for path in ("dates.pre_bid_date", "dates.bid_deadline"):
        status, rules = results(db, run, path)
        assert status == "needs_review"
        assert rules["contract_date_order"] == (
            False,
            "pre-bid date 2026-04-12 is after bid deadline 2026-03-30",
        )


def test_unlocated_evidence_is_a_named_validation_failure_and_the_candidate_stays_visible(
    make_pipeline: MakePipeline, db: Session
) -> None:
    pipeline = make_pipeline(
        ScriptedSDK(
            {
                **GOOD_ANSWERS,
                "issuer": {
                    **GOOD_ANSWERS["issuer"],
                    "evidence": [{"page_no": 1, "quote": "words that are not on the page at all"}],
                },
            }
        )
    )
    run = pipeline.extracted_run(db)
    status, rules = results(db, run, "identity.issuer")
    assert status == "needs_review"
    assert rules["evidence_not_located"] == (False, "evidence not located on p.1")
    state = pipeline.review_state.for_object(db, "document", run.document_id)
    issuer = next(f for f in state.fields if f.field_path == "identity.issuer")
    assert issuer.candidate is not None and issuer.candidate.status == "needs_review"


def test_a_required_field_the_model_did_not_find_is_flagged_but_an_optional_one_is_not(
    make_pipeline: MakePipeline, db: Session
) -> None:
    sdk = ScriptedSDK(
        {k: v for k, v in GOOD_ANSWERS.items() if k not in ("bid_deadline", "issuer")}
    )
    run = make_pipeline(sdk).extracted_run(db)
    status, rules = results(db, run, "dates.bid_deadline")
    assert status == "needs_review", "a failed validation marks the candidate needs_review"
    assert rules == {"required_present": (False, "required field: the model returned no value")}
    assert results(db, run, "identity.issuer") == ("not_found", {})
    assert "contract_date_order" not in results(db, run, "dates.pre_bid_date")[1]


def test_a_rejected_candidate_gets_the_evidence_required_result(
    make_pipeline: MakePipeline, db: Session
) -> None:
    run = run_with(
        make_pipeline,
        db,
        issuer={"value": "Acme", "confidence": 0.9, "rationale": "r", "evidence": []},
    )
    status, rules = results(db, run, "identity.issuer")
    assert status == "rejected" and rules["evidence_required"][0] is False


def test_status_changes_are_audited_and_validation_is_repeatable(
    make_pipeline: MakePipeline, db: Session
) -> None:
    pipeline = make_pipeline(
        ScriptedSDK({**GOOD_ANSWERS, "tenure_years": {**GOOD_ANSWERS["tenure_years"], "value": 99}})
    )
    run = pipeline.extracted_run(db)
    changes = list(db.scalars(select(AuditLog).where(AuditLog.action == "status_change")))
    assert len(changes) == 7 and all(row.actor == "validation" for row in changes)
    assert (
        sorted(row.after["status"] for row in changes if row.after)
        == ["needs_review"] + ["validated"] * 6
    )
    assert all(row.before == {"status": "raw"} for row in changes)
    before = db.scalar(select(func.count()).select_from(ValidationResult))
    ValidationService(pipeline.schemas, "ergplan").validate(db, run.id)
    assert db.scalar(select(func.count()).select_from(ValidationResult)) == before
    assert (
        db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "status_change")
        )
        == 7
    )


def test_one_unlocated_quote_among_several_still_sends_the_candidate_to_review(
    make_pipeline: MakePipeline, db: Session
) -> None:
    good = GOOD_ANSWERS["issuer"]["evidence"][0]
    run = run_with(
        make_pipeline,
        db,
        issuer={
            **GOOD_ANSWERS["issuer"],
            "evidence": [good, {"page_no": 1, "quote": "words that are not on the page at all"}],
        },
    )
    status, rules = results(db, run, "identity.issuer")
    assert status == "needs_review"
    assert rules["evidence_not_located"] == (False, "1 of 2 quotes not located (stated on p.1)")
    issuer = db.scalars(
        select(Candidate).where(
            Candidate.extraction_run_id == run.id, Candidate.field_path == "identity.issuer"
        )
    ).one()
    assert issuer.confidence == GOOD_ANSWERS["issuer"]["confidence"], "located once: no cap"


def test_a_cross_field_failure_is_written_on_every_candidate_of_the_fields(
    make_pipeline: MakePipeline, db: Session
) -> None:
    """A field can have two candidates when its window is split. The failed rule must show
    on both, so the read model cannot pick one the rule never touched."""
    sdk = ScriptedSDK(
        {**GOOD_ANSWERS, "pre_bid_date": {**GOOD_ANSWERS["pre_bid_date"], "value": "12.04.2026"}},
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
    run = make_pipeline(sdk, extract_max_pages_per_call=2).extracted_run(db)
    rows = list(
        db.scalars(
            select(Candidate).where(
                Candidate.extraction_run_id == run.id,
                Candidate.field_path.in_(["dates.pre_bid_date", "dates.bid_deadline"]),
            )
        )
    )
    assert len(rows) == 4
    for row in rows:
        failed = db.scalars(
            select(ValidationResult.rule_name).where(
                ValidationResult.candidate_id == row.id, ValidationResult.passed.is_(False)
            )
        ).all()
        assert "contract_date_order" in failed and row.status == "needs_review"


def test_a_run_rule_sees_the_run_and_its_valued_candidates_and_can_fail_one(
    make_pipeline: MakePipeline, db: Session
) -> None:
    from collections.abc import Sequence

    from core.schemas import CandidateOutcome
    from tests.fixtures.schemas import contract_schema

    seen: list[tuple[str, list[str]]] = []

    def no_emd(
        session: Session, run: ExtractionRun, valued: Sequence[Candidate]
    ) -> list[CandidateOutcome]:
        seen.append((run.schema_name, sorted(c.field_path for c in valued)))
        return [
            CandidateOutcome(c.id, c.field_path != "security.emd_per_mw", "checked by run rule")
            for c in valued
        ]

    pipeline = make_pipeline(ScriptedSDK({k: v for k, v in GOOD_ANSWERS.items() if k != "issuer"}))
    pipeline.schemas.register_run_rule("no_emd", no_emd)
    with pytest.raises(ValueError, match="already registered"):
        pipeline.schemas.register_run_rule("no_emd", no_emd)
    with pytest.raises(ValueError, match="unregistered run rule"):
        pipeline.schemas.register(
            contract_schema().model_copy(update={"name": "test.bad", "run_rules": ["missing"]})
        )
    schema = contract_schema().model_copy(update={"name": "test.runrule", "run_rules": ["no_emd"]})
    pipeline.schemas.register(schema)
    document = pipeline.parsed_document(db)
    run = pipeline.extract.start_run(
        db,
        document_id=document.id,
        schema_name="test.runrule",
        schema_version="v1",
        prompt_version="v1",
        created_by="pytest",
        is_fixture=True,
    )
    pipeline.runner.run_until_idle()
    assert seen == [
        (
            "test.runrule",
            [
                "dates.bid_deadline",
                "dates.pre_bid_date",
                "identity.agreement_number",
                "security.capacity_mw",
                "security.emd_per_mw",
                "security.tenure_years",
            ],
        )
    ]
    status, rules = results(db, run, "security.emd_per_mw")
    assert status == "needs_review" and rules["no_emd"] == (False, "checked by run rule")
    status, rules = results(db, run, "security.capacity_mw")
    assert status == "validated" and rules["no_emd"] == (True, "checked by run rule")
    assert "no_emd" not in results(db, run, "identity.issuer")[1]
