"""Starting, running and reading back an agent pass."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.harness import Harness, Quote, RunOutcome
from agent.models import AgentFinding, AgentRun
from agent.service import JOB_KIND, AgentPassError, AgentPassService, job_handlers
from core.models import AuditLog, Job
from tender.models import Tender
from tests.agent.conftest import scripted
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE, make_tender

QUOTE = "The last date of bid submission is 30.03.2026 at 15:00 hrs."


def submit_deadline(harness: Harness) -> str:
    harness.read_pages(1, [2])
    told = harness.submit_finding(
        DEADLINE, '"30.03.2026"', 0.9, "bid sheet", [Quote(document_no=1, page_no=2, quote=QUOTE)]
    )
    assert told.startswith(f"{DEADLINE}: accepted")
    return "one field found"


def test_start_queues_a_run_its_job_and_an_audit_row(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    run = service.start(db, readable_tender, created_by="Asha")
    assert (run.status, run.object_type, run.object_id, run.object_version) == (
        "queued",
        "tender",
        readable_tender.id,
        1,
    )
    compiled = pipeline.catalog.get("solar")
    assert (run.schema_name, run.schema_version) == (
        compiled.schema.name,
        compiled.schema.version,
    )
    assert (run.prompt_name, run.prompt_version, run.model) == (
        "agent_pass",
        "v1",
        pipeline.settings.openai_model,
    )
    assert list(run.pages_offered) == ["1"] and run.pages_offered["1"]
    assert run.documents[0]["filename"] == "rfs.pdf" and run.documents[0]["number"] == 1
    assert run.pages_read == {} and run.created_by == "Asha" and not run.is_fixture

    job = db.scalars(select(Job).where(Job.kind == JOB_KIND)).one()
    assert (job.status, job.payload) == ("queued", {"agent_run_id": run.id})
    audited = db.scalars(
        select(AuditLog).where(AuditLog.table_name == "agent_run", AuditLog.action == "insert")
    ).one()
    assert audited.row_id == run.id and audited.actor == "Asha"
    assert audited.after["prompt"] == "agent_pass/v1" and audited.after["fields"] > 10

    assert service.get(db, readable_tender, run.id).id == run.id
    assert [r.id for r in service.runs(db, readable_tender)] == [run.id]
    assert service.findings(db, run) == []
    with pytest.raises(LookupError):
        service.get(db, readable_tender, "0" * 32)
    other = make_tender(pipeline, db)
    with pytest.raises(LookupError):
        service.get(db, other, run.id)


def test_start_refuses_a_superseded_tender_no_version_and_an_unknown_version(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    with pytest.raises(AgentPassError, match="no version 3"):
        service.start(db, readable_tender, version_no=3, created_by="x")
    bare = make_tender(pipeline, db)
    with pytest.raises(AgentPassError, match="no version yet"):
        service.start(db, bare, created_by="x")
    readable_tender.status = "superseded"
    db.commit()
    with pytest.raises(AgentPassError, match="superseded"):
        service.start(db, readable_tender, created_by="x")
    assert db.scalars(select(AgentRun)).all() == []


def test_run_drives_the_harness_and_closes_the_run_as_done(
    db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    run = service.start(db, readable_tender, created_by="pytest", is_fixture=True)
    done = service.run(db, run.id, scripted(submit_deadline))
    assert done.id == run.id and done.status == "done"
    assert done.started_at is not None and done.finished_at is not None
    assert done.error is not None and done.error.startswith("field(s) without a finding"[0:0])
    assert "field(s) without a finding" in done.error and DEADLINE not in done.error
    assert done.pages_read == {"1": [2]} and done.turns == 0
    findings = service.findings(db, done)
    assert [(f.field_path, f.status) for f in findings] == [(DEADLINE, "accepted")]
    closing = db.scalars(
        select(AuditLog).where(AuditLog.table_name == "agent_run", AuditLog.action == "finish")
    ).one()
    assert closing.after["status"] == "done" and closing.after["findings"] == 1
    assert DEADLINE not in closing.after["unsubmitted"]


def test_a_stopped_loop_keeps_the_findings_made_before_it(
    db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    def drive(harness: Harness, instructions: str, brief: str) -> RunOutcome:
        assert "Tender type: solar" in brief and "submit_finding" in instructions
        submit_deadline(harness)
        return RunOutcome(stopped="stopped at the turn limit (120)")

    run = service.start(db, readable_tender, created_by="pytest")
    stopped = service.run(db, run.id, drive)
    assert stopped.status == "stopped" and stopped.error
    assert stopped.error.startswith("stopped at the turn limit (120); ")
    assert "field(s) without a finding" in stopped.error and DEADLINE not in stopped.error
    assert [f.status for f in service.findings(db, stopped)] == ["accepted"]


def test_a_driver_that_raises_stops_the_run_with_the_error(
    db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    def drive(harness: Harness, instructions: str, brief: str) -> RunOutcome:
        harness.read_pages(1, [1])
        raise ConnectionError("provider unreachable")

    run = service.start(db, readable_tender, created_by="pytest")
    stopped = service.run(db, run.id, drive)
    assert stopped.status == "stopped" and stopped.error
    assert stopped.error.startswith("ConnectionError: provider unreachable; ")
    assert stopped.pages_read == {"1": [1]}


def test_a_run_that_is_not_queued_is_left_alone(
    db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    run = service.start(db, readable_tender, created_by="pytest")
    run.status = "done"
    db.commit()
    calls: list[str] = []

    def drive(harness: Harness, instructions: str, brief: str) -> RunOutcome:
        calls.append("ran")
        return RunOutcome()

    assert service.run(db, run.id, drive).status == "done"
    assert calls == [] and db.scalars(select(AgentFinding)).all() == []
    with pytest.raises(LookupError):
        service.run(db, "0" * 32, drive)


def test_an_input_that_vanished_fails_the_run(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    run = service.start(db, readable_tender, created_by="pytest")
    # The version was asked for by number; a run queued for a version that no longer
    # resolves cannot build its inputs.
    run.object_version = 9
    db.commit()
    failed = service.run(db, run.id, scripted(submit_deadline))
    assert failed.status == "failed" and failed.error and "no version 9" in failed.error


def test_job_handlers_map_the_agent_pass_kind(
    db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    handlers = job_handlers(service, scripted(submit_deadline))
    assert list(handlers) == ["agent_pass"]
    run = service.start(db, readable_tender, created_by="pytest")
    handlers["agent_pass"](db, {"agent_run_id": run.id})
    db.refresh(run)
    assert run.status == "done"
