"""A health listener for the processes that poll rather than serve (worker, agent).

Cloud Run runs them as services and expects something to answer on $PORT; compose does
not. `serve_health` starts a thread answering `GET /health` with a short JSON body on the
given port and returns the server, or None when no port is given.
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

log = logging.getLogger("liveness")


def serve_health(port: int | None, *, name: str) -> ThreadingHTTPServer | None:
    """Answer health probes on `port` from a daemon thread; nothing when port is None."""
    if port is None:
        return None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            if self.path != "/health":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"status": "ok", "process": name}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, name=f"{name}-health", daemon=True)
    thread.start()
    log.info("%s answering /health on port %s", name, port)
    return server
