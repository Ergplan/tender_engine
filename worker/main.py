"""Worker entrypoint: build the runner and poll the job table until told to stop."""

import logging
import signal
import threading

from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.schemas import SchemaRegistry
from core.storage import make_storage
from worker.runner import Runner


def build_runner(settings: Settings) -> Runner:
    session_factory = make_session_factory(make_engine(settings))
    return Runner(
        settings,
        session_factory,
        make_storage(settings),
        SchemaRegistry(),
        LLMClient(settings, session_factory),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    build_runner(Settings()).run_forever(stop)


if __name__ == "__main__":
    main()
