"""Slow: one real model call with a real tender PDF as native document input."""

import base64
import os
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.llm.client import LLMClient, LLMRequest, PdfPart, TextPart
from core.llm.smoke import SmokeResult
from core.models import LLMCallLog

PDF = Path("/work/tenders/solar/seci-cni-1-700mw/Pre-Bid_meeting_notification48.pdf")


@pytest.mark.slow
def test_model_reads_a_real_tender_pdf_and_the_call_is_logged(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not PDF.is_file():
        pytest.skip("needs ANTHROPIC_API_KEY and the tender set under /work/tenders")
    client = LLMClient(settings.model_copy(update={"anthropic_api_key": key}), session_factory)

    response = client.call(
        LLMRequest[SmokeResult](
            prompt_name="smoke",
            prompt_version="v1",
            content=[
                PdfPart(data_b64=base64.standard_b64encode(PDF.read_bytes()).decode()),
                TextPart(text="Which organisation issued this document?"),
            ],
            response_model=SmokeResult,
            created_by="e2e",
            max_tokens=2000,
        )
    )

    assert response.parsed.saw_document is True
    assert "solar energy corporation" in response.parsed.answer.lower() or "SECI" in (
        response.parsed.answer
    )
    row = db.get(LLMCallLog, response.call_log_id)
    assert row is not None and row.status == "ok" and row.tokens_in > 0
    print(f"\nanswer={response.parsed.answer!r}\nquote={response.parsed.quote!r}")
    print(f"tokens_in={row.tokens_in} tokens_out={row.tokens_out} latency_ms={row.latency_ms}")
