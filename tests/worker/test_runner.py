from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import ExtractionRun, Job
from core.services import jobs
from tests.conftest import Pipeline
from tests.fixtures.llm import ScriptedSDK

MakePipeline = Callable[..., Pipeline]


def test_the_chain_runs_parse_section_map_extract_validate_in_order(
    pipeline: Pipeline, db: Session
) -> None:
    document = pipeline.upload(db)
    assert pipeline.runner.run_until_idle() == 2
    db.refresh(document)
    assert document.status == "parsed"
    run = pipeline.start_run(db, document)
    assert pipeline.runner.run_until_idle() == 2
    assert pipeline.runner.run_once() is False
    db.refresh(run)
    assert run.status == "validated"
    done = [
        (job.kind, job.status, job.attempts)
        for job in db.scalars(select(Job).order_by(Job.created_at))
    ]
    assert done == [
        ("parse", "done", 1),
        ("section_map", "done", 1),
        ("extract", "done", 1),
        ("validate", "done", 1),
    ]


def test_a_failing_job_records_the_traceback_and_is_requeued(
    make_pipeline: MakePipeline, db: Session
) -> None:
    def always_fail(number: int, kwargs: dict[str, Any]) -> None:
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.InternalServerError(
            "boom", response=httpx2.Response(500, request=request), body=None
        )

    pipeline = make_pipeline(ScriptedSDK(before_call=always_fail))
    pipeline.upload(db)
    assert pipeline.runner.run_until_idle() == 2
    job = db.scalars(select(Job).where(Job.kind == "section_map")).one()
    assert (job.status, job.attempts) == ("queued", 1)
    assert (
        job.last_error is not None
        and "Traceback" in job.last_error
        and "LLMCallError" in job.last_error
    )


def test_a_non_retryable_failure_fails_the_job_and_the_run_at_once(
    make_pipeline: MakePipeline, db: Session
) -> None:
    def bad_request_on_extract(number: int, kwargs: dict[str, Any]) -> None:
        if number > 1:
            request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.BadRequestError(
                "bad", response=httpx2.Response(400, request=request), body=None
            )

    pipeline = make_pipeline(ScriptedSDK(before_call=bad_request_on_extract))
    run = pipeline.start_run(db, pipeline.parsed_document(db))
    pipeline.runner.run_until_idle()
    db.expire_all()
    job = db.scalars(select(Job).where(Job.kind == "extract")).one()
    assert (job.status, job.attempts) == ("failed", 1)
    failed = db.get_one(ExtractionRun, run.id)
    assert failed.status == "failed" and failed.error is not None and "HTTP 400" in failed.error


def test_an_unknown_job_kind_fails_without_retry(pipeline: Pipeline, db: Session) -> None:
    job = jobs.enqueue(db, tenant_id="ergplan", kind="mystery", payload={}, created_by="pytest")
    db.commit()
    assert pipeline.runner.run_once() is True
    db.refresh(job)
    assert job.status == "failed" and "no handler for job kind 'mystery'" in (job.last_error or "")


def test_a_section_map_that_fails_for_good_is_shown_on_the_document(
    make_pipeline: MakePipeline, db: Session
) -> None:
    def refuse(number: int, kwargs: dict[str, Any]) -> None:
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.BadRequestError(
            "bad request", response=httpx2.Response(400, request=request), body=None
        )

    pipeline = make_pipeline(ScriptedSDK(before_call=refuse))
    document = pipeline.upload(db)
    pipeline.runner.run_until_idle()
    db.refresh(document)
    assert document.status == "parsed"
    assert document.error is not None and document.error.startswith("section map failed")


def test_the_worker_puts_back_jobs_an_earlier_worker_left_running(
    pipeline: Pipeline, db: Session
) -> None:
    import threading

    document = pipeline.upload(db)
    job = db.scalars(select(Job).where(Job.kind == "parse")).one()
    job.status, job.attempts = "running", 1
    db.commit()
    assert pipeline.runner.run_once() is False, "a running job is not claimed"

    stop = threading.Event()
    stop.set()
    pipeline.runner.run_forever(stop)
    pipeline.runner.run_until_idle()
    db.refresh(document)
    assert document.status == "parsed"
