"""Contract tests for every tender endpoint, through HTTP only."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.main import create_app
from core.models import AuditLog
from tender.models import TenderFieldDef
from tests.conftest import Pipeline
from tests.fixtures.pdfs import make_pdf
from tests.fixtures.tenders import (
    AMENDMENT_ANSWERS,
    AMENDMENT_PAGES,
    DEADLINE,
    EMD,
    RFS_ANSWERS,
    RFS_PAGES,
)

BODY = {
    "type": "solar",
    "agency": "Acme Renewables Agency",
    "external_ref": "ACME/RE/2026/007",
    "title": "Selection of solar power developers for 600 MW solar PV projects",
}
ASHA = {"X-Reviewer": "Asha"}


def create(client: TestClient, **changes: Any) -> dict[str, Any]:
    response = client.post("/api/v1/tenders", json={**BODY, **changes}, headers=ASHA)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def add_version(
    client: TestClient, tender_id: str, pages: list[list[str]], name: str, **form: str
) -> Any:
    return client.post(
        f"/api/v1/tenders/{tender_id}/versions",
        files={"file": (name, make_pdf(pages), "application/pdf")},
        data=form,
        headers=ASHA,
    )


def extracted(client: TestClient, pipeline: Pipeline) -> dict[str, Any]:
    """A tender with its original version uploaded, parsed, extracted and validated."""
    pipeline.sdk.answers = dict(RFS_ANSWERS)
    tender = create(client)
    assert (
        add_version(client, tender["id"], RFS_PAGES, "rfs.pdf", kind="original").status_code == 201
    )
    pipeline.runner.run_until_idle()
    started = client.post(f"/api/v1/tenders/{tender['id']}/extract", json={}, headers=ASHA)
    assert started.status_code == 202, started.text
    pipeline.runner.run_until_idle()
    return tender


def fields(client: TestClient, tender_id: str, **params: Any) -> dict[str, dict[str, Any]]:
    response = client.get(f"/api/v1/tenders/{tender_id}/review-state", params=params)
    assert response.status_code == 200, response.text
    return {field["field_path"]: field for field in response.json()["state"]["fields"]}


def test_create_get_and_list_tenders(client: TestClient) -> None:
    tender = create(client)
    assert tender["tender_type"] == "solar" and tender["issuing_agency"] == BODY["agency"]
    assert (tender["status"], tender["current_version_no"], tender["created_by"]) == (
        "ingested",
        None,
        "Asha",
    )
    other = create(client, type="fdre", external_ref=None, title="Another tender")
    assert client.get(f"/api/v1/tenders/{tender['id']}").json() == tender
    listed = client.get("/api/v1/tenders").json()
    assert [row["id"] for row in listed] == [other["id"], tender["id"]], "ordered by type"
    assert client.get(f"/api/v1/tenders/{'0' * 32}").status_code == 404


def test_create_refuses_an_unknown_type_and_missing_fields(client: TestClient) -> None:
    unknown = client.post("/api/v1/tenders", json={**BODY, "type": "nuclear"})
    assert unknown.status_code == 422 and "unknown tender type" in unknown.json()["detail"]
    assert client.post("/api/v1/tenders", json={"type": "solar"}).status_code == 422
    assert client.post("/api/v1/tenders", json={**BODY, "title": "  "}).status_code == 422
    assert client.get("/api/v1/tenders").json() == []


def test_versions_are_added_listed_and_ordered(client: TestClient, db: Session) -> None:
    tender = create(client)
    early = add_version(client, tender["id"], AMENDMENT_PAGES, "a.pdf", kind="amendment")
    assert early.status_code == 422 and "first version" in early.json()["detail"]
    first = add_version(client, tender["id"], RFS_PAGES, "rfs.pdf", kind="original")
    assert first.status_code == 201, first.text
    assert first.json()["version_no"] == 1 and first.json()["kind"] == "original"
    assert [d["role"] for d in first.json()["documents"]] == ["rfs"]
    second = add_version(
        client,
        tender["id"],
        AMENDMENT_PAGES,
        "amendment-01.pdf",
        kind="amendment",
        issued_on="2026-03-20",
        summary_of_change="Bid deadline extended.",
    )
    assert second.status_code == 201, second.text
    body = second.json()
    assert (body["version_no"], body["issued_on"], body["summary_of_change"]) == (
        2,
        "2026-03-20",
        "Bid deadline extended.",
    )
    assert body["supersedes_version_id"] == first.json()["id"]
    assert body["documents"][0]["filename"] == "amendment-01.pdf"
    versions = client.get(f"/api/v1/tenders/{tender['id']}/versions").json()
    assert [v["version_no"] for v in versions] == [1, 2]
    assert client.get(f"/api/v1/tenders/{tender['id']}").json()["current_version_no"] == 2
    audits = db.scalars(select(AuditLog).where(AuditLog.table_name == "tender_version")).all()
    assert len(audits) == 4 and {audit.actor for audit in audits} == {"Asha"}


def test_a_document_is_added_to_an_existing_version_with_its_role(client: TestClient) -> None:
    tender = create(client)
    add_version(client, tender["id"], RFS_PAGES, "rfs.pdf", kind="original")
    ppa = [["DRAFT POWER PURCHASE AGREEMENT", "Article 10: tariff"]]
    missing_role = add_version(
        client, tender["id"], ppa, "ppa.pdf", kind="original", version_no="1"
    )
    assert missing_role.status_code == 422 and "`role` is required" in missing_role.json()["detail"]
    attached = add_version(
        client, tender["id"], ppa, "ppa.pdf", kind="original", version_no="1", role="ppa"
    )
    assert attached.status_code == 201, attached.text
    assert [d["role"] for d in attached.json()["documents"]] == ["rfs", "ppa"]
    as_change = add_version(
        client,
        tender["id"],
        AMENDMENT_PAGES,
        "amendment.pdf",
        kind="amendment",
        version_no="1",
        role="amendment",
    )
    assert as_change.status_code == 422, "an amendment is a new version, never an attachment"
    assert "a new version" in as_change.json()["detail"]
    disguised = add_version(
        client, tender["id"], AMENDMENT_PAGES, "a.pdf", kind="amendment", version_no="1", role="rfs"
    )
    assert disguised.status_code == 422 and "is 'original'" in disguised.json()["detail"]
    by_role = add_version(
        client, tender["id"], AMENDMENT_PAGES, "a.pdf", version_no="1", role="amendment"
    )
    assert by_role.status_code == 422 and "add it as a new version" in by_role.json()["detail"]
    no_kind = add_version(
        client, tender["id"], [["Technical volume"]], "t.pdf", version_no="1", role="technical"
    )
    assert no_kind.status_code == 201, "kind may be left out when adding to a version"
    assert len(client.get(f"/api/v1/tenders/{tender['id']}/versions").json()) == 1


def test_bad_version_requests_are_422_or_404(client: TestClient) -> None:
    tender = create(client)
    url = f"/api/v1/tenders/{tender['id']}/versions"
    not_pdf = client.post(
        url, files={"file": ("x.pdf", b"hello", "application/pdf")}, data={"kind": "original"}
    )
    assert not_pdf.status_code == 422 and "not a PDF" in not_pdf.json()["detail"]
    assert add_version(client, tender["id"], RFS_PAGES, "r.pdf", kind="rewrite").status_code == 422
    missing = add_version(client, tender["id"], RFS_PAGES, "r.pdf")
    assert missing.status_code == 422 and "`kind` is required" in missing.json()["detail"]
    bad_role = add_version(client, tender["id"], RFS_PAGES, "r.pdf", kind="original", role="novel")
    assert bad_role.status_code == 422
    bad_date = add_version(
        client, tender["id"], RFS_PAGES, "r.pdf", kind="original", issued_on="soon"
    )
    assert bad_date.status_code == 422
    assert add_version(client, "0" * 32, RFS_PAGES, "r.pdf", kind="original").status_code == 404
    no_version = add_version(
        client, tender["id"], RFS_PAGES, "r.pdf", kind="original", version_no="3", role="ppa"
    )
    assert no_version.status_code == 404
    assert client.get(f"/api/v1/tenders/{'0' * 32}/versions").status_code == 404


def test_extract_queues_one_run_per_document_and_the_worker_completes_them(
    client: TestClient, pipeline: Pipeline
) -> None:
    pipeline.sdk.answers = dict(RFS_ANSWERS)
    tender = create(client)
    url = f"/api/v1/tenders/{tender['id']}/extract"
    empty = client.post(url, json={})
    assert empty.status_code == 422 and "no version yet" in empty.json()["detail"]
    add_version(client, tender["id"], RFS_PAGES, "rfs.pdf", kind="original")
    unparsed = client.post(url, json={})
    assert unparsed.status_code == 422 and "not parsed yet" in unparsed.json()["detail"]
    pipeline.runner.run_until_idle()
    assert client.post(url, json={"prompt_version": "v9"}).status_code == 422
    assert client.post(url, json={"version_no": 5}).status_code == 404
    assert client.post(f"/api/v1/tenders/{'0' * 32}/extract", json={}).status_code == 404
    started = client.post(url, json={}, headers=ASHA)
    assert started.status_code == 202, started.text
    (run,) = started.json()
    assert (run["object_type"], run["object_id"], run["object_version"]) == (
        "tender",
        tender["id"],
        1,
    )
    assert (run["schema_name"], run["status"]) == ("tender.solar", "queued")
    assert client.get(f"/api/v1/tenders/{tender['id']}").json()["status"] == "ingested"
    pipeline.runner.run_until_idle()
    assert client.get(f"/api/v1/extraction-runs/{run['id']}").json()["status"] == "validated"
    assert client.get(f"/api/v1/tenders/{tender['id']}").json()["status"] == "extracted"


def test_review_state_delegates_to_core_for_one_version(
    client: TestClient, pipeline: Pipeline
) -> None:
    tender = create(client)
    blank = client.get(f"/api/v1/tenders/{tender['id']}/review-state").json()
    assert (blank["version_no"], blank["changed_fields"], blank["state"]["fields"]) == (
        None,
        [],
        [],
    )
    tender = extracted(client, pipeline)
    body = client.get(f"/api/v1/tenders/{tender['id']}/review-state").json()
    assert (body["tender_id"], body["version_no"], body["version_kind"]) == (
        tender["id"],
        1,
        "original",
    )
    state = body["state"]
    assert (state["object_type"], state["object_id"]) == ("tender", tender["id"])
    assert state["total"] == len(pipeline.catalog.get("solar").fields)
    by_path = {field["field_path"]: field for field in state["fields"]}
    assert by_path[EMD]["candidate"]["value"] == 928000
    assert by_path[EMD]["candidate"]["evidence"][0]["page_no"] == 3
    assert by_path[EMD]["group"] == "guarantees"
    assert EMD in body["changed_fields"] and len(body["changed_fields"]) == len(RFS_ANSWERS)
    assert body["missing_required"] == []
    assert client.get(f"/api/v1/tenders/{'0' * 32}/review-state").status_code == 404


def test_full_tender_flow_with_an_amendment_through_the_http_api(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    """Upload, extract, approve; then an amendment moves the deadline. The view shows the
    amended deadline from version 2 and the untouched EMD from version 1."""
    tender = extracted(client, pipeline)
    tid = tender["id"]
    view = client.get(f"/api/v1/tenders/{tid}/view").json()
    assert (view["decided"], view["current_version_no"]) == (0, 1)
    assert all(field["value"] is None for field in view["fields"]), "no truth before a decision"
    first = fields(client, tid)
    for path in (EMD, DEADLINE):
        approved = client.post(
            "/api/v1/approvals",
            json={"candidate_id": first[path]["candidate"]["id"], "decision": "approved"},
            headers=ASHA,
        )
        assert approved.status_code == 201, approved.text

    pipeline.sdk.answers = dict(AMENDMENT_ANSWERS)
    added = add_version(
        client, tid, AMENDMENT_PAGES, "amendment-01.pdf", kind="amendment", issued_on="2026-03-20"
    )
    assert added.status_code == 201
    pipeline.runner.run_until_idle()
    started = client.post(f"/api/v1/tenders/{tid}/extract", json={}, headers=ASHA)
    assert started.status_code == 202 and started.json() == [], (
        "an amending document is mapped by a background job, which then queues its run"
    )
    pipeline.runner.run_until_idle()

    latest = client.get(f"/api/v1/tenders/{tid}/review-state").json()
    assert (latest["version_no"], latest["version_kind"]) == (2, "amendment")
    assert latest["changed_fields"] == [DEADLINE]
    assert latest["missing_required"] == [], "the amendment need not restate required fields"
    second = {field["field_path"]: field for field in latest["state"]["fields"]}
    assert second[DEADLINE]["candidate"]["value"] == "15.04.2026"
    assert second[EMD]["candidate"] is None
    assert fields(client, tid, version=1)[DEADLINE]["candidate"]["value"] == "30.03.2026"
    approved = client.post(
        "/api/v1/approvals",
        json={"candidate_id": second[DEADLINE]["candidate"]["id"], "decision": "approved"},
        headers=ASHA,
    )
    assert approved.status_code == 201, approved.text

    view = client.get(f"/api/v1/tenders/{tid}/view").json()
    by_path = {field["field_path"]: field for field in view["fields"]}
    assert (view["current_version_no"], view["decided"], view["total"]) == (2, 2, len(first))
    assert (by_path[DEADLINE]["value"], by_path[DEADLINE]["version_no"]) == ("2026-04-15", 2)
    assert by_path[DEADLINE]["version_kind"] == "amendment"
    assert (by_path[EMD]["value"], by_path[EMD]["version_no"]) == (928000, 1)
    assert by_path[EMD]["version_kind"] == "original" and by_path[EMD]["section"] == "guarantees"
    assert by_path[EMD]["evidence"][0]["page_no"] == 3
    assert client.get(f"/api/v1/tenders/{tid}").json()["status"] == "in_review"
    assert client.get(f"/api/v1/tenders/{'0' * 32}/view").status_code == 404


def test_schema_endpoint_returns_the_compiled_field_list(client: TestClient) -> None:
    body = client.get("/api/v1/schemas/tender/fdre").json()
    assert (body["tender_type"], body["pack"]) == ("fdre", "power")
    assert (body["schema_name"], body["schema_version"]) == ("tender.fdre", "v1")
    assert [section["name"] for section in body["sections"]][-1] == "fdre_profile"
    assert body["sections"][0] == {
        "name": "summary",
        "label": "Summary",
        "prompt": "summary",
        "roles": ["rfs", "contractual", "nit"],
        "order": 1,
    }
    paths = [field["path"] for field in body["fields"]]
    assert paths[0] == "core.summary.plain_english_summary"
    assert "sector.power.fdre.demand_profile" in paths
    field = next(f for f in body["fields"] if f["path"] == "core.guarantees.emd_form")
    assert field["enum_values"] == ["bg", "insurance_surety", "cash", "other"]
    assert (field["namespace"], field["section"]) == ("core", "guarantees")
    assert client.get("/api/v1/schemas/tender/nuclear").status_code == 404


def test_the_api_writes_the_field_definitions_at_start_up(pipeline: Pipeline, db: Session) -> None:
    assert db.scalar(select(TenderFieldDef.id).limit(1)) is None
    create_app(
        pipeline.settings, pipeline.schemas, pipeline.storage, pipeline.llm, pipeline.catalog
    )
    rows = db.scalars(select(TenderFieldDef.tender_type).distinct()).all()
    assert sorted(rows) == sorted(pipeline.catalog.types)


def test_another_tenants_tender_is_invisible(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    from core.models import Tenant

    tender = create(client)
    db.add(Tenant(tenant_id="other", name="Other", created_by="pytest"))
    db.commit()
    other = TestClient(
        create_app(
            pipeline.settings.model_copy(update={"tenant_id": "other"}),
            pipeline.schemas,
            pipeline.storage,
            pipeline.llm,
            pipeline.catalog,
        )
    )
    assert other.get(f"/api/v1/tenders/{tender['id']}").status_code == 404
    assert other.get("/api/v1/tenders").json() == []
    assert other.get(f"/api/v1/tenders/{tender['id']}/versions").status_code == 404
    assert other.get(f"/api/v1/tenders/{tender['id']}/view").status_code == 404


def test_extraction_summary_is_served_as_data_and_as_the_markdown_report(
    client: TestClient, pipeline: Pipeline
) -> None:
    empty = client.get("/api/v1/reports/extraction-summary").json()
    assert empty["tenders"] == [] and empty["markdown"].startswith("# Extraction summary")
    tender = extracted(client, pipeline)
    body = client.get("/api/v1/reports/extraction-summary").json()
    (row,) = body["tenders"]
    fields = len(pipeline.catalog.get("solar").fields)
    assert (row["tender_id"], row["tender_type"], row["versions"], row["documents"]) == (
        tender["id"],
        "solar",
        1,
        1,
    )
    assert (row["fields"], row["with_value"], row["located"]) == (fields, 9, 9)
    assert (row["runs"], row["unfinished_runs"], row["pages"]) == (1, 0, 3)
    assert row["failing_validation"] == 0
    assert body["model"] == "claude-fable-5-1" and body["calls"] >= 10
    assert body["total_cost_usd"] > 0 and float(row["cost_usd"]) > 0
    assert f"| 1 | 1 | 3 | {fields} | 9 | 9 | 100% |" in body["markdown"]
