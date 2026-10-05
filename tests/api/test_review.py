"""Integration: upload -> parse -> extract (scripted model) -> validate -> approve -> canonical,
through the HTTP API only."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import AuditLog, CanonicalFact
from tests.api.test_documents import upload
from tests.api.test_extraction import BODY
from tests.conftest import Pipeline

REVIEWER = {"X-Reviewer": "Asha"}


def reviewed_document(
    client: TestClient, pipeline: Pipeline
) -> tuple[str, dict[str, dict[str, Any]]]:
    document = upload(client)
    pipeline.runner.run_until_idle()
    assert client.post(f"/api/v1/documents/{document['id']}/extract", json=BODY).status_code == 202
    pipeline.runner.run_until_idle()
    return document["id"], fields_of(client, document["id"])


def fields_of(client: TestClient, document_id: str) -> dict[str, dict[str, Any]]:
    state = client.get(
        "/api/v1/review-state", params={"object_type": "document", "object_id": document_id}
    )
    assert state.status_code == 200
    return {field["field_path"]: field for field in state.json()["fields"]}


def test_full_pipeline_through_the_http_api(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    document_id, fields = reviewed_document(client, pipeline)
    params = {"object_type": "document", "object_id": document_id}

    state = client.get("/api/v1/review-state", params=params).json()
    assert (state["decided"], state["total"], state["required_undecided"]) == (0, 7, 3)
    assert state["run"]["status"] == "validated"
    emd = fields["security.emd_per_mw"]
    assert emd["candidate"]["value"] == 928000 and emd["candidate"]["status"] == "validated"
    assert (
        emd["candidate"]["evidence"][0]["page_no"] == 3 and emd["candidate"]["evidence"][0]["bbox"]
    )
    assert client.get("/api/v1/canonical", params=params).json() == []
    assert db.scalar(select(func.count()).select_from(CanonicalFact)) == 0, (
        "no truth before a human decision"
    )

    approved = client.post(
        "/api/v1/approvals",
        json={"candidate_id": emd["candidate"]["id"], "decision": "approved"},
        headers=REVIEWER,
    )
    assert approved.status_code == 201
    body = approved.json()
    assert (body["decision"], body["final_value"], body["reviewer"]) == ("approved", 928000, "Asha")
    assert (
        body["created"] is True
        and body["canonical_fact_id"]
        and body["feedback_delta_kind"] is None
    )

    edited = client.post(
        "/api/v1/approvals",
        json={
            "candidate_id": fields["dates.bid_deadline"]["candidate"]["id"],
            "decision": "edited",
            "final_value": "31/03/2026",
            "note": "amended by corrigendum",
        },
        headers=REVIEWER,
    )
    assert edited.status_code == 201
    assert (
        edited.json()["final_value"] == "2026-03-31"
        and edited.json()["feedback_delta_kind"] == "wrong_value"
    )

    facts = client.get("/api/v1/canonical", params=params).json()
    assert [(f["field_path"], f["value"], f["created_by"]) for f in facts] == [
        ("dates.bid_deadline", "2026-03-31", "Asha"),
        ("security.emd_per_mw", 928000, "Asha"),
    ]
    assert facts[1]["evidence"][0]["page_no"] == 3 and facts[1]["approval_id"] == body["id"]
    assert client.get("/api/v1/canonical", params={**params, "version": 2}).json() == []

    after = fields_of(client, document_id)
    assert after["security.emd_per_mw"]["approval"]["decision"] == "approved"
    assert after["dates.bid_deadline"]["approval"]["final_value"] == "2026-03-31"
    assert after["dates.bid_deadline"]["candidate"]["value"] == "2026-03-30", (
        "candidate is unchanged"
    )
    state = client.get("/api/v1/review-state", params={**params, "version": 1}).json()
    assert (state["decided"], state["required_undecided"]) == (2, 2)
    tables = set(db.scalars(select(AuditLog.table_name)))
    assert tables == {"candidate", "approval", "canonical_fact", "feedback", "request"}


def test_a_repeated_identical_approval_is_200_and_writes_nothing(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    _, fields = reviewed_document(client, pipeline)
    request = {"candidate_id": fields["identity.issuer"]["candidate"]["id"], "decision": "approved"}
    first = client.post("/api/v1/approvals", json=request, headers=REVIEWER)
    # The request itself is audited each time; the repeat writes nothing to a truth table.
    truth = select(func.count()).select_from(AuditLog).where(AuditLog.table_name != "request")
    audits = db.scalar(truth)
    second = client.post("/api/v1/approvals", json=request, headers=REVIEWER)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"] and second.json()["created"] is False
    assert second.json()["canonical_fact_id"] == first.json()["canonical_fact_id"]
    assert db.scalar(select(func.count()).select_from(CanonicalFact)) == 1
    assert db.scalar(truth) == audits


def test_approval_requires_the_reviewer_header(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    _, fields = reviewed_document(client, pipeline)
    request = {"candidate_id": fields["identity.issuer"]["candidate"]["id"], "decision": "approved"}
    for headers in ({}, {"X-Reviewer": "   "}):
        response = client.post("/api/v1/approvals", json=request, headers=headers)
        assert response.status_code == 422 and "X-Reviewer" in response.json()["detail"]
    assert db.scalar(select(func.count()).select_from(CanonicalFact)) == 0


def test_bad_approvals_are_422_or_404_with_a_plain_message(
    client: TestClient, pipeline: Pipeline
) -> None:
    _, fields = reviewed_document(client, pipeline)
    candidate_id = fields["security.tenure_years"]["candidate"]["id"]

    def post(body: dict[str, Any]) -> Any:
        return client.post("/api/v1/approvals", json=body, headers=REVIEWER)

    wrong_type = post({"candidate_id": candidate_id, "decision": "edited", "final_value": "many"})
    assert wrong_type.status_code == 422 and "not a valid int" in wrong_type.json()["detail"]
    assert post({"candidate_id": candidate_id, "decision": "blessed"}).status_code == 422
    assert post({"decision": "approved"}).status_code == 422
    changed = post({"candidate_id": candidate_id, "decision": "approved", "final_value": 30})
    assert changed.status_code == 422 and "cannot change the value" in changed.json()["detail"]
    missing = post({"candidate_id": "0" * 32, "decision": "approved"})
    assert missing.status_code == 404 and missing.json()["error_type"] == "not_found"


def test_review_state_and_canonical_require_their_query_parameters(client: TestClient) -> None:
    assert client.get("/api/v1/review-state").status_code == 422
    assert client.get("/api/v1/canonical", params={"object_type": "document"}).status_code == 422
    empty = client.get(
        "/api/v1/review-state", params={"object_type": "document", "object_id": "0" * 32}
    )
    assert empty.status_code == 200 and empty.json()["fields"] == []


def test_every_api_route_is_under_v1_except_the_root_health_probe(client: TestClient) -> None:
    paths = sorted(client.get("/openapi.json").json()["paths"])
    outside = [p for p in paths if not p.startswith("/api/v1/") and p != "/health"]
    assert outside == []
    assert {
        "/api/v1/documents",
        "/api/v1/documents/{document_id}",
        "/api/v1/documents/{document_id}/pages/{page_no}/render",
        "/api/v1/documents/{document_id}/sections",
        "/api/v1/documents/{document_id}/extract",
        "/api/v1/extraction-runs/{run_id}",
        "/api/v1/review-state",
        "/api/v1/approvals",
        "/api/v1/canonical",
        "/api/v1/health",
    } <= set(paths)
