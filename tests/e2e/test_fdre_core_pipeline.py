"""Slow: the Stage 1 end-to-end run. A real FDRE tender goes through the HTTP API and the
worker with the real model: upload, parse, section map, extract, validate, approve, canonical.

Prints one line per field for the stage report. Run with `make test-e2e`.
"""

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from api.main import create_app
from core.config import Settings
from core.llm.client import LLMClient
from core.models import CanonicalFact, ExtractionRun, Job
from core.storage import LocalStorage
from tests.fixtures.fdre_schema import SCHEMA_NAME, SCHEMA_VERSION, make_fdre_registry
from worker.runner import Runner

TENDERS = Path("/work/tenders/fdre")
PDFS = {
    "seci-fdre-ix": TENDERS
    / "seci-fdre-ix/RfS_for_4800_MWh_Peak_Supply_(FDRE-IX)-_final_upload.pdf",
    "nhpc-fdre-ii": TENDERS / "nhpc-fdre-ii/RfS_FDRE_1200MW_NHPC_Tranche-II.pdf",
}
REVIEWER = {"X-Reviewer": "e2e"}


@pytest.mark.slow
@pytest.mark.timeout(1800)
@pytest.mark.parametrize("slug", sorted(PDFS))
def test_a_real_fdre_tender_goes_from_upload_to_canonical(
    slug: str,
    settings: Settings,
    session_factory: sessionmaker[Session],
    db: Session,
    tmp_path: Path,
) -> None:
    pdf = PDFS[slug]
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not pdf.is_file():
        pytest.skip("needs ANTHROPIC_API_KEY and the tender set under /work/tenders")
    local = settings.model_copy(
        update={"anthropic_api_key": key, "data_dir": str(tmp_path / "data")}
    )
    storage, schemas = LocalStorage(local.data_dir), make_fdre_registry()
    llm = LLMClient(local, session_factory)
    runner = Runner(local, session_factory, storage, schemas, llm)
    client = TestClient(create_app(local, schemas, storage, llm))

    uploaded = client.post(
        "/api/v1/documents", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["id"]
    runner.run_until_idle()
    document = client.get(f"/api/v1/documents/{document_id}").json()
    assert document["status"] == "parsed", _job_errors(db)
    sections = client.get(f"/api/v1/documents/{document_id}/sections").json()
    assert sections, _job_errors(db)
    render = client.get(f"/api/v1/documents/{document_id}/pages/1/render")
    assert render.status_code == 200 and render.content.startswith(b"\x89PNG")

    started = client.post(
        f"/api/v1/documents/{document_id}/extract",
        json={
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "prompt_version": "v1",
        },
    )
    assert started.status_code == 202
    runner.run_until_idle()
    run = client.get(f"/api/v1/extraction-runs/{started.json()['id']}").json()
    assert run["status"] == "validated", _job_errors(db)

    params = {"object_type": "document", "object_id": document_id}
    state = client.get("/api/v1/review-state", params=params).json()
    fields: list[dict[str, Any]] = state["fields"]

    print(f"\ndocument: {pdf.name} ({document['page_count']} pages, {len(sections)} sections)")
    print(
        f"run: model={run['model']} tokens_in={run['token_in']} tokens_out={run['token_out']} "
        f"cost_usd={run['cost_usd']}"
    )
    print("field | value | confidence | status | evidence page (resolution, score) | failed rules")
    unlocated: list[str] = []
    for field in fields:
        candidate = field["candidate"]
        if candidate is None:
            print(f"{field['field_path']} | (no candidate)")
            unlocated.append(field["field_path"])
            continue
        spans = candidate["evidence"]
        where = ", ".join(
            f"p{span['page_no']} ({span['resolution']}, {span['match_score']})" for span in spans
        )
        failed = ", ".join(v["rule_name"] for v in candidate["validation"] if not v["passed"])
        print(
            f"{field['field_path']} | {candidate['value']!r} | {candidate['confidence']:.2f} | "
            f"{candidate['status']} | {where or '-'} | {failed or '-'}"
        )
        print(f"    rationale: {' '.join(candidate['rationale'].split())[:260]}")
        has_value = candidate["value"] is not None
        if has_value and not any(span["char_start"] is not None for span in spans):
            unlocated.append(field["field_path"])

    assert len(fields) == 12
    assert db.scalar(select(CanonicalFact.id).limit(1)) is None, "no truth before a human decision"
    assert not unlocated, f"evidence not located for: {unlocated}"

    number = next(f for f in fields if f["field_path"] == "identity.tender_number")["candidate"]
    approved = client.post(
        "/api/v1/approvals",
        json={"candidate_id": number["id"], "decision": "approved"},
        headers=REVIEWER,
    )
    assert approved.status_code == 201, approved.text
    canonical = client.get("/api/v1/canonical", params=params).json()
    assert [fact["field_path"] for fact in canonical] == ["identity.tender_number"]
    assert canonical[0]["value"] == number["value"] and canonical[0]["evidence"]
    print(f"approved identity.tender_number -> canonical value {canonical[0]['value']!r}")


def _job_errors(db: Session) -> str:
    """Why the chain stopped: failed or requeued jobs and failed runs, for the assert message."""
    db.rollback()
    lines = [
        f"job {job.kind} {job.status} attempts={job.attempts}: {(job.last_error or '')[-600:]}"
        for job in db.scalars(select(Job).where(Job.last_error.is_not(None)))
    ]
    lines += [
        f"run {run.id} {run.status}: {run.error}"
        for run in db.scalars(select(ExtractionRun).where(ExtractionRun.error.is_not(None)))
    ]
    return "\n".join(lines) or "no job errors recorded"
