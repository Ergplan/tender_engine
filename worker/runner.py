"""Job runner for one tenant: claims one of its jobs at a time and runs the
parse -> section_map -> extract -> validate chain. A single process; failures are recorded
with the traceback and retried with backoff up to the job's max_attempts.
"""

import logging
import threading
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.llm.client import LLMCallError, LLMClient
from core.llm.registry import UnregisteredPromptError
from core.models import Document, ExtractionRun, Job
from core.schemas import SchemaRegistry, UnknownSchemaError
from core.services import jobs
from core.services.extract import ExtractService
from core.services.parse import ParseService
from core.services.section_map import SectionMapper
from core.services.validate import ValidationService
from core.storage import Storage

log = logging.getLogger("worker")
Handler = Callable[[Session, dict[str, Any]], None]


class Runner:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        storage: Storage,
        schemas: SchemaRegistry,
        llm: LLMClient,
        extra_handlers: dict[str, Handler] | None = None,
        on_validated: Callable[[Session, str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._parse = ParseService(storage, settings)
        self._section_map = SectionMapper(llm, settings.tenant_id)
        self._extract = ExtractService(llm, storage, schemas, settings)
        self._validate = ValidationService(schemas, settings.tenant_id)
        self._on_validated = on_validated
        self._handlers: dict[str, Handler] = {
            "parse": lambda s, p: _ignore(self._parse.parse(s, p["document_id"])),
            "section_map": lambda s, p: _ignore(self._section_map.map(s, p["document_id"])),
            "extract": lambda s, p: _ignore(self._extract.extract(s, p["extraction_run_id"])),
            "validate": self._validated,
            # Job kinds of the domain layer, handed in by whoever builds the runner.
            **(extra_handlers or {}),
        }

    def _validated(self, session: Session, payload: dict[str, Any]) -> None:
        """Validate the run; then tell the domain layer, which may have a second pass to
        queue once the runs of its object are all in."""
        self._validate.validate(session, payload["extraction_run_id"])
        if self._on_validated is not None:
            self._on_validated(session, payload["extraction_run_id"])

    def run_once(self) -> bool:
        """Run the next due job, if any. Returns whether a job was run."""
        with self._session_factory() as session:
            job = jobs.claim_next(session, self._settings.tenant_id)
            if job is None:
                return False
            job_id, kind, payload = job.id, job.kind, dict(job.payload)
        log.info("job %s %s started", kind, job_id)
        try:
            handler = self._handlers.get(kind)
            if handler is None:
                raise UnknownJobError(f"no handler for job kind {kind!r}")
            with self._session_factory() as session:
                handler(session, payload)
        except Exception as exc:
            retryable = _retryable(exc)
            with self._session_factory() as session:
                failed = jobs.fail(
                    session,
                    self._settings.tenant_id,
                    job_id,
                    traceback.format_exc(),
                    retryable=retryable,
                )
                if failed.status == "failed":
                    self._mark_run_failed(session, failed, exc)
            log.exception("job %s %s failed (status now %s)", kind, job_id, failed.status)
            return True
        with self._session_factory() as session:
            jobs.complete(session, self._settings.tenant_id, job_id)
        log.info("job %s %s done", kind, job_id)
        return True

    def run_until_idle(self, max_jobs: int = 100) -> int:
        """Run due jobs until none is left. For tests and management commands."""
        count = 0
        while count < max_jobs and self.run_once():
            count += 1
        return count

    def run_forever(self, stop: threading.Event) -> None:
        with self._session_factory() as session:
            orphans = jobs.requeue_orphans(session, self._settings.tenant_id)
        if orphans:
            log.warning("%s job(s) left running by an earlier worker were put back", orphans)
        log.info("worker polling every %ss", self._settings.worker_poll_seconds)
        while not stop.is_set():
            if not self.run_once():
                stop.wait(self._settings.worker_poll_seconds)

    def _mark_run_failed(self, session: Session, job: Job, exc: Exception) -> None:
        """Show a job that failed for good on the thing it was working on."""
        run_id = job.payload.get("extraction_run_id")
        if not run_id:
            document = session.scalar(
                select(Document).where(
                    Document.id == job.payload.get("document_id"),
                    Document.tenant_id == job.tenant_id,
                )
            )
            if document is not None and job.kind == "section_map":
                document.error = f"section map failed: {type(exc).__name__}: {exc}"
                session.commit()
            return
        run = session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.id == run_id, ExtractionRun.tenant_id == job.tenant_id
            )
        )
        if run is not None and run.status not in ("validated",):
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            session.commit()


class UnknownJobError(LookupError):
    pass


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, LLMCallError):
        return exc.retryable
    return not isinstance(exc, LookupError | UnknownSchemaError | UnregisteredPromptError)


def _ignore(_: object) -> None:
    return None
