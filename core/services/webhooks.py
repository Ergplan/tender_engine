"""Webhooks (Stage 7, Block 6 b): a caller registers a URL for events, the engine records
one delivery per event and endpoint, and the worker delivers it signed and retries with
backoff. Events: `extraction_done` (every run of a tender settled, the summary queued),
`review_complete` (a review completed), `new_version` (a version added to a tender),
`amendment_detected` (the freshness check found a new document on the source page; it
ingests nothing). Nothing here reads or writes a fact.

Signature: `X-Tender-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<body>">`
with the endpoint's secret; the receiver recomputes it over the raw body (`verify`)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import WebhookDelivery, WebhookEndpoint
from core.services import audit, jobs

log = logging.getLogger("webhooks")
EVENTS = ("extraction_done", "review_complete", "new_version", "amendment_detected")
JOB_KIND = "webhook_deliver"
MAX_ATTEMPTS = 6
TIMEOUT_S = 15.0
ACTOR = "webhooks"
MIN_SECRET = 16


class WebhookError(Exception):
    pass


class WebhookDeliveryError(Exception):
    """A delivery attempt that did not get a 2xx; the job machinery retries it."""


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify(secret: str, header: str, body: bytes, *, tolerance_s: int = 300) -> bool:
    """What a receiver does: the header's timestamp within tolerance and the HMAC equal."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        timestamp = int(parts.get("t", ""))
    except ValueError:
        return False
    if abs(time.time() - timestamp) > tolerance_s:
        return False
    expected = sign(secret, timestamp, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))


def register(
    session: Session,
    *,
    tenant_id: str,
    url: str,
    events: list[str],
    secret: str,
    created_by: str,
    description: str | None = None,
) -> WebhookEndpoint:
    unknown = sorted(set(events) - set(EVENTS))
    if unknown or not events:
        raise WebhookError(f"events must be among {list(EVENTS)}; got {unknown or events}")
    if not (url.startswith("https://") or url.startswith("http://")):
        raise WebhookError("the URL must be http(s)")
    if len(secret) < MIN_SECRET:
        raise WebhookError(f"the secret must be at least {MIN_SECRET} characters")
    row = WebhookEndpoint(
        tenant_id=tenant_id,
        created_by=created_by,
        url=url,
        events=sorted(set(events)),
        secret=secret,
        description=description,
        active=True,
    )
    session.add(row)
    session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=created_by,
        action="insert",
        table_name="webhook_endpoint",
        row_id=row.id,
        after={"url": url, "events": row.events},
    )
    session.commit()
    return row


def endpoints(session: Session, tenant_id: str) -> list[WebhookEndpoint]:
    return list(
        session.scalars(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.tenant_id == tenant_id)
            .order_by(WebhookEndpoint.created_at)
        )
    )


def deactivate(
    session: Session, *, tenant_id: str, endpoint_id: str, by: str
) -> WebhookEndpoint | None:
    row = session.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id, WebhookEndpoint.tenant_id == tenant_id
        )
    )
    if row is None:
        return None
    if row.active:
        row.active = False
        audit.record(
            session,
            tenant_id=tenant_id,
            actor=by,
            action="update",
            table_name="webhook_endpoint",
            row_id=row.id,
            before={"active": True},
            after={"active": False},
        )
        session.commit()
    return row


def emit(
    session: Session,
    *,
    tenant_id: str,
    event: str,
    payload: dict[str, Any],
    created_by: str = ACTOR,
) -> list[WebhookDelivery]:
    """One delivery per active endpoint subscribed to the event, each queued as a job.
    Commits nothing: the caller's transaction carries the rows with its own change, so an
    event is never sent for a change that was rolled back."""
    if event not in EVENTS:
        raise WebhookError(f"unknown event {event!r}")
    deliveries = []
    for endpoint in session.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.tenant_id == tenant_id, WebhookEndpoint.active.is_(True)
        )
    ):
        if event not in endpoint.events:
            continue
        delivery = WebhookDelivery(
            tenant_id=tenant_id,
            created_by=created_by,
            endpoint_id=endpoint.id,
            event=event,
            payload={"event": event, "occurred_at": datetime.now(UTC).isoformat(), **payload},
            status="pending",
            attempts=0,
        )
        session.add(delivery)
        session.flush()
        job = jobs.enqueue(
            session,
            tenant_id=tenant_id,
            kind=JOB_KIND,
            payload={"delivery_id": delivery.id},
            created_by=created_by,
        )
        job.max_attempts = MAX_ATTEMPTS
        deliveries.append(delivery)
    return deliveries


def deliveries(
    session: Session, tenant_id: str, endpoint_id: str | None = None, limit: int = 100
) -> list[WebhookDelivery]:
    query = (
        select(WebhookDelivery)
        .where(WebhookDelivery.tenant_id == tenant_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    )
    if endpoint_id:
        query = query.where(WebhookDelivery.endpoint_id == endpoint_id)
    return list(session.scalars(query))


class Deliverer:
    """What the worker runs: one attempt per job run."""

    def __init__(self, tenant_id: str, transport: httpx2.BaseTransport | None = None) -> None:
        self._tenant_id = tenant_id
        self._transport = transport

    def deliver(self, session: Session, delivery_id: str) -> WebhookDelivery:
        """A 2xx marks the delivery `delivered`; anything else records the status and
        raises WebhookDeliveryError so the job is retried with backoff, until MAX_ATTEMPTS
        when the delivery is `failed`."""
        delivery = session.scalar(
            select(WebhookDelivery).where(
                WebhookDelivery.id == delivery_id, WebhookDelivery.tenant_id == self._tenant_id
            )
        )
        if delivery is None:
            raise LookupError(f"delivery {delivery_id} not found")
        endpoint = session.get(WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None or not endpoint.active:
            delivery.status = "cancelled"
            session.commit()
            return delivery
        body = json.dumps(delivery.payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        timestamp = int(time.time())
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "tender-engine-webhooks/1",
            "X-Tender-Event": delivery.event,
            "X-Tender-Delivery": delivery.id,
            "X-Tender-Signature": sign(endpoint.secret, timestamp, body),
        }
        delivery.attempts += 1
        delivery.last_attempt_at = datetime.now(UTC)
        error: str | None
        try:
            with httpx2.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
                response = client.post(endpoint.url, content=body, headers=headers)
            delivery.last_status = response.status_code
            ok = 200 <= response.status_code < 300
            error = None if ok else f"HTTP {response.status_code}"
        except httpx2.HTTPError as exc:
            delivery.last_status = None
            ok, error = False, f"{type(exc).__name__}: {exc}"
        if ok:
            delivery.status = "delivered"
            delivery.delivered_at = datetime.now(UTC)
            delivery.last_error = None
            session.commit()
            return delivery
        delivery.last_error = error
        delivery.status = "failed" if delivery.attempts >= MAX_ATTEMPTS else "pending"
        session.commit()
        log.warning("webhook delivery %s attempt %d: %s", delivery.id, delivery.attempts, error)
        raise WebhookDeliveryError(error or "delivery failed")


def job_handlers(deliverer: Deliverer) -> dict[str, Callable[[Session, dict[str, Any]], None]]:
    def deliver(session: Session, payload: dict[str, Any]) -> None:
        deliverer.deliver(session, payload["delivery_id"])

    return {JOB_KIND: deliver}
