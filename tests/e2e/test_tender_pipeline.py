"""Slow: the Stage 2 end-to-end run. A real tender (an NTPC notice inviting tenders, three
pages) goes through the tender API and the worker with the real model: create, upload as
the original version, parse, section map, extract every section, validate, approve one
field, read the current view.

Prints one line per field. Run with `make test-e2e`. The full tender set is extracted by
`python -m scripts.ingest_tenders`, not by this test.
"""

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from api.main import create_app
from core.config import Settings
from core.llm.client import LLMClient
from core.storage import LocalStorage
from tender.services.packs import build_registry
from tests.e2e.test_fdre_core_pipeline import _job_errors
from worker.runner import Runner

PDF = Path("/work/tenders/generation/ntpc-phes-2000mw/job_45538.pdf")
REVIEWER = {"X-Reviewer": "e2e"}
TARGET = 0.95


@pytest.mark.slow
@pytest.mark.timeout(1800)
def test_a_real_tender_goes_from_upload_to_the_current_view(
    settings: Settings, session_factory: sessionmaker[Session], db: Session, tmp_path: Path
) -> None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not PDF.is_file():
        pytest.skip("needs ANTHROPIC_API_KEY and the tender set under /work/tenders")
    local = settings.model_copy(
        update={"anthropic_api_key": key, "data_dir": str(tmp_path / "data")}
    )
    storage = LocalStorage(local.data_dir)
    schemas, catalog = build_registry()
    llm = LLMClient(local, session_factory, prompt_roots=catalog.prompt_roots)
    runner = Runner(local, session_factory, storage, schemas, llm)
    client = TestClient(create_app(local, schemas, storage, llm, catalog))

    created = client.post(
        "/api/v1/tenders",
        json={
            "type": "generation",
            "agency": "NTPC Renewable Energy Ltd",
            "external_ref": "NRE-CS-5846-004",
            "title": "Pumped hydro energy storage of 2000 MW / 12000 MWh (NIT)",
        },
        headers=REVIEWER,
    )
    assert created.status_code == 201, created.text
    tender_id = created.json()["id"]
    version = client.post(
        f"/api/v1/tenders/{tender_id}/versions",
        files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
        data={"kind": "original", "role": "nit", "issued_on": "2026-05-29"},
        headers=REVIEWER,
    )
    assert version.status_code == 201, version.text
    runner.run_until_idle()
    started = client.post(f"/api/v1/tenders/{tender_id}/extract", json={}, headers=REVIEWER)
    assert started.status_code == 202, started.text + _job_errors(db)
    runner.run_until_idle()
    assert client.get(f"/api/v1/tenders/{tender_id}").json()["status"] == "extracted", _job_errors(
        db
    )

    body = client.get(f"/api/v1/tenders/{tender_id}/review-state").json()
    fields: list[dict[str, Any]] = body["state"]["fields"]
    runs = [client.get(f"/api/v1/extraction-runs/{run['id']}").json() for run in started.json()]
    print(f"\ntender: {PDF.name}, schema {body['state']['run']['schema_name']}")
    print(
        f"tokens_in={sum(r['token_in'] for r in runs)} "
        f"tokens_out={sum(r['token_out'] for r in runs)} "
        f"cost_usd={sum(float(r['cost_usd']) for r in runs):.4f}"
    )
    print("field | value | confidence | status | evidence page (resolution) | failed rules")
    returned = located = 0
    for field in fields:
        candidate = field["candidate"]
        assert candidate is not None, f"{field['field_path']} has no candidate"
        spans = candidate["evidence"]
        where = ", ".join(f"p{span['page_no']} ({span['resolution']})" for span in spans)
        failed = ", ".join(v["rule_name"] for v in candidate["validation"] if not v["passed"])
        value = " ".join(str(candidate["value"]).split())[:120]
        print(
            f"{field['field_path']} | {value} | {candidate['confidence']:.2f} | "
            f"{candidate['status']} | {where or '-'} | {failed or '-'}"
        )
        if candidate["value"] is not None:
            returned += 1
            located += any(span["char_start"] is not None for span in spans)
    print(f"evidence-location rate {located}/{returned}; answer rate {returned}/{len(fields)}")
    assert len(fields) == len(catalog.get("generation").fields)
    assert returned >= 5, "a notice inviting tenders states at least its identity and dates"
    assert located / returned >= TARGET

    view = client.get(f"/api/v1/tenders/{tender_id}/view").json()
    assert view["decided"] == 0, "no truth before a human decision"
    number = next(f for f in fields if f["field_path"] == "core.identity.tender_number")
    approved = client.post(
        "/api/v1/approvals",
        json={"candidate_id": number["candidate"]["id"], "decision": "approved"},
        headers=REVIEWER,
    )
    assert approved.status_code == 201, approved.text
    view = client.get(f"/api/v1/tenders/{tender_id}/view").json()
    shown = next(f for f in view["fields"] if f["field_path"] == "core.identity.tender_number")
    assert (view["decided"], shown["version_no"], shown["version_kind"]) == (1, 1, "original")
    assert shown["value"] == number["candidate"]["value"] and shown["evidence"]
    print(f"approved core.identity.tender_number -> canonical value {shown['value']!r}")
