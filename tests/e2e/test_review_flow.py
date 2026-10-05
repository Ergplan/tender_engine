"""Slow: the Stage 3 end-to-end run. A real tender (an NTPC notice inviting tenders, three
pages) is extracted with the real model the way the management command does it, through
the batch API with its sections sharing one cached page window, and is then reviewed
through a review link: the reviewer's view, decisions, completion and the snapshot.

Prints the tokens, the share read from the cache and the cost. Run with `make test-e2e`.
"""

import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from api.main import create_app
from core.config import Settings
from core.llm.client import LLMClient
from core.models import ExtractionRun, LLMBatch, LLMCallLog
from core.services.extract import ExtractService
from core.storage import LocalStorage
from tender.services.packs import build_registry
from tender.services.worker_jobs import tender_jobs
from tests.e2e.test_fdre_core_pipeline import _job_errors
from worker.runner import Runner

PDF = Path("/work/tenders/generation/ntpc-phes-2000mw/job_45538.pdf")
INTERNAL = {"X-Reviewer": "e2e"}
TARGET = 0.95


@pytest.mark.slow
@pytest.mark.timeout(3600)
def test_a_real_tender_is_extracted_in_a_batch_and_reviewed_through_a_link(
    settings: Settings, session_factory: sessionmaker[Session], db: Session, tmp_path: Path
) -> None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not PDF.is_file():
        pytest.skip("needs ANTHROPIC_API_KEY and the tender set under /work/tenders")
    local = settings.model_copy(
        update={
            "anthropic_api_key": key,
            "data_dir": str(tmp_path / "data"),
            "llm_batch_poll_seconds": 0,
        }
    )
    storage = LocalStorage(local.data_dir)
    schemas, catalog = build_registry()
    llm = LLMClient(local, session_factory, prompt_roots=catalog.prompt_roots)
    extract = ExtractService(llm, storage, schemas, local)
    # The worker as deployed: with the tender layer's jobs, so the summary is written
    # from the record once the extraction is validated.
    runner = Runner(
        local,
        session_factory,
        storage,
        schemas,
        llm,
        *tender_jobs(llm, catalog, extract, schemas, local.tenant_id),
    )
    client = TestClient(create_app(local, schemas, storage, llm, catalog))

    created = client.post(
        "/api/v1/tenders",
        json={
            "type": "generation",
            "agency": "NTPC Renewable Energy Ltd",
            "external_ref": "NRE-CS-5846-004",
            "title": "Pumped hydro energy storage of 2000 MW / 12000 MWh (NIT)",
        },
        headers=INTERNAL,
    )
    assert created.status_code == 201, created.text
    tender_id = created.json()["id"]
    version = client.post(
        f"/api/v1/tenders/{tender_id}/versions",
        files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
        data={"kind": "original", "role": "nit", "issued_on": "2026-05-29"},
        headers=INTERNAL,
    )
    assert version.status_code == 201, version.text
    runner.run_until_idle()

    began = time.monotonic()
    started = client.post(
        f"/api/v1/tenders/{tender_id}/extract", json={"mode": "batch"}, headers=INTERNAL
    )
    assert started.status_code == 202, started.text + _job_errors(db)
    run_id = started.json()[0]["id"]
    # The worker looks at the batch, finds it unfinished and queues the next look.
    while time.monotonic() - began < 3000:
        runner.run_until_idle(max_jobs=5)
        db.expire_all()
        if db.get_one(ExtractionRun, run_id).status in ("validated", "failed"):
            break
        time.sleep(20)
    run = db.get_one(ExtractionRun, run_id)
    assert run.status == "validated", _job_errors(db)
    seconds = time.monotonic() - began
    # The second pass: the summary written from the record (one text-only call).
    runner.run_until_idle(max_jobs=5)

    calls = list(db.scalars(select(LLMCallLog).where(LLMCallLog.extraction_run_id == run_id)))
    batches = list(db.scalars(select(LLMBatch).where(LLMBatch.extraction_run_id == run_id)))
    in_batch = [call for call in calls if call.mode == "batch" and call.status == "ok"]
    print(f"\ntender: {PDF.name}; {len(calls)} calls, {len(in_batch)} answered in a batch")
    print(
        f"batches (wave, calls): {sorted((b.wave, b.request_count) for b in batches)}; "
        f"wall clock {seconds:.0f} s"
    )
    print(
        f"input tokens {run.token_in}, read from the cache {run.token_cached} "
        f"({100 * run.token_cached / max(run.token_in, 1):.0f}%), written to it "
        f"{sum(call.cache_write_tokens for call in calls)}, output {run.token_out}, "
        f"cost USD {run.cost_usd}"
    )
    assert sorted(b.wave for b in batches) == [1, 2] and all(
        b.status == "collected" for b in batches
    )
    assert len(in_batch) >= len(calls) - 2, "the calls went through the batch API"
    assert sum(call.cache_write_tokens for call in calls) > 0, "the shared window was cached"

    # A review link, and the reviewer's side of the API as the browser uses it.
    link = client.post(
        "/api/v1/review-tokens", json={"tender_id": tender_id, "reviewer_name": "E2E Reviewer"}
    )
    assert link.status_code == 201, link.text
    reviewer = {"X-Public-Request": "1", "X-Review-Token": link.json()["token"]}
    assert client.get("/api/v1/tenders", headers={"X-Public-Request": "1"}).status_code == 401
    review: dict[str, Any] = client.get(
        f"/api/v1/tenders/{tender_id}/review", headers=reviewer
    ).json()
    returned = located = 0
    for field in review["fields"]:
        assert field["current"] is not None, f"{field['field_path']} has no candidate"
        candidate = field["entries"][field["current"]]["state"]["candidate"]
        if candidate["value"] is not None:
            returned += 1
            located += any(span["char_start"] is not None for span in candidate["evidence"])
    print(f"evidence-location rate {located}/{returned}; answer rate {returned}/{review['total']}")
    assert returned >= 5 and located / returned >= TARGET
    assert review["can_complete"] is False

    summary_path = "core.summary.plain_english_summary"
    summary = next(f for f in review["fields"] if f["field_path"] == summary_path)
    written = summary["entries"][summary["current"]]["state"]["candidate"]
    assert written["prompt_name"] == "summary_record", "the summary in review is the second pass"
    assert all(span["source"] and span["char_start"] is not None for span in written["evidence"])
    print(
        f"summary written from the record: {len(written['evidence'])} inherited passages, "
        f"{written['value'].count(chr(10) + chr(10)) + 1} paragraphs"
    )
    early = client.post(
        "/api/v1/approvals",
        json={"candidate_id": written["id"], "decision": "approved"},
        headers=reviewer,
    )
    assert early.status_code == 422 and "decide the other fields first" in early.json()["detail"]

    # Every other field, then the summary: it is written from them and decided last.
    decided = 0
    for field in [f for f in review["fields"] if f["field_path"] != summary_path] + [summary]:
        entry = field["entries"][field["current"]]
        candidate = entry["state"]["candidate"]
        approvable = candidate["value"] is not None and any(
            span["char_start"] is not None for span in candidate["evidence"]
        )
        made = client.post(
            "/api/v1/approvals",
            json={
                "candidate_id": candidate["id"],
                "decision": "approved" if approvable else "not_in_document",
                "previous_approval_id": None,
            },
            headers=reviewer,
        )
        assert made.status_code == 201, (field["field_path"], made.text)
        assert made.json()["reviewer"] == "E2E Reviewer"
        decided += 1
    done = client.post(f"/api/v1/tenders/{tender_id}/complete-review", headers=reviewer)
    assert done.status_code == 201, done.text
    snapshot = client.get(f"/api/v1/tenders/{tender_id}/snapshot", headers=reviewer).json()
    values = {f["field_path"]: f for f in snapshot["snapshot"]["view"]["fields"]}
    number = values["core.identity.tender_number"]
    print(
        f"reviewed {decided} fields through the link, the summary last; snapshot tender number "
        f"{number['value']!r} with {len(number['evidence'])} evidence item(s)"
    )
    assert snapshot["snapshot"]["decided"] == decided and number["value"] and number["evidence"]
    assert (
        client.get(f"/api/v1/tenders/{tender_id}", headers=reviewer).json()["status"] == "reviewed"
    )
    late = client.post(
        "/api/v1/approvals",
        json={"candidate_id": "0" * 32, "decision": "approved"},
        headers=reviewer,
    )
    assert late.status_code == 409
