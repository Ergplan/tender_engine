"""Postgres-backed job queue. Idea from tariff-oder services/api/src/tariff_api/queue.py
(SKIP LOCKED claim, bounded retries with backoff), reduced to a single-process worker.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Job

BACKOFF_SECONDS = 30


def enqueue(
    session: Session, *, tenant_id: str, kind: str, payload: dict[str, Any], created_by: str
) -> Job:
    job = Job(tenant_id=tenant_id, created_by=created_by, kind=kind, payload=payload)
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session) -> Job | None:
    """Take the oldest due job and mark it running. Commits."""
    now = datetime.now(UTC)
    job = session.scalar(
        select(Job)
        .where(Job.status == "queued", Job.run_after <= now)
        .order_by(Job.run_after, Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        session.rollback()
        return None
    job.status = "running"
    job.attempts += 1
    job.started_at = now
    session.commit()
    return job


def complete(session: Session, job_id: str) -> None:
    job = session.get_one(Job, job_id)
    job.status = "done"
    job.finished_at = datetime.now(UTC)
    job.last_error = None
    session.commit()


def fail(session: Session, job_id: str, error: str, *, retryable: bool = True) -> Job:
    """Record the error. Re-queue with backoff until max_attempts, then mark failed."""
    job = session.get_one(Job, job_id)
    job.last_error = error
    if retryable and job.attempts < job.max_attempts:
        job.status = "queued"
        delay = BACKOFF_SECONDS * 2 ** (job.attempts - 1)
        job.run_after = datetime.now(UTC) + timedelta(seconds=delay)
    else:
        job.status = "failed"
        job.finished_at = datetime.now(UTC)
    session.commit()
    return job
