from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.models import Document
from tests.conftest import Pipeline
from tests.fixtures.pdfs import make_pdf


def upload(client: TestClient, data: bytes | None = None, name: str = "contract.pdf") -> dict:
    response = client.post(
        "/api/v1/documents",
        files={"file": (name, data if data is not None else make_pdf(), "application/pdf")},
        headers={"X-Reviewer": "Asha"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_upload_returns_201_then_200_for_the_same_file(client: TestClient) -> None:
    data = make_pdf()
    first = client.post("/api/v1/documents", files={"file": ("a.pdf", data, "application/pdf")})
    assert first.status_code == 201
    body = first.json()
    assert body["status"] == "uploaded" and body["filename"] == "a.pdf"
    assert body["page_count"] is None and body["created_by"] == "api" and len(body["sha256"]) == 64
    second = client.post("/api/v1/documents", files={"file": ("b.pdf", data, "application/pdf")})
    assert second.status_code == 200 and second.json()["id"] == body["id"]


def test_upload_records_the_reviewer_when_given(client: TestClient) -> None:
    assert upload(client)["created_by"] == "Asha"


def test_upload_records_where_the_file_came_from_and_when(client: TestClient) -> None:
    data = make_pdf()
    bare = client.post("/api/v1/documents", files={"file": ("a.pdf", data, "application/pdf")})
    assert bare.status_code == 201
    assert bare.json()["source_url"] is None and bare.json()["retrieved_on"] is None
    sourced = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", data, "application/pdf")},
        data={
            "source_url": "https://cercind.gov.in/2026/orders/31-AT-2026.pdf",
            "retrieved_on": "2026-10-07",
        },
    )
    assert sourced.status_code == 200, "the same file: the first document, now with its source"
    body = sourced.json()
    assert body["id"] == bare.json()["id"]
    assert body["source_url"] == "https://cercind.gov.in/2026/orders/31-AT-2026.pdf"
    assert body["retrieved_on"] == "2026-10-07"
    assert client.get(f"/api/v1/documents/{body['id']}").json()["retrieved_on"] == "2026-10-07"


def test_a_malformed_retrieval_date_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", make_pdf(), "application/pdf")},
        data={"retrieved_on": "7 October 2026"},
    )
    assert response.status_code == 422


def test_upload_of_a_non_pdf_is_422_with_a_typed_error(client: TestClient) -> None:
    response = client.post("/api/v1/documents", files={"file": ("a.txt", b"hello", "text/plain")})
    assert response.status_code == 422
    assert response.json()["error_type"] == "validation_failed"
    assert response.json()["detail"] == "the file is not a PDF"


def test_upload_without_a_file_is_422(client: TestClient) -> None:
    assert client.post("/api/v1/documents").status_code == 422


def test_get_document_shows_status_and_page_count_after_parsing(
    client: TestClient, pipeline: Pipeline
) -> None:
    document = upload(client)
    pipeline.runner.run_until_idle()
    body = client.get(f"/api/v1/documents/{document['id']}").json()
    assert (body["status"], body["page_count"], body["error"]) == ("parsed", 3, None)
    assert client.get("/api/v1/documents/" + "0" * 32).status_code == 404


def test_page_render_is_a_png_and_missing_pages_are_404(
    client: TestClient, pipeline: Pipeline
) -> None:
    document = upload(client)
    before = client.get(f"/api/v1/documents/{document['id']}/pages/1/render")
    assert before.status_code == 404
    pipeline.runner.run_until_idle()
    render = client.get(f"/api/v1/documents/{document['id']}/pages/2/render")
    assert render.status_code == 200 and render.headers["content-type"] == "image/png"
    assert render.content.startswith(b"\x89PNG") and "max-age" in render.headers["cache-control"]
    assert client.get(f"/api/v1/documents/{document['id']}/pages/9/render").status_code == 404
    assert client.get("/api/v1/documents/" + "0" * 32 + "/pages/1/render").status_code == 404
    assert client.get(f"/api/v1/documents/{document['id']}/pages/x/render").status_code == 422


def test_sections_are_listed_in_page_order(client: TestClient, pipeline: Pipeline) -> None:
    document = upload(client)
    assert client.get(f"/api/v1/documents/{document['id']}/sections").json() == []
    pipeline.runner.run_until_idle()
    sections = client.get(f"/api/v1/documents/{document['id']}/sections").json()
    assert [(s["start_page"], s["end_page"], s["kind"]) for s in sections] == [
        (1, 1, "cover_and_notice"),
        (2, 2, "dates_and_schedule"),
        (3, 3, "financial_security"),
    ]
    assert sections[1]["heading"] == "SECTION 2: KEY DATES" and sections[1]["confidence"] == 0.9
    assert client.get("/api/v1/documents/" + "0" * 32 + "/sections").status_code == 404


def test_another_tenants_document_is_invisible(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    db.execute(
        text("INSERT INTO tenant (tenant_id, name, created_by) VALUES ('other', 'Other', 't')")
    )
    foreign = Document(
        tenant_id="other",
        created_by="t",
        sha256="f" * 64,
        filename="x.pdf",
        mime="application/pdf",
        storage_path="documents/x.pdf",
        status="parsed",
        page_count=1,
    )
    db.add(foreign)
    db.commit()
    assert client.get(f"/api/v1/documents/{foreign.id}").status_code == 404
    assert client.get(f"/api/v1/documents/{foreign.id}/sections").status_code == 404
    assert client.get(f"/api/v1/documents/{foreign.id}/pages/1/render").status_code == 404
    response = client.post(
        f"/api/v1/documents/{foreign.id}/extract",
        json={"schema_name": "test.contract", "schema_version": "v1", "prompt_version": "v1"},
    )
    assert response.status_code == 404
    state = client.get(
        "/api/v1/review-state", params={"object_type": "document", "object_id": foreign.id}
    )
    assert state.json()["run"] is None
