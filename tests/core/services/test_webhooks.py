"""Webhooks (Stage 7, Block 6 b): registration, the events, signed delivery, retries."""

import json
import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Job, WebhookDelivery
from core.services import webhooks
from tender.models import Tender
from tests.conftest import Pipeline
from tests.fixtures.tenders import amended_tender, extracted_tender

SECRET = "s3cret-s3cret-s3cret"


def _endpoint(
    pipeline: Pipeline, db: Session, events: list[str], url: str = "https://acme.test/hook"
):  # type: ignore[no-untyped-def]
    return webhooks.register(
        db,
        tenant_id=pipeline.settings.tenant_id,
        url=url,
        events=events,
        secret=SECRET,
        created_by="pytest",
    )


def test_signature_round_trip_and_tolerance() -> None:
    body = b'{"event":"extraction_done"}'
    header = webhooks.sign(SECRET, int(time.time()), body)
    assert header.startswith("t=") and ",v1=" in header
    assert webhooks.verify(SECRET, header, body)
    assert not webhooks.verify("other-secret-other", header, body)
    assert not webhooks.verify(SECRET, header, body + b" ")
    stale = webhooks.sign(SECRET, int(time.time()) - 3600, body)
    assert not webhooks.verify(SECRET, stale, body)
    assert not webhooks.verify(SECRET, "garbage", body)


def test_registration_checks_events_url_and_secret(pipeline: Pipeline, db: Session) -> None:
    with pytest.raises(webhooks.WebhookError, match="events must be among"):
        _endpoint(pipeline, db, ["no_such_event"])
    with pytest.raises(webhooks.WebhookError, match="http"):
        _endpoint(pipeline, db, ["new_version"], url="ftp://x")
    with pytest.raises(webhooks.WebhookError, match="secret"):
        webhooks.register(
            db,
            tenant_id=pipeline.settings.tenant_id,
            url="https://acme.test/h",
            events=["new_version"],
            secret="short",
            created_by="pytest",
        )
    row = _endpoint(pipeline, db, ["new_version", "new_version", "review_complete"])
    assert row.events == ["new_version", "review_complete"] and row.active


def test_an_event_queues_one_signed_delivery_per_subscribed_endpoint(
    pipeline: Pipeline, db: Session
) -> None:
    wants = _endpoint(pipeline, db, ["new_version", "extraction_done"])
    other = _endpoint(pipeline, db, ["review_complete"], url="https://acme.test/other")
    off = _endpoint(pipeline, db, ["new_version"], url="https://acme.test/off")
    webhooks.deactivate(db, tenant_id=pipeline.settings.tenant_id, endpoint_id=off.id, by="pytest")
    # A tender's first version is an event; its reading settling is another.
    tender = extracted_tender(pipeline, db)
    rows = list(db.scalars(select(WebhookDelivery).order_by(WebhookDelivery.created_at)))
    assert [(r.endpoint_id, r.event) for r in rows] == [
        (wants.id, "new_version"),
        (wants.id, "extraction_done"),
    ], "the other endpoint wants other events; the deactivated one gets nothing"
    assert all(r.status == "delivered" and r.attempts == 1 for r in rows)
    sent = pipeline.webhooks.requests
    assert [r.headers["X-Tender-Event"] for r in sent] == ["new_version", "extraction_done"]
    for request, row in zip(sent, rows, strict=True):
        assert request.url == "https://acme.test/hook"
        assert request.headers["X-Tender-Delivery"] == row.id
        assert webhooks.verify(SECRET, request.headers["X-Tender-Signature"], request.content)
        payload = json.loads(request.content)
        assert payload["tender_id"] == tender.id and payload["event"] == row.event
    assert other.id not in {r.endpoint_id for r in rows}


def test_a_failing_receiver_is_retried_with_backoff_and_then_given_up(
    pipeline: Pipeline, db: Session
) -> None:
    _endpoint(pipeline, db, ["new_version"])
    pipeline.webhooks.status = 503
    extracted_tender(pipeline, db)
    delivery = db.scalars(select(WebhookDelivery)).one()
    job = db.scalars(select(Job).where(Job.kind == webhooks.JOB_KIND)).one()
    assert delivery.status == "pending" and delivery.attempts == 1
    assert delivery.last_status == 503 and delivery.last_error == "HTTP 503"
    assert (
        job.status == "queued" and job.attempts == 1 and job.max_attempts == webhooks.MAX_ATTEMPTS
    )
    # Every retry is due now for the test; the receiver stays down.
    for expected in range(2, webhooks.MAX_ATTEMPTS + 1):
        job.run_after = job.created_at
        db.commit()
        pipeline.runner.run_until_idle()
        db.refresh(delivery)
        db.refresh(job)
        assert delivery.attempts == expected
    assert delivery.status == "failed" and job.status == "failed"
    assert len(pipeline.webhooks.requests) == webhooks.MAX_ATTEMPTS
    # Nothing changes about the tender itself.
    assert db.scalars(select(Job).where(Job.status == "failed")).one().kind == webhooks.JOB_KIND


def test_review_complete_and_amendment_events_carry_the_tender(
    pipeline: Pipeline, db: Session
) -> None:
    _endpoint(pipeline, db, ["review_complete", "new_version"])
    from tests.tender.test_rounds import reviewed_tender

    tender_id, _ = reviewed_tender(pipeline, db)
    pipeline.runner.run_until_idle()  # the delivery of the completion
    events = [r.headers["X-Tender-Event"] for r in pipeline.webhooks.requests]
    assert events == ["new_version", "review_complete"]
    done = json.loads(pipeline.webhooks.requests[-1].content)
    assert done["tender_id"] == tender_id and done["reviewer"] == "Asha"
    tender = db.get(Tender, tender_id)
    assert tender is not None
    amended_tender(pipeline, db, tender)
    events = [r.headers["X-Tender-Event"] for r in pipeline.webhooks.requests]
    assert events[-1] == "new_version"
    assert json.loads(pipeline.webhooks.requests[-1].content)["version_no"] == 2
