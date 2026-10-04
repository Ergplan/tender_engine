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


def test_a_failed_rule_marked_as_a_warning_is_shown_but_does_not_send_to_review(
    make_pipeline: MakePipeline, db: Session
) -> None:
    from core.schemas import RuleOutcome
    from tests.fixtures.schemas import contract_schema

    def tenure_is_long(values: dict[str, Any]) -> list[RuleOutcome]:
        path = "security.tenure_years"
        if path not in values:
            return []
        return [RuleOutcome((path,), False, "a tenure of 25 years is unusual", warning=True)]

    pipeline = make_pipeline()
    pipeline.schemas.register_rule("tenure_is_long", tenure_is_long)
    schema = contract_schema().model_copy(
        update={"name": "test.warning", "cross_field_rules": ["tenure_is_long"]}
    )
    pipeline.schemas.register(schema)
    document = pipeline.parsed_document(db)
    run = pipeline.extract.start_run(
        db,
        document_id=document.id,
        schema_name="test.warning",
        schema_version="v1",
        prompt_version="v1",
        created_by="pytest",
        is_fixture=True,
    )
    pipeline.runner.run_until_idle()
    status, rules = results(db, run, "security.tenure_years")
    assert status == "validated", "a warning does not send the candidate to review"
    assert rules["tenure_is_long"] == (False, "a tenure of 25 years is unusual")
    severities = {
        row.rule_name: row.severity
        for row in db.scalars(
            select(ValidationResult)
            .join(Candidate, Candidate.id == ValidationResult.candidate_id)
            .where(Candidate.field_path == "security.tenure_years")
        )
    }
    assert severities["tenure_is_long"] == "warning" and severities["type"] == "error"
    state = pipeline.review_state.for_object(db, "document", document.id)
    tenure = next(f for f in state.fields if f.field_path == "security.tenure_years")
    assert tenure.candidate is not None
    shown = {v.rule_name: (v.passed, v.severity) for v in tenure.candidate.validation}
    assert shown["tenure_is_long"] == (False, "warning")


def test_a_required_field_is_required_of_the_object_not_of_each_document_or_version(
    make_pipeline: MakePipeline, db: Session
) -> None:
    """Version 1 states the bid deadline. A second document of version 1 and a later
    version that do not restate it are not flagged; an object that never states it is."""
    from tests.fixtures.pdfs import PAGE_1, PAGE_2, PAGE_3, make_pdf

    pipeline = make_pipeline()
    first = pipeline.parsed_document(db)
    stated = pipeline.start_run(db, first, object_type="thing", object_id="a" * 32)
    pipeline.runner.run_until_idle()
    assert results(db, stated, "dates.bid_deadline")[0] == "validated"

    pipeline.sdk.answers = {k: v for k, v in GOOD_ANSWERS.items() if k != "bid_deadline"}
    second = pipeline.parsed_document(db, make_pdf([PAGE_1, PAGE_2, PAGE_3, ["Annexure"]]))
    for version in (1, 2):
        silent = pipeline.start_run(
            db, second, object_type="thing", object_id="a" * 32, object_version=version
        )
        pipeline.runner.run_until_idle()
        status, rules = results(db, silent, "dates.bid_deadline")
        assert status == "not_found", f"version {version} need not restate the deadline"
        assert rules == {
            "required_present": (
                True,
                "stated by another document or an earlier version of the object",
            )
        }
    missing = pipeline.start_run(db, second, object_type="thing", object_id="b" * 32)
    pipeline.runner.run_until_idle()
    status, rules = results(db, missing, "dates.bid_deadline")
    assert status == "needs_review"
    assert rules == {"required_present": (False, "required field: the model returned no value")}
    earlier = pipeline.start_run(
        db, second, object_type="thing", object_id="c" * 32, object_version=1
    )
    pipeline.runner.run_until_idle()
    assert results(db, earlier, "dates.bid_deadline")[0] == "needs_review", (
        "a value stated only by a later version does not satisfy an earlier one"
    )
