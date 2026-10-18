"""The agent container's entrypoint: poll the job table for `agent_pass` jobs only, run
each through the OpenAI Agents SDK, and never touch the worker's chain."""

import logging
import os
import signal
import threading
import traceback

from sqlalchemy.orm import Session, sessionmaker

from agent.harness import Driver
from agent.service import JOB_KIND, AgentPassService, real_driver
from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.services import jobs
from core.services.extract import ExtractService
from core.services.liveness import serve_health
from core.storage import make_storage
from tender.services.packs import build_registry
from tender.services.tenders import TenderService

log = logging.getLogger("agent")


class AgentWorker:
    """One process, one job kind."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        service: AgentPassService | None = None,
        driver: Driver | None = None,
    ) -> None:
        """`service` and `driver` are built from the settings unless handed in (the tests
        hand in the pipeline's service and a scripted driver)."""
        self._settings = settings
        self._session_factory = session_factory
        if service is None:
            schemas, catalog = build_registry()
            storage = make_storage(settings)
            llm = LLMClient(settings, session_factory, prompt_roots=catalog.prompt_roots)
            tenders = TenderService(
                catalog, ExtractService(llm, storage, schemas, settings), settings.tenant_id
            )
            service = AgentPassService(catalog, schemas, tenders, settings, storage)
            driver = driver or real_driver(settings, session_factory, catalog)
        if driver is None:
            raise ValueError("a service handed in needs its driver")
        self._service = service
        self._driver = driver

    def run_once(self) -> bool:
        with self._session_factory() as session:
            job = jobs.claim_next(session, self._settings.tenant_id, kinds=(JOB_KIND,))
            if job is None:
                return False
            job_id, payload = job.id, dict(job.payload)
        log.info("agent pass %s started", payload.get("agent_run_id"))
        try:
            with self._session_factory() as session:
                self._service.run(session, payload["agent_run_id"], self._driver)
        except Exception:
            with self._session_factory() as session:
                jobs.fail(session, self._settings.tenant_id, job_id, traceback.format_exc())
            log.exception("agent pass job %s failed", job_id)
            return True
        with self._session_factory() as session:
            jobs.complete(session, self._settings.tenant_id, job_id)
        log.info("agent pass job %s done", job_id)
        return True

    def run_forever(self, stop: threading.Event) -> None:
        with self._session_factory() as session:
            orphans = jobs.requeue_orphans(session, self._settings.tenant_id, kinds=(JOB_KIND,))
        if orphans:
            log.warning(
                "%s agent pass job(s) left running by an earlier process were put back", orphans
            )
        log.info("agent polling every %ss", self._settings.worker_poll_seconds)
        while not stop.is_set():
            if not self.run_once():
                stop.wait(self._settings.worker_poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = Settings()
    # Cloud Run runs the agent as a service and probes $PORT; compose sets no port.
    port = os.environ.get("PORT")
    serve_health(int(port) if port else None, name="agent")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    AgentWorker(
        settings, make_session_factory(make_engine(settings), settings.tenant_id)
    ).run_forever(stop)


if __name__ == "__main__":
    main()
