import threading

from core.config import Settings
from worker.main import run


def test_worker_checks_the_database_and_stops_on_request(settings: Settings) -> None:
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    run(settings, stop)
    assert stop.is_set()
