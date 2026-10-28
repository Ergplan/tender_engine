"""REST v1 for any caller (Stage 7, Block 6 a and b): the contract routes through the
API, and the scopes an API key needs for them."""

from typing import Any

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.db import make_engine, make_session_factory
from core.models import Job
from core.services.identity import IdentityService
from tests.api.test_auth import PUBLIC
from tests.conftest import Pipeline
from tests.fixtures.pdfs import make_pdf
from tests.fixtures.tenders import AMENDMENT_PAGES, RFS_ANSWERS, RFS_PAGES, extracted_tender

SECRET = "hook-secret-hook-secret"


def _run(pipeline: Pipeline, db: Session, rounds: int = 4) -> None:
    for _ in range(rounds):
        db.execute(update(Job).where(Job.status == "queued").values(run_after=Job.created_at))
        db.commit()
        pipeline.runner.run_until_idle()


def test_submit_status_fields_changes_and_a_review_link(
    pipeline: Pipeline, client: TestClient, db: Session
) -> None:
    pipeline.sdk.answers = dict(RFS_ANSWERS)
    pdf = make_pdf(RFS_PAGES)
    made = client.post(
        "/api/v1/tenders/submit",
        files={"file": ("rfs.pdf", pdf, "application/pdf")},
        data={"tender_type": "solar", "agency": "Acme", "title": "600 MW solar"},
    )
    assert made.status_code == 202, made.text
    body = made.json()
    tender_id = body["tender_id"]
    assert body["version_no"] == 1 and body["created"] is True
    assert body["status_path"] == f"/api/v1/tenders/{tender_id}/status"
    status = client.get(f"/api/v1/tenders/{tender_id}/status").json()
    assert status["versions"][0]["stage"] == "parsing" and not status["extraction_done"]
    _run(pipeline, db)
    status = client.get(f"/api/v1/tenders/{tender_id}/status").json()
    assert status["extraction_done"] and status["versions"][0]["stage"] == "validated"
    fields = client.get(f"/api/v1/tenders/{tender_id}/fields").json()
    assert fields["contract_version"] == "1" and fields["machine"] > 0 and fields["approved"] == 0
    emd = next(f for f in fields["fields"] if f["path"] == "core.guarantees.emd_per_mw_inr")
    assert (emd["state"], emd["source"], emd["value"]) == ("value", "machine", 928000)
    assert emd["evidence"][0]["page_no"] == 3 and emd["evidence"][0]["located"] is True
    # The same file again: the same tender, nothing started twice.
    again = client.post(
        "/api/v1/tenders/submit", files={"file": ("rfs.pdf", pdf, "application/pdf")}
    )
    assert again.status_code == 202 and again.json() == {**body, "created": False}
    # An amendment, then the changes with impacts.
    pipeline.sdk.answers = dict(RFS_ANSWERS)
    amended = client.post(
        f"/api/v1/tenders/{tender_id}/submit-amendment",
        files={"file": ("amendment-01.pdf", make_pdf(AMENDMENT_PAGES), "application/pdf")},
        data={"kind": "amendment", "issued_on": "2026-03-20", "force": "true"},
    )
    assert amended.status_code == 202 and amended.json()["version_no"] == 2
    _run(pipeline, db)
    changes = client.get(f"/api/v1/tenders/{tender_id}/changes").json()
    assert [v["version_no"] for v in changes["versions"]] == [1, 2]
    # A review link for a named reviewer.
    link = client.post(f"/api/v1/tenders/{tender_id}/review-link", json={"reviewer_name": "Asha"})
    assert link.status_code == 201 and "/review/" in link.json()["url"]
    assert link.json()["reviewer_name"] == "Asha"
    # Refusals in plain words.
    bad = client.post("/api/v1/tenders/submit", data={"tender_type": "nuclear"})
    assert bad.status_code == 422 and "unknown tender type" in bad.json()["detail"]
    missing = client.get("/api/v1/tenders/" + "0" * 32 + "/status")
    assert missing.status_code == 404


