from datetime import UTC, datetime, timedelta

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
    claimed = jobs.claim_next(db)
    assert claimed is not None and claimed.id == first.id
    assert (claimed.status, claimed.attempts) == ("running", 1) and claimed.started_at
    again = jobs.claim_next(db)
    assert again is not None and again.id == second.id
    assert jobs.claim_next(db) is None


def test_a_job_scheduled_for_later_is_not_claimed(db: Session) -> None:
    job = enqueue(db)
    job.run_after = datetime.now(UTC) + timedelta(minutes=5)
    db.commit()
    assert jobs.claim_next(db) is None


def test_a_job_locked_by_another_session_is_skipped(
    db: Session, session_factory: sessionmaker[Session]
) -> None:
    enqueue(db)
    with session_factory() as other:
        from sqlalchemy import select

        other.scalar(select(Job).with_for_update())
        assert jobs.claim_next(db) is None
        other.rollback()
    assert jobs.claim_next(db) is not None


def test_complete_marks_done_and_clears_the_error(db: Session) -> None:
    job = enqueue(db)
    jobs.claim_next(db)
    jobs.fail(db, job.id, "first error")
    job.run_after = datetime.now(UTC)
    db.commit()
    jobs.claim_next(db)
    jobs.complete(db, job.id)
    db.refresh(job)
    assert (job.status, job.last_error, job.attempts) == ("done", None, 2) and job.finished_at


def test_failure_requeues_with_growing_backoff_then_fails_after_three_attempts(
    db: Session,
) -> None:
    job = enqueue(db)
    delays = []
    for attempt in (1, 2, 3):
        job.run_after = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        assert jobs.claim_next(db) is not None
        before = datetime.now(UTC)
        jobs.fail(db, job.id, f"Traceback attempt {attempt}")
        db.refresh(job)
        delays.append((job.run_after - before).total_seconds())
        assert job.last_error == f"Traceback attempt {attempt}"
        assert job.status == ("queued" if attempt < 3 else "failed")
    assert 29 <= delays[0] <= 31 and 59 <= delays[1] <= 61
    assert job.attempts == 3 and job.finished_at is not None
    assert jobs.claim_next(db) is None


def test_a_non_retryable_failure_fails_at_once(db: Session) -> None:
    job = enqueue(db)
    jobs.claim_next(db)
    jobs.fail(db, job.id, "bad input", retryable=False)
    db.refresh(job)
    assert (job.status, job.attempts) == ("failed", 1)
