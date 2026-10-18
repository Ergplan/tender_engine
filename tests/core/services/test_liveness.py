"""The health listener the polling processes offer Cloud Run."""

import json
import urllib.request

from core.services.liveness import serve_health


def test_health_answers_on_the_port_and_nothing_else() -> None:
    server = serve_health(0, name="worker")
    assert server is not None
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as response:
            assert response.status == 200
            assert json.loads(response.read()) == {"status": "ok", "process": "worker"}
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/other")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("only /health is served")
    finally:
        server.shutdown()
        server.server_close()


def test_no_port_means_no_listener() -> None:
    assert serve_health(None, name="agent") is None
