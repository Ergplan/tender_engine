from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from core.models import Job
from core.services import jobs


def enqueue(db: Session, kind: str = "parse") -> Job:
    job = jobs.enqueue(db, tenant_id="ergplan", kind=kind, payload={"n": 1}, created_by="pytest")
    db.commit()
    return job


def test_jobs_are_claimed_oldest_first_and_only_once(db: Session) -> None:
    first, second = enqueue(db, "a"), enqueue(db, "b")
    first.run_after = datetime.now(UTC) - timedelta(seconds=5)
    db.commit()
    claimed = jobs.claim_next(db, "ergplan")
    assert claimed is not None and claimed.id == first.id
    assert (claimed.status, claimed.attempts) == ("running", 1) and claimed.started_at
    again = jobs.claim_next(db, "ergplan")
    assert again is not None and again.id == second.id
    assert jobs.claim_next(db, "ergplan") is None


def test_a_job_scheduled_for_later_is_not_claimed(db: Session) -> None:
    job = enqueue(db)
    job.run_after = datetime.now(UTC) + timedelta(minutes=5)
    db.commit()
    assert jobs.claim_next(db, "ergplan") is None


def test_a_job_locked_by_another_session_is_skipped(
    db: Session, session_factory: sessionmaker[Session]
) -> None:
    enqueue(db)
    with session_factory() as other:
        from sqlalchemy import select

        other.scalar(select(Job).with_for_update())
        assert jobs.claim_next(db, "ergplan") is None
        other.rollback()
    assert jobs.claim_next(db, "ergplan") is not None


def test_complete_marks_done_and_clears_the_error(db: Session) -> None:
    job = enqueue(db)
    jobs.claim_next(db, "ergplan")
    jobs.fail(db, "ergplan", job.id, "first error")
    job.run_after = datetime.now(UTC)
    db.commit()
    jobs.claim_next(db, "ergplan")
    jobs.complete(db, "ergplan", job.id)
    db.refresh(job)
    assert (job.status, job.last_error, job.attempts) == ("done", None, 2) and job.finished_at


def test_failure_is_retried_three_times_with_growing_backoff_then_fails(
    db: Session,
) -> None:
    job = enqueue(db)
    delays = []
    for attempt in (1, 2, 3, 4):
        job.run_after = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        assert jobs.claim_next(db, "ergplan") is not None
        before = datetime.now(UTC)
        jobs.fail(db, "ergplan", job.id, f"Traceback attempt {attempt}")
        db.refresh(job)
        delays.append((job.run_after - before).total_seconds())
        assert job.last_error == f"Traceback attempt {attempt}"
        assert job.status == ("queued" if attempt < 4 else "failed")
    assert 29 <= delays[0] <= 31 and 59 <= delays[1] <= 61 and 119 <= delays[2] <= 121
    assert job.attempts == 4 and job.finished_at is not None
    assert jobs.claim_next(db, "ergplan") is None


def test_jobs_left_running_by_a_dead_worker_are_put_back_or_failed(db: Session) -> None:
    interrupted, exhausted, waiting = enqueue(db), enqueue(db), enqueue(db)
    for job in (interrupted, exhausted):
        job.status = "running"
        job.attempts = 1
    exhausted.attempts = exhausted.max_attempts
    db.commit()

    assert jobs.requeue_orphans(db, "ergplan") == 2
    for job in (interrupted, exhausted, waiting):
        db.refresh(job)
    assert (interrupted.status, interrupted.attempts) == ("queued", 1)
    assert interrupted.last_error is not None and "worker stopped" in interrupted.last_error
    assert exhausted.status == "failed" and exhausted.finished_at is not None
    assert (waiting.status, waiting.last_error) == ("queued", None)
    assert jobs.requeue_orphans(db, "ergplan") == 0


def test_a_non_retryable_failure_fails_at_once(db: Session) -> None:
    job = enqueue(db)
    jobs.claim_next(db, "ergplan")
    jobs.fail(db, "ergplan", job.id, "bad input", retryable=False)
    db.refresh(job)
    assert (job.status, job.attempts) == ("failed", 1)


def test_a_worker_only_sees_the_jobs_of_its_own_tenant(db: Session) -> None:
    db.execute(
        text("INSERT INTO tenant (tenant_id, name, created_by) VALUES ('other', 'Other', 't')")
    )
    foreign = jobs.enqueue(db, tenant_id="other", kind="parse", payload={}, created_by="t")
    foreign.status = "running"
    db.commit()
    assert jobs.requeue_orphans(db, "ergplan") == 0
    foreign.status = "queued"
    db.commit()
    assert jobs.claim_next(db, "ergplan") is None
    claimed = jobs.claim_next(db, "other")
    assert claimed is not None and claimed.id == foreign.id
