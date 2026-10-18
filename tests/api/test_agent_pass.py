"""The independent agent pass through HTTP: queued by the API, run by the agent container,
read back with its findings; never reachable with a review link."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.harness import Harness, Quote, RunOutcome
from agent.main import AgentWorker
from agent.service import AgentPassService
from core.models import Job
from tests.api.test_review_tokens import PUBLIC, link
from tests.api.test_tenders import ASHA, add_version, create
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE, RFS_PAGES

DEADLINE_QUOTE = "The last date of bid submission is 30.03.2026 at 15:00 hrs."


def readable(client: TestClient, pipeline: Pipeline) -> dict[str, Any]:
    """A tender whose original is uploaded, parsed and section-mapped, not extracted."""
    tender = create(client)
    added = add_version(client, tender["id"], RFS_PAGES, "rfs.pdf", kind="original")
    assert added.status_code == 201, added.text
    pipeline.runner.run_until_idle()
    return tender


def script(harness: Harness, instructions: str, brief: str) -> RunOutcome:
    """What a model would do: read the bid sheet, submit the deadline from it."""
    assert "Document 1: rfs.pdf" in brief and DEADLINE in brief
    harness.read_pages(1, [2])
    told = harness.submit_finding(
        DEADLINE,
        '"30.03.2026"',
        0.9,
        "the bid information sheet",
        [Quote(document_no=1, page_no=2, quote=DEADLINE_QUOTE)],
    )
    assert told.startswith(f"{DEADLINE}: accepted")
    return RunOutcome(final_output="1 field found")


def agent_worker(pipeline: Pipeline) -> AgentWorker:
    service = AgentPassService(
        pipeline.catalog, pipeline.schemas, pipeline.tenders, pipeline.settings, pipeline.storage
    )
    return AgentWorker(pipeline.settings, pipeline.session_factory, service=service, driver=script)


def test_a_pass_is_queued_run_by_the_agent_container_and_read_back(
    client: TestClient, pipeline: Pipeline, db: Session
) -> None:
    tender = readable(client, pipeline)
    started = client.post(f"/api/v1/tenders/{tender['id']}/agent-pass", json={}, headers=ASHA)
    assert started.status_code == 202, started.text
    run = started.json()
    assert (run["status"], run["object_id"], run["object_version"]) == ("queued", tender["id"], 1)
    assert run["model"] == pipeline.settings.openai_model
    assert (run["prompt_name"], run["prompt_version"]) == ("agent_pass", "v1")
    assert run["pages_offered"]["1"] and run["created_by"] == "Asha"
    assert [d["filename"] for d in run["documents"]] == ["rfs.pdf"]
    jobs = db.scalars(select(Job).where(Job.kind == "agent_pass")).all()
    assert len(jobs) == 1 and jobs[0].status == "queued"

    # The worker's chain leaves the job alone; the agent container takes it.
    pipeline.runner.run_until_idle()
    db.expire_all()
    assert db.get(Job, jobs[0].id).status == "queued"
    assert agent_worker(pipeline).run_once() is True
    db.expire_all()
    assert db.get(Job, jobs[0].id).status == "done"

    listed = client.get(f"/api/v1/tenders/{tender['id']}/agent-pass")
    assert listed.status_code == 200 and [r["id"] for r in listed.json()] == [run["id"]]
    assert listed.json()[0]["status"] == "done"

    read = client.get(f"/api/v1/tenders/{tender['id']}/agent-pass/{run['id']}")
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["run"]["status"] == "done" and body["run"]["pages_read"] == {"1": [2]}
    assert body["run"]["error"] and "field(s) without a finding" in body["run"]["error"]
    assert body["run"]["finished_at"] and body["run"]["turns"] == 0
    (finding,) = body["findings"]
    assert (finding["field_path"], finding["value"], finding["status"]) == (
        DEADLINE,
        "2026-03-30",
        "accepted",
    )
    assert finding["ordinal"] == 1 and finding["reason"] is None
    span = finding["evidence"][0]
    assert span["page_no"] == 2 and span["char_start"] is not None and span["quote"]
    assert DEADLINE not in body["unsubmitted"] and body["unsubmitted"]
    assert agent_worker(pipeline).run_once() is False, "nothing left to claim"


def test_refusals_are_422_or_404(client: TestClient, pipeline: Pipeline) -> None:
    bare = create(client)
    no_version = client.post(f"/api/v1/tenders/{bare['id']}/agent-pass", json={}, headers=ASHA)
    assert no_version.status_code == 422 and "no version" in no_version.json()["detail"]

    tender = readable(client, pipeline)
    other = create(client, external_ref="ACME/RE/2026/008", title="Another tender")
    missing_version = client.post(
        f"/api/v1/tenders/{tender['id']}/agent-pass", json={"version_no": 9}, headers=ASHA
    )
    assert missing_version.status_code == 422 and "version 9" in missing_version.json()["detail"]

    unknown = client.post("/api/v1/tenders/" + "0" * 32 + "/agent-pass", json={}, headers=ASHA)
    assert unknown.status_code == 404 and unknown.json()["error_type"] == "not_found"
    assert client.get("/api/v1/tenders/" + "0" * 32 + "/agent-pass").status_code == 404

    run = client.post(f"/api/v1/tenders/{tender['id']}/agent-pass", json={}, headers=ASHA).json()
    foreign = client.get(f"/api/v1/tenders/{other['id']}/agent-pass/{run['id']}")
    assert foreign.status_code == 404 and foreign.json()["error_type"] == "not_found"
    assert client.get(f"/api/v1/tenders/{other['id']}/agent-pass").json() == []
    assert client.get(f"/api/v1/tenders/{tender['id']}/agent-pass/" + "0" * 32).status_code == 404


def test_a_review_link_reaches_no_agent_pass_route(client: TestClient, pipeline: Pipeline) -> None:
    tender = readable(client, pipeline)
    run = client.post(f"/api/v1/tenders/{tender['id']}/agent-pass", json={}, headers=ASHA).json()
    headers = {**PUBLIC, "X-Review-Token": link(client, tender["id"])["token"]}
    for method, path in (
        ("POST", f"/api/v1/tenders/{tender['id']}/agent-pass"),
        ("GET", f"/api/v1/tenders/{tender['id']}/agent-pass"),
        ("GET", f"/api/v1/tenders/{tender['id']}/agent-pass/{run['id']}"),
    ):
        response = client.request(method, path, headers=headers, json={})
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["error_type"] == "not_allowed"
