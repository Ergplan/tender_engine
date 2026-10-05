"""The worker of the browser-test stack (`make test-ui`): the real job runner with a
scripted model, so that what the reviewer screen sets in motion (the summary written again
after a correction) happens there too.

  python -m tests.e2e.scripted_worker
"""

import signal
import threading

from core.config import Settings
from tests.e2e.seed_review import build_runner
from tests.fixtures.llm import ScriptedSDK
from tests.fixtures.tenders import RFS_ANSWERS


def main() -> None:
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    settings = Settings().model_copy(update={"worker_poll_seconds": 1.0})
    runner, _, _ = build_runner(settings, ScriptedSDK(dict(RFS_ANSWERS)))
    runner.run_forever(stop)


if __name__ == "__main__":
    main()