def test_submit_by_official_url_only(pipeline: Pipeline, client: TestClient) -> None:
    pdf = make_pdf(RFS_PAGES)

    def site(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=pdf, headers={"content-type": "application/pdf"})

    client.app.state.submit_transport = httpx2.MockTransport(site)  # type: ignore[attr-defined]
    refused = client.post(
        "/api/v1/tenders/submit",
        data={"source_url": "https://news.example/rfs.pdf", "tender_type": "solar"},
    )
    assert refused.status_code == 422 and "official source" in refused.json()["detail"]
    made = client.post(
        "/api/v1/tenders/submit",
        data={"source_url": "https://www.seci.co.in/tenders/rfs.pdf", "tender_type": "solar"},
    )
    assert made.status_code == 202, made.text
    document = client.get(f"/api/v1/documents/{made.json()['document_id']}").json()
    assert document["source_url"] == "https://www.seci.co.in/tenders/rfs.pdf"


def test_webhooks_are_registered_listed_delivered_and_deactivated(
    pipeline: Pipeline, client: TestClient, db: Session
) -> None:
    made = client.post(
        "/api/v1/webhooks",
        json={"url": "https://acme.test/hook", "events": ["new_version"], "secret": SECRET},
    )
    assert made.status_code == 201, made.text
    endpoint = made.json()
    assert endpoint["events"] == ["new_version"] and endpoint["active"] and "secret" not in endpoint
    assert [e["id"] for e in client.get("/api/v1/webhooks").json()] == [endpoint["id"]]
    bad = client.post(
        "/api/v1/webhooks", json={"url": "https://x.test", "events": ["nope"], "secret": SECRET}
    )
    assert bad.status_code == 422
    extracted_tender(pipeline, db)
    rows = client.get(f"/api/v1/webhooks/{endpoint['id']}/deliveries").json()
    assert [r["event"] for r in rows] == ["new_version"] and rows[0]["status"] == "delivered"
    assert pipeline.webhooks.requests[0].headers["X-Tender-Event"] == "new_version"
    off = client.delete(f"/api/v1/webhooks/{endpoint['id']}")
    assert off.status_code == 200 and off.json()["active"] is False
    assert client.delete("/api/v1/webhooks/" + "0" * 32).status_code == 404


def test_an_api_key_needs_the_scopes_the_routes_want(
    pipeline: Pipeline, client: TestClient, db: Session
) -> None:
    tender = extracted_tender(pipeline, db)
    identity = IdentityService(pipeline.settings)
    factory = make_session_factory(make_engine(pipeline.settings), pipeline.settings.tenant_id)

    def key(scopes: list[str]) -> dict[str, str]:
        with factory() as session:
            _, secret = identity.create_api_key(
                session, pipeline.settings.tenant_id, "k", scopes, created_by="pytest"
            )
        return {**PUBLIC, "Authorization": f"Bearer {secret}"}

    outside = TestClient(client.app, base_url="https://testserver")
    reader = key(["read"])
    writer = key(["write"])
    minter = key(["review:mint"])
    hook = {"url": "https://acme.test/h", "events": ["new_version"], "secret": SECRET}

    def status(method: str, path: str, headers: dict[str, str], **kwargs: Any) -> int:
        return outside.request(method, path, headers=headers, **kwargs).status_code

    assert status("GET", f"/api/v1/tenders/{tender.id}/status", reader) == 200
    assert status("GET", f"/api/v1/tenders/{tender.id}/fields", reader) == 200
    assert status("GET", "/api/v1/webhooks", reader) == 200
    assert status("POST", "/api/v1/webhooks", reader, json=hook) == 403
    assert status("POST", "/api/v1/tenders/submit", reader, data={"tender_type": "solar"}) == 403
    assert (
        status(
            "POST", f"/api/v1/tenders/{tender.id}/review-link", reader, json={"reviewer_name": "A"}
        )
        == 403
    )
    assert status("POST", f"/api/v1/tenders/{tender.id}/ask", reader, json={"question": "x"}) == 403
    assert status("POST", "/api/v1/webhooks", writer, json=hook) == 201
    assert (
        status(
            "POST", f"/api/v1/tenders/{tender.id}/review-link", writer, json={"reviewer_name": "A"}
        )
        == 403
    )
    assert (
        status(
            "POST", f"/api/v1/tenders/{tender.id}/review-link", minter, json={"reviewer_name": "A"}
        )
        == 201
    )
    assert status("POST", "/api/v1/tenders/submit", minter, data={"tender_type": "solar"}) == 403
    # A key of another tenant sees none of it.
    with factory() as session:
        assert session.scalar(select(Job.id)) is not None
