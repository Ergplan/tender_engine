"""Invariants enforced by the database and by the shape of the code."""

import re
from pathlib import Path

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.models import AuditLog, Candidate, EvidenceSpan
from tests.conftest import Pipeline

ROOT = Path(__file__).resolve().parents[2]
CODE_DIRS = ("core", "tender", "api", "worker", "scripts")


def one_candidate(pipeline: Pipeline, db: Session) -> Candidate:
    run = pipeline.extracted_run(db)
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.extraction_run_id == run.id, Candidate.field_path == "security.emd_per_mw"
        )
    )
    assert candidate is not None
    return candidate


@pytest.mark.parametrize(
    "assignment",
    [
        "value = '1'::jsonb",
        "confidence = 1.0",
        "rationale = 'changed'",
        "field_path = 'x.y'",
        "prompt_version = 'v2'",
        "value_type = 'text'",
        "created_by = 'someone'",
    ],
)
def test_candidate_rows_cannot_be_updated(pipeline: Pipeline, db: Session, assignment: str) -> None:
    candidate = one_candidate(pipeline, db)
    with pytest.raises(DBAPIError, match="candidate rows are immutable: only status may change"):
        db.execute(text(f"UPDATE candidate SET {assignment} WHERE id = :id"), {"id": candidate.id})
    db.rollback()
    db.refresh(candidate)
    assert candidate.value == 928000 and candidate.confidence == 0.88


def test_candidate_rows_cannot_be_updated_through_the_orm_either(
    pipeline: Pipeline, db: Session
) -> None:
    candidate = one_candidate(pipeline, db)
    candidate.value = 1
    with pytest.raises(DBAPIError, match="immutable"):
        db.commit()
    db.rollback()


def test_candidate_rows_cannot_be_deleted(pipeline: Pipeline, db: Session) -> None:
    candidate = one_candidate(pipeline, db)
    with pytest.raises(DBAPIError, match="delete refused"):
        db.execute(text("DELETE FROM candidate WHERE id = :id"), {"id": candidate.id})
    db.rollback()


def test_candidate_status_alone_may_change(pipeline: Pipeline, db: Session) -> None:
    candidate = one_candidate(pipeline, db)
    db.execute(update(Candidate).where(Candidate.id == candidate.id).values(status="superseded"))
    db.commit()
    db.refresh(candidate)
    assert candidate.status == "superseded" and candidate.value == 928000


@pytest.mark.parametrize(
    "statement", ["UPDATE evidence_span SET quote = 'x'", "DELETE FROM evidence_span"]
)
def test_evidence_spans_cannot_be_changed_or_deleted(
    pipeline: Pipeline, db: Session, statement: str
) -> None:
    one_candidate(pipeline, db)
    assert db.scalar(select(EvidenceSpan.id).limit(1)) is not None
    with pytest.raises(DBAPIError, match="evidence_span rows are append-only"):
        db.execute(text(statement))
    db.rollback()


@pytest.mark.parametrize("statement", ["UPDATE audit_log SET actor = 'x'", "DELETE FROM audit_log"])
def test_the_audit_log_is_append_only(pipeline: Pipeline, db: Session, statement: str) -> None:
    one_candidate(pipeline, db)
    assert db.scalar(select(AuditLog.id).limit(1)) is not None
    with pytest.raises(DBAPIError, match="audit_log rows are append-only"):
        db.execute(text(statement))
    db.rollback()


def _python_files() -> list[Path]:
    return [path for directory in CODE_DIRS for path in (ROOT / directory).rglob("*.py")]


def test_approval_service_is_the_only_writer_of_canonical_fact() -> None:
    """Grep: CanonicalFact is constructed, and its rows changed, in approve.py and nowhere else."""
    constructs = re.compile(r"^(?!class ).*\bCanonicalFact\(", re.MULTILINE)
    mutates = re.compile(
        r"(insert|update|delete)\(\s*CanonicalFact\b|canonical_fact\b.*\b(INSERT|UPDATE|DELETE)\b",
        re.IGNORECASE,
    )
    writers = sorted(
        str(path.relative_to(ROOT))
        for path in _python_files()
        if constructs.search(path.read_text()) or mutates.search(path.read_text())
    )
    assert writers == ["core/services/approve.py"]


def test_nothing_reads_feedback_at_runtime() -> None:
    """Feedback is stored, never auto-applied: only approve.py (the writer) and the model
    definition may name the Feedback table."""
    users = sorted(
        str(path.relative_to(ROOT))
        for path in _python_files()
        if re.search(r"\bFeedback\b", path.read_text())
    )
    assert users == ["core/models/__init__.py", "core/models/truth.py", "core/services/approve.py"]


def test_validation_makes_no_model_call() -> None:
    """Deterministic validation: these modules import neither the LLM module nor the SDK."""
    for name in ("core/services/validate.py", "core/validation/rules.py", "core/schemas/types.py"):
        source = (ROOT / name).read_text()
        assert not re.search(r"^\s*(from|import) (core\.llm|anthropic)\b", source, re.MULTILINE), (
            name
        )


def test_core_does_not_import_the_tender_layer() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "core").rglob("*.py")
        if re.search(r"^\s*(from|import) tender\b", path.read_text(), re.MULTILINE)
    ]
    assert offenders == []
