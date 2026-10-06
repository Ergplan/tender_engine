"""A run may read a section with a prompt version other than the pinned one, for an
evaluation; the override is stored on the run and on every candidate it produces."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.llm.registry import UnregisteredPromptError
from core.models import Candidate, ExtractionRun
from core.services.extract import ExtractionError
from evals.runner import candidates_of_runs, finished_runs
from tests.conftest import Pipeline
from tests.fixtures.tenders import extracted_tender


def test_an_override_reads_the_section_with_that_version(pipeline: Pipeline, db: Session) -> None:
    tender = extracted_tender(pipeline, db)
    own_runs = select(ExtractionRun.id).where(ExtractionRun.object_id == tender.id)
    first = list(db.scalars(select(Candidate).where(Candidate.extraction_run_id.in_(own_runs))))
    commercial = {c.field_path for c in first if c.prompt_name == "extract/commercial"}
    assert commercial and {c.prompt_version for c in first if c.field_path in commercial} == {"v3"}
    runs = pipeline.tenders.start_extraction(
        db,
        tender,
        created_by="pytest",
        is_fixture=True,
        groups=["commercial"],
        prompt_overrides={"commercial": "v2", "penalties": ""},
    )
    assert [r.prompt_overrides for r in runs] == [{"commercial": "v2"}]
    pipeline.runner.run_until_idle()
    db.refresh(runs[0])
    assert runs[0].status == "validated"
    again = {
        c.field_path: c.prompt_version
        for c in db.scalars(select(Candidate).where(Candidate.extraction_run_id == runs[0].id))
    }
    assert set(again) == commercial and set(again.values()) == {"v2"}
    stored = db.get_one(ExtractionRun, runs[0].id)
    assert stored.prompt_overrides == {"commercial": "v2"}
    # What an evaluation of that run scores: its readings, one per field, with their pages.
    assert finished_runs(db, pipeline.settings.tenant_id, [runs[0].id])
    readings = candidates_of_runs(db, pipeline.settings.tenant_id, [runs[0].id])
    assert set(readings) == commercial
    assert {r.prompt_version for r in readings.values()} == {"v2"}
    assert {r.prompt_name for r in readings.values()} == {"extract/commercial"}
    assert candidates_of_runs(db, "another-tenant", [runs[0].id]) == {}


def test_an_override_must_name_a_group_and_a_registered_version(
    pipeline: Pipeline, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    with pytest.raises(ExtractionError, match="no group"):
        pipeline.tenders.start_extraction(
            db, tender, created_by="pytest", is_fixture=True, prompt_overrides={"nope": "v1"}
        )
    with pytest.raises(UnregisteredPromptError):
        pipeline.tenders.start_extraction(
            db, tender, created_by="pytest", is_fixture=True, prompt_overrides={"commercial": "v99"}
        )
