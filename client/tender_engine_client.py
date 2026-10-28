"""A thin Python client of the Tender Intelligence Engine's REST v1 (Stage 7, Block 6 d),
for jouleWise products. Standard library only; one class, one method per operation.

    from tender_engine_client import TenderEngine

    engine = TenderEngine("https://34.131.65.108", api_key="tie_live_…")
    made = engine.submit_tender(source_url="https://www.seci.co.in/…/RfS.pdf", tender_type="solar")
    status = engine.status(made["tender_id"])
    snapshot = engine.fields(made["tender_id"])          # contract v1
    changes = engine.changes(made["tender_id"])
    answer = engine.ask(made["tender_id"], "What is the bid submission deadline?")
    link = engine.review_link(made["tender_id"], "Asha")
    hook = engine.register_webhook("https://my.app/hooks/tender", ["extraction_done"], secret)

Every answer is the API's JSON as a dict. An error answers `TenderEngineError` with the
API's `error_type` and `message`. Nothing here is a fact: `source` on every field says
whether a reviewer approved it; the tender document is the authoritative source.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import ssl
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

__all__ = ["TenderEngine", "TenderEngineError", "verify_webhook"]
__version__ = "1.0.0"


class TenderEngineError(Exception):
    def __init__(self, status: int, error_type: str, message: str) -> None:
        super().__init__(f"{status} {error_type}: {message}")
        self.status = status
        self.error_type = error_type
        self.message = message


def verify_webhook(
    secret: str, signature_header: str, body: bytes, *, tolerance_s: int = 300
) -> bool:
    """True when `X-Tender-Signature` (t=<unix>,v1=<hex>) signs `body` with `secret` and
    was made within `tolerance_s` of now."""
    parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
    try:
        timestamp = int(parts.get("t", ""))
    except ValueError:
        return False
    if abs(time.time() - timestamp) > tolerance_s:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))


class TenderEngine:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = 120.0,
        verify_tls: bool = True,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout_s
        self._context = None if verify_tls else ssl._create_unverified_context()  # noqa: SLF001

    # -- tenders ---------------------------------------------------------------------------

    def submit_tender(
        self,
        *,
        file: str | Path | None = None,
        source_url: str | None = None,
        tender_type: str | None = None,
        agency: str | None = None,
        title: str | None = None,
        external_ref: str | None = None,
        issued_on: str | None = None,
        priority: bool = False,
    ) -> dict[str, Any]:
        """A new tender from its RfS: a local file or the official URL. Needs `write`."""
        fields = {
            "source_url": source_url,
            "tender_type": tender_type,
            "agency": agency,
            "title": title,
            "external_ref": external_ref,
            "issued_on": issued_on,
            "priority": "true" if priority else None,
        }
        return self._multipart("POST", "/api/v1/tenders/submit", fields, file)

    def submit_amendment(
        self,
        tender_id: str,
        *,
        kind: str,
        file: str | Path | None = None,
        source_url: str | None = None,
        issued_on: str | None = None,
        summary_of_change: str | None = None,
        force: bool = False,
        priority: bool = False,
    ) -> dict[str, Any]:
        """A corrigendum, amendment or clarification as the next version. Needs `write`."""
        fields = {
            "kind": kind,
            "source_url": source_url,
            "issued_on": issued_on,
            "summary_of_change": summary_of_change,
            "force": "true" if force else None,
            "priority": "true" if priority else None,
        }
        return self._multipart(
            "POST", f"/api/v1/tenders/{tender_id}/submit-amendment", fields, file
        )

    def status(self, tender_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/v1/tenders/{tender_id}/status")

    def fields(self, tender_id: str) -> dict[str, Any]:
        """The snapshot, contract v1: every field with value, unit, page, quote, version,
        state, approved or machine, and confidence."""
        return self._json("GET", f"/api/v1/tenders/{tender_id}/fields")

    def changes(self, tender_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/v1/tenders/{tender_id}/changes")

    def published(self, tender_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/v1/tenders/{tender_id}/published")

    def ask(self, tender_id: str, question: str) -> dict[str, Any]:
        """One question about the tender; never a fact. Needs `model`."""
        return self._json("POST", f"/api/v1/tenders/{tender_id}/ask", {"question": question})

    def ask_across(self, question: str | None = None, **query: Any) -> dict[str, Any]:
        """Which tenders satisfy a condition on one field, over approved facts. Send a
        `question`, or `field_path`, `operator` and `value`. Needs `model`."""
        return self._json("POST", "/api/v1/tenders/ask", {"question": question, **query})

    def review_link(self, tender_id: str, reviewer_name: str) -> dict[str, Any]:
        """A review link for a named reviewer: a credential, hand it over and store it
        nowhere. Needs `review:mint`."""
        return self._json(
            "POST", f"/api/v1/tenders/{tender_id}/review-link", {"reviewer_name": reviewer_name}
        )

    def wait_until_done(
        self, tender_id: str, *, poll_s: float = 30.0, timeout_s: float = 7200.0
    ) -> dict[str, Any]:
        """Poll the status until the reading is done or a version failed."""
        deadline = time.time() + timeout_s
        while True:
            status = self.status(tender_id)
            if status["extraction_done"] or any(v["stage"] == "failed" for v in status["versions"]):
                return status
            if time.time() > deadline:
                raise TimeoutError(f"tender {tender_id} not done after {timeout_s} s")
            time.sleep(poll_s)

    # -- webhooks ----------------------------------------------------------------------------

    def register_webhook(
        self, url: str, events: list[str], secret: str, description: str | None = None
    ) -> dict[str, Any]:
        """Needs `write`. Events: extraction_done, review_complete, new_version,
        amendment_detected. Verify deliveries with `verify_webhook`."""
        body = {"url": url, "events": events, "secret": secret, "description": description}
        return self._json("POST", "/api/v1/webhooks", body)

    def webhooks(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = self._json("GET", "/api/v1/webhooks")
        return out

    def deliveries(self, endpoint_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = self._json("GET", f"/api/v1/webhooks/{endpoint_id}/deliveries")
        return out

    def deactivate_webhook(self, endpoint_id: str) -> dict[str, Any]:
        return self._json("DELETE", f"/api/v1/webhooks/{endpoint_id}")

    # -- plumbing ------------------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "X-Public-Request": "1",
            "Accept": "application/json",
            "User-Agent": f"tender-engine-client/{__version__}",
        }

    def _json(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None
        headers = self._headers()
        if body is not None:
            data = json.dumps({k: v for k, v in body.items() if v is not None}).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return self._send(method, path, data, headers)

    def _multipart(
        self, method: str, path: str, fields: dict[str, str | None], file: str | Path | None
    ) -> Any:
        boundary = f"----tender-engine-{uuid.uuid4().hex}"
        parts: list[bytes] = []
        for name, value in fields.items():
            if value is None:
                continue
            head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            parts.append(f"{head}{value}\r\n".encode())
        if file is not None:
            source = Path(file)
            kind = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            parts.append(
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                    f'filename="{source.name}"\r\nContent-Type: {kind}\r\n\r\n'
                ).encode()
                + source.read_bytes()
                + b"\r\n"
            )
        parts.append(f"--{boundary}--\r\n".encode())
        headers = {**self._headers(), "Content-Type": f"multipart/form-data; boundary={boundary}"}
        return self._send(method, path, b"".join(parts), headers)

    def _send(self, method: str, path: str, data: bytes | None, headers: dict[str, str]) -> Any:
        request = urllib.request.Request(
            self._base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout, context=self._context
            ) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {}
            raise TenderEngineError(
                exc.code,
                str(payload.get("error_type") or "http_error"),
                str(payload.get("message") or raw[:300].decode("utf-8", "replace")),
            ) from None
