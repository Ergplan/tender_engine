from fastapi.testclient import TestClient

from tests.api.test_documents import upload
from tests.conftest import Pipeline

BODY = {"schema_name": "test.contract", "schema_version": "v1", "prompt_version": "v1"}


def test_extract_queues_a_run_and_the_worker_completes_it(
    client: TestClient, pipeline: Pipeline
) -> None:
    document = upload(client)
    pipeline.runner.run_until_idle()
    response = client.post(
        f"/api/v1/documents/{document['id']}/extract", json=BODY, headers={"X-Reviewer": "Asha"}
    )
    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "queued" and run["document_id"] == document["id"]
    assert (run["object_type"], run["object_id"], run["object_version"]) == (
        "document",
        document["id"],
        1,
    )
    assert (run["schema_name"], run["prompt_version"], run["model"]) == (
        "test.contract",
        "v1",
        "claude-fable-5-1",
    )
    assert client.get(f"/api/v1/extraction-runs/{run['id']}").json()["status"] == "queued"

    pipeline.runner.run_until_idle()
    done = client.get(f"/api/v1/extraction-runs/{run['id']}").json()
    assert done["status"] == "validated" and done["error"] is None
    assert (done["token_in"], done["token_out"]) == (3000, 300) and float(done["cost_usd"]) > 0
    assert done["started_at"] and done["finished_at"]


def test_extract_is_refused_for_unknown_schema_prompt_or_unparsed_document(
    client: TestClient, pipeline: Pipeline
) -> None:
    document = upload(client)
    url = f"/api/v1/documents/{document['id']}/extract"
    not_parsed = client.post(url, json=BODY)
    assert not_parsed.status_code == 422 and "not parsed" in not_parsed.json()["detail"]
    pipeline.runner.run_until_idle()
    unknown_schema = client.post(url, json={**BODY, "schema_name": "nope"})
    assert unknown_schema.status_code == 422 and "not registered" in unknown_schema.json()["detail"]
    unknown_prompt = client.post(url, json={**BODY, "prompt_version": "v9"})
    assert (
        unknown_prompt.status_code == 422
        and "extract/v9 is not registered" in unknown_prompt.json()["detail"]
    )
    assert client.post(url, json={"schema_name": "x"}).status_code == 422
    missing = client.post("/api/v1/documents/" + "0" * 32 + "/extract", json=BODY)
    assert missing.status_code == 404 and missing.json()["error_type"] == "not_found"


def test_unknown_extraction_run_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/extraction-runs/" + "0" * 32).status_code == 404
