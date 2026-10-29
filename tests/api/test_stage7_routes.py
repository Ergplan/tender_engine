"""The Stage 7 routes the independent review of 2026-10-29 found without an API test
(operating rule 15 b): the bundle upload, the classifier queue, the amendment link and the
type a person sets."""

import io
import zipfile
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Job
from tests.api.test_tenders import create
from tests.conftest import Pipeline
from tests.fixtures.pdfs import make_pdf

MISSING = "0" * 32


def _zip(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return out.getvalue()


def _parsed_document(client: TestClient, pipeline: Pipeline, pages: Any = None) -> str:
    made = client.post(
        "/api/v1/documents",
        files={"file": ("amendment.pdf", make_pdf(pages), "application/pdf")},
    )
    assert made.status_code == 201, made.text
    pipeline.runner.run_until_idle()
    document_id: str = made.json()["id"]
    assert client.get(f"/api/v1/documents/{document_id}").json()["status"] == "parsed"
    return document_id


def test_a_bundle_upload_makes_documents_and_names_what_it_left_out(client: TestClient) -> None:
    bundle = _zip(
        {
            "pack/RfS.pdf": make_pdf(),
            "pack/scan.jpg": b"\xff\xd8\xff\xe0" + b"\0" * 32,
        }
    )
    made = client.post(
        "/api/v1/documents/bundle",
        files={"file": ("pack.zip", bundle, "application/zip")},
        data={"source_url": "https://www.seci.co.in/tenders/pack.zip"},
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert [(m["name"], m["created"]) for m in body["documents"]] == [("pack/RfS.pdf", True)]
    assert body["documents"][0]["document"]["source_url"] == (
        "https://www.seci.co.in/tenders/pack.zip"
    )
    assert [r["name"] for r in body["rejected"]] == ["pack/scan.jpg"]
    again = client.post(
        "/api/v1/documents/bundle", files={"file": ("pack.zip", bundle, "application/zip")}
    )
    assert again.status_code == 201 and again.json()["documents"][0]["created"] is False
    broken = client.post(
        "/api/v1/documents/bundle",
        files={"file": ("pack.zip", b"PK\x03\x04not a zip", "application/zip")},
    )
    assert broken.status_code == 422 and broken.json()["error_type"] == "validation_failed"


def test_classify_queues_one_job_for_a_parsed_document_only(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    unparsed = client.post(
        "/api/v1/documents", files={"file": ("x.pdf", make_pdf(), "application/pdf")}
    ).json()
    refused = client.post(f"/api/v1/documents/{unparsed['id']}/classify")
    assert refused.status_code == 422 and "not parsed" in refused.json()["detail"]
    assert client.post(f"/api/v1/documents/{MISSING}/classify").status_code == 404
    pipeline.runner.run_until_idle()
    queued = client.post(f"/api/v1/documents/{unparsed['id']}/classify")
    assert queued.status_code == 202, queued.text
    assert queued.json()["id"] == unparsed["id"]
    jobs = db.scalars(select(Job).where(Job.kind == "classify_type")).all()
    assert [j.payload["document_id"] for j in jobs if j.status == "queued"] == [unparsed["id"]]


def test_link_amendment_answers_without_writing(client: TestClient, pipeline: Pipeline) -> None:
    create(client)
    document_id = _parsed_document(client, pipeline)
    linked = client.post(f"/api/v1/documents/{document_id}/link-amendment")
    assert linked.status_code == 200, linked.text
    body = linked.json()
    assert set(body) >= {"state", "tender_id", "confidence", "method", "candidates", "reason"}
    assert body["state"] in ("linked", "ask", "none")
    tenders = client.get("/api/v1/tenders").json()
    assert all(t["current_version_no"] is None for t in tenders), "nothing was attached"
    assert client.post(f"/api/v1/documents/{MISSING}/link-amendment").status_code == 404


def test_link_amendment_refuses_an_unparsed_document(client: TestClient) -> None:
    made = client.post(
        "/api/v1/documents", files={"file": ("y.pdf", make_pdf(), "application/pdf")}
    ).json()
    refused = client.post(f"/api/v1/documents/{made['id']}/link-amendment")
    assert refused.status_code == 422 and "not parsed" in refused.json()["detail"]


def test_a_person_sets_the_type_of_an_unread_tender(
    client: TestClient,
) -> None:
    tender = create(client)
    changed = client.post(
        f"/api/v1/tenders/{tender['id']}/type",
        json={"type": "wind"},
        headers={"X-Reviewer": "Asha"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["tender_type"] == "wind"
    unknown = client.post(f"/api/v1/tenders/{tender['id']}/type", json={"type": "nuclear"})
    assert unknown.status_code == 422 and "unknown tender type" in unknown.json()["detail"]
    assert client.post(f"/api/v1/tenders/{MISSING}/type", json={"type": "wind"}).status_code == 404
