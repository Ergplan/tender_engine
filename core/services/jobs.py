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


def claim_next(session: Session, tenant_id: str) -> Job | None:
    """Take the tenant's oldest due job and mark it running. Commits."""
    now = datetime.now(UTC)
    job = session.scalar(
        select(Job)
        .where(Job.tenant_id == tenant_id, Job.status == "queued", Job.run_after <= now)
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


def requeue_orphans(session: Session, tenant_id: str) -> int:
    """Put jobs left in `running` back in the queue. Called when the single worker starts:
    a job still marked running then belongs to a worker that died mid-job. A job that has
    used all its attempts is marked failed instead. Commits; returns the number touched."""
    orphans = list(
        session.scalars(
            select(Job).where(Job.tenant_id == tenant_id, Job.status == "running").with_for_update()
        )
    )
    now = datetime.now(UTC)
    for job in orphans:
        note = "worker stopped while the job was running"
        job.last_error = f"{note}\n{job.last_error}" if job.last_error else note
        if job.attempts < job.max_attempts:
            job.status = "queued"
            job.run_after = now
        else:
            job.status = "failed"
            job.finished_at = now
    session.commit()
    return len(orphans)


def _own(session: Session, tenant_id: str, job_id: str) -> Job:
    return session.scalars(select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)).one()


def complete(session: Session, tenant_id: str, job_id: str) -> None:
    job = _own(session, tenant_id, job_id)
    job.status = "done"
    job.finished_at = datetime.now(UTC)
    job.last_error = None
    session.commit()


def fail(
    session: Session, tenant_id: str, job_id: str, error: str, *, retryable: bool = True
) -> Job:
    """Record the error. Re-queue with backoff until max_attempts, then mark failed."""
    job = _own(session, tenant_id, job_id)
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
