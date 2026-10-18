"""Slow: the Stage 5A end-to-end run. A real tender document (a SECI pre-bid notice, a few
pages) is parsed and section-mapped with the real extraction model, then read by the
independent agent on the real OpenAI model through its three tools. Prints the run's
turns, tokens and cost. Run with `make test-e2e`; it spends money on both providers.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from agent.main import AgentWorker
from agent.service import AgentPassService, real_driver
from api.main import create_app
from core.config import Settings
from core.llm.client import LLMClient
from core.models import LLMCallLog
from core.services.extract import ExtractService
from core.storage import LocalStorage
from tender.services.packs import build_registry
from tender.services.tenders import TenderService
from tests.e2e.test_fdre_core_pipeline import _job_errors
from worker.runner import Runner

PDF = Path("/work/tenders/solar/seci-cni-1-700mw/Pre-Bid_meeting_notification48.pdf")
REVIEWER = {"X-Reviewer": "e2e"}


@pytest.mark.slow
@pytest.mark.timeout(2400)
def test_the_agent_reads_a_real_tender_and_its_findings_carry_located_evidence(
    settings: Settings, session_factory: sessionmaker[Session], db: Session, tmp_path: Path
) -> None:
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not anthropic_key or not openai_key or not PDF.is_file():
        pytest.skip(
            "needs ANTHROPIC_API_KEY, OPENAI_API_KEY and the tender set under /work/tenders"
        )
    local = settings.model_copy(
        update={
            "anthropic_api_key": anthropic_key,
            "openai_api_key": openai_key,
            "data_dir": str(tmp_path / "data"),
        }
    )
    storage = LocalStorage(local.data_dir)
    schemas, catalog = build_registry()
    llm = LLMClient(local, session_factory, prompt_roots=catalog.prompt_roots)
    runner = Runner(local, session_factory, storage, schemas, llm)
    client = TestClient(create_app(local, schemas, storage, llm, catalog))

    created = client.post(
        "/api/v1/tenders",
        json={
            "type": "solar",
            "agency": "Solar Energy Corporation of India",
            "external_ref": "SECI/C&P/IPP/CnI-1/700MW",
            "title": "Pre-bid meeting notification, CnI-1 700 MW (e2e)",
        },
        headers=REVIEWER,
    )
    assert created.status_code == 201, created.text
    tender_id = created.json()["id"]
    version = client.post(
        f"/api/v1/tenders/{tender_id}/versions",
        files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
        data={"kind": "original", "role": "rfs"},
        headers=REVIEWER,
    )
    assert version.status_code == 201, version.text
    runner.run_until_idle()  # the real parse and section map; no extraction

    tenders = TenderService(catalog, ExtractService(llm, storage, schemas, local), local.tenant_id)
    service = AgentPassService(catalog, schemas, tenders, local, storage)
    tender = tenders.get(db, tender_id)
    run = service.start(db, tender, created_by="e2e")
    assert run.status == "queued" and run.pages_offered["1"], _job_errors(db)

    worker = AgentWorker(
        local, session_factory, service=service, driver=real_driver(local, session_factory, catalog)
    )
    assert worker.run_once() is True
    db.refresh(run)
    assert run.status in ("done", "stopped"), (run.status, run.error, _job_errors(db))
    assert run.turns > 0 and run.tokens_in > 0 and run.cost_usd > 0

    findings = service.findings(db, run)
    assert findings, "the agent submitted nothing"
    accepted = [f for f in findings if f.status == "accepted"]
    read = {int(no): set(pages) for no, pages in run.pages_read.items()}
    for finding in accepted:
        assert finding.evidence, finding.field_path
        for span in finding.evidence:
            assert span["char_start"] is not None, (finding.field_path, span["quote"])
            assert span["page_no"] in read[span["document_no"]], finding.field_path

    calls = db.scalars(select(LLMCallLog).where(LLMCallLog.agent_run_id == run.id)).all()
    assert len(calls) == run.turns and all(c.model == local.openai_model for c in calls)
    assert sum(c.cost_usd for c in calls) > 0

    by_status: dict[str, int] = {}
    for finding in findings:
        by_status[finding.status] = by_status.get(finding.status, 0) + 1
    print(
        f"\nagent pass on {PDF.name}: status={run.status} turns={run.turns} "
        f"tokens_in={run.tokens_in} (cached {run.tokens_cached}) tokens_out={run.tokens_out} "
        f"cost_usd={run.cost_usd} findings={by_status} pages_read={run.pages_read}"
    )
    if run.error:
        print(f"note: {run.error}")
    for finding in accepted:
        page = finding.evidence[0]
        print(
            f"  {finding.field_path} = {finding.value!r} ({finding.confidence:.2f}) "
            f"doc {page['document_no']} p{page['page_no']}: {page['quote'][:60]!r}"
        )
