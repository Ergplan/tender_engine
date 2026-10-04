"""Worker entrypoint. Stage 0B: connect, report ready, idle. The job chain arrives in Stage 1."""

import logging
import signal
import threading

from sqlalchemy import text

from core.config import Settings
from core.db import make_engine

log = logging.getLogger("worker")
HEARTBEAT_SECONDS = 60.0


def run(settings: Settings, stop: threading.Event) -> None:
    engine = make_engine(settings)
    try:
        while not stop.is_set():
            with engine.connect() as conn:
                conn.execute(text("select 1"))
            log.info("worker idle: database reachable, no job table until Stage 1")
            stop.wait(HEARTBEAT_SECONDS)
    finally:
        engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run(Settings(), stop)


if __name__ == "__main__":
    main()
