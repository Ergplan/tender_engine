"""Worker entrypoint: build the runner and poll the job table until told to stop."""

import logging
import os
import signal
import threading
from pathlib import Path

import agent.models  # noqa: F401  (registers the agent pass tables on Base.metadata)
import tender.models  # noqa: F401  (registers the tender tables on Base.metadata)
from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.services.extract import ExtractService
from core.services.liveness import serve_health
from core.storage import make_storage
from tender.services import freshness
from tender.services.packs import build_registry
from tender.services.worker_jobs import tender_jobs
from worker.runner import Runner


def build_runner(settings: Settings) -> Runner:
    session_factory = make_session_factory(make_engine(settings), settings.tenant_id)
    schemas, catalog = build_registry()
    storage = make_storage(settings)
    llm = LLMClient(settings, session_factory, prompt_roots=catalog.prompt_roots)
    handlers, after_validation = tender_jobs(
        llm,
        catalog,
        ExtractService(llm, storage, schemas, settings),
        schemas,
        settings.tenant_id,
        tenders_root=Path(settings.tenders_root),
        freshness_interval_days=settings.freshness_interval_days,
    )
    # The weekly freshness check: one is queued when none is pending, so a worker that
    # starts on a fresh database checks the corpus at once and then every interval.
    if settings.freshness_interval_days > 0:
        with session_factory() as session:
            freshness.ensure_scheduled(session, settings.tenant_id)
    return Runner(settings, session_factory, storage, schemas, llm, handlers, after_validation)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    # Cloud Run runs the worker as a service and probes $PORT; compose sets no port.
    port = os.environ.get("PORT")
    serve_health(int(port) if port else None, name="worker")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    build_runner(Settings()).run_forever(stop)


if __name__ == "__main__":
    main()
