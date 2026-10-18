"""The agent container's loop: its own job kind, nothing of the worker's."""

import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.harness import Harness, RunOutcome
from agent.main import AgentWorker
from agent.service import JOB_KIND, AgentPassService
from core.models import Job
from core.services import jobs
from tender.models import Tender
from tests.agent.conftest import scripted
from tests.agent.test_service import submit_deadline
from tests.conftest import Pipeline


def other_job(db: Session, kind: str = "parse", **payload: str) -> Job:
    job = jobs.enqueue(
        db,
        tenant_id="ergplan",
        kind=kind,
        payload=payload or {"document_id": "x"},
        created_by="pytest",
    )
    db.commit()
    return job


def test_run_once_claims_only_agent_pass_jobs_and_completes_them(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    foreign = other_job(db)
    worker = AgentWorker(
        pipeline.settings,
        pipeline.session_factory,
        service=service,
        driver=scripted(submit_deadline),
    )
    assert worker.run_once() is False, "nothing of its kind yet"
    run = service.start(db, readable_tender, created_by="pytest")
    assert worker.run_once() is True
    db.refresh(run)
    db.refresh(foreign)
    assert run.status == "done" and [f.status for f in service.findings(db, run)] == ["accepted"]
    job = db.scalars(select(Job).where(Job.kind == JOB_KIND)).one()
    assert (job.status, job.attempts) == ("done", 1)
    assert (foreign.status, foreign.attempts) == ("queued", 0)
    assert worker.run_once() is False


def test_the_worker_runner_leaves_agent_pass_jobs_alone(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    run = service.start(db, readable_tender, created_by="pytest")
    pipeline.runner.run_until_idle()
    db.refresh(run)
    job = db.scalars(select(Job).where(Job.kind == JOB_KIND)).one()
    assert (run.status, job.status, job.attempts) == ("queued", "queued", 0)


def test_a_driver_error_stops_the_run_and_the_job_still_completes(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    def drive(harness: Harness, instructions: str, brief: str) -> RunOutcome:
        raise RuntimeError("boom")

    run = service.start(db, readable_tender, created_by="pytest")
    worker = AgentWorker(pipeline.settings, pipeline.session_factory, service=service, driver=drive)
    assert worker.run_once() is True
    db.refresh(run)
    assert run.status == "stopped" and run.error
    assert run.error.startswith("RuntimeError: boom; ") and "without a finding" in run.error
    job = db.scalars(select(Job).where(Job.kind == JOB_KIND)).one()
    assert (job.status, job.last_error) == ("done", None)


def test_a_failure_outside_the_service_is_recorded_on_the_job(
    pipeline: Pipeline, db: Session, service: AgentPassService
) -> None:
    # No such agent run: the service raises LookupError before any driver runs.
    job = other_job(db, JOB_KIND, agent_run_id="0" * 32)
    worker = AgentWorker(
        pipeline.settings, pipeline.session_factory, service=service, driver=scripted(lambda h: "")
    )
    assert worker.run_once() is True
    db.refresh(job)
    assert job.status == "queued" and job.attempts == 1
    assert job.last_error is not None and "LookupError" in job.last_error


def test_run_forever_puts_back_only_its_own_orphans(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    service.start(db, readable_tender, created_by="pytest")
    own = db.scalars(select(Job).where(Job.kind == JOB_KIND)).one()
    foreign = other_job(db, "extract")
    for job in (own, foreign):
        job.status = "running"
        job.attempts = 1
    db.commit()
    stop = threading.Event()
    stop.set()
    AgentWorker(
        pipeline.settings, pipeline.session_factory, service=service, driver=scripted(lambda h: "")
    ).run_forever(stop)
    db.refresh(own)
    db.refresh(foreign)
    assert own.status == "queued" and own.last_error and "stopped while" in own.last_error
    assert (foreign.status, foreign.last_error) == ("running", None)
