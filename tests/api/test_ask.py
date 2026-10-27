"""The ask routes (Stage 7, Block 5), through HTTP only."""

from fastapi.testclient import TestClient

from tests.api.test_tenders import ASHA, extracted, fields
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE, EMD


def _approve(client: TestClient, tender_id: str, path: str) -> None:
    candidate = fields(client, tender_id)[path]["candidate"]
    approved = client.post(
        "/api/v1/approvals",
        json={"candidate_id": candidate["id"], "decision": "approved"},
        headers=ASHA,
    )
    assert approved.status_code == 201, approved.text


def test_ask_answers_from_the_approved_fact_and_cites_its_located_page(
    client: TestClient, pipeline: Pipeline
) -> None:
    tender = extracted(client, pipeline)
    machine = client.post(
        f"/api/v1/tenders/{tender['id']}/ask",
        json={"question": "What is the bid submission deadline?"},
        headers=ASHA,
    )
    assert machine.status_code == 200, machine.text
    assert (machine.json()["source"], machine.json()["value"]) == ("machine", "30.03.2026")
    _approve(client, tender["id"], DEADLINE)
    approved = client.post(
        f"/api/v1/tenders/{tender['id']}/ask",
        json={"question": "What is the bid submission deadline?"},
        headers=ASHA,
    )
    body = approved.json()
    assert (body["mode"], body["source"], body["value"], body["is_fact"]) == (
        "field",
        "approved",
        "2026-03-30",
        False,
    )
    assert "Approved fact" in body["answer"]
    assert (body["citations_total"], body["citations_resolved"]) == (1, 1)
    assert body["citations"][0]["page_no"] == 2 and body["citations"][0]["resolved"] is True
    assert (
        client.post(f"/api/v1/tenders/{tender['id']}/ask", json={"question": "  "}).status_code
        == 422
    )
    assert client.post(f"/api/v1/tenders/{'0' * 32}/ask", json={"question": "x"}).status_code == 404


def test_cross_tender_questions_search_approved_facts_only(
    client: TestClient, pipeline: Pipeline
) -> None:
    tender = extracted(client, pipeline)
    none_yet = client.post(
        "/api/v1/tenders/ask", json={"field_path": EMD, "operator": ">", "value": 500000}
    )
    assert none_yet.status_code == 200, none_yet.text
    body = none_yet.json()
    assert (body["matched"], body["considered"], len(body["unreviewed"])) == ([], 1, 1)
    assert body["query"] == {
        "field_path": EMD,
        "label": body["query"]["label"],
        "operator": ">",
        "value": 500000,
    }
    _approve(client, tender["id"], EMD)
    found = client.post(
        "/api/v1/tenders/ask", json={"question": "Which tenders ask an EMD per MW above 5,00,000?"}
    ).json()
    assert found["query"]["field_path"] == EMD and (
        found["query"]["operator"],
        found["query"]["value"],
    ) == (">", 500000)
    assert [hit["tender_id"] for hit in found["matched"]] == [tender["id"]]
    assert found["matched"][0]["value"] == 928000 and found["matched"][0]["evidence_pages"] == [3]
    assert found["is_fact"] is False and "approved facts" in found["answer"]
    too_high = client.post(
        "/api/v1/tenders/ask", json={"field_path": EMD, "operator": ">", "value": 5_000_000}
    ).json()
    assert too_high["matched"] == []
    no_field = client.post("/api/v1/tenders/ask", json={"question": "Which pooling substation?"})
    assert no_field.status_code == 422 and "names no field" in no_field.json()["detail"]
    assert client.post("/api/v1/tenders/ask", json={}).status_code == 422


def test_the_index_route_queues_the_tenders_documents(
    client: TestClient, pipeline: Pipeline
) -> None:
    tender = extracted(client, pipeline)
    before = pipeline.store.count_documents()
    queued = client.post(f"/api/v1/tenders/{tender['id']}/index", headers=ASHA)
    assert queued.status_code == 202 and queued.json() == {"queued": 1}
    pipeline.runner.run_until_idle()
    assert pipeline.store.count_documents() == before
    assert client.post(f"/api/v1/tenders/{'0' * 32}/index", headers=ASHA).status_code == 404
