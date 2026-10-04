"""Management command: one real call to the extraction model, logged in llm_call_log.

Usage: python -m scripts.llm_smoke [path/to/small.pdf]
Proves the key, the model id and the typed-output path. Not part of the test suite.
"""

import base64
import sys
from pathlib import Path

from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient, LLMRequest, PdfPart, TextPart
from core.llm.smoke import SmokeResult


def main(argv: list[str]) -> int:
    settings = Settings()
    engine = make_engine(settings)
    client = LLMClient(settings, make_session_factory(engine))
    content: list[TextPart | PdfPart] = []
    if len(argv) > 1:
        pdf = Path(argv[1])
        content.append(
            PdfPart(data_b64=base64.standard_b64encode(pdf.read_bytes()).decode(), title=pdf.name)
        )
        content.append(TextPart(text="Which organisation issued this document?"))
    else:
        content.append(TextPart(text="Reply that the connection works."))
    response = client.call(
        LLMRequest(
            prompt_name="smoke",
            prompt_version="v1",
            content=content,
            response_model=SmokeResult,
            created_by="llm_smoke",
            max_tokens=2000,
        )
    )
    print(f"model={response.model} log_id={response.call_log_id}")
    print(f"tokens_in={response.tokens_in} tokens_out={response.tokens_out}")
    print(f"latency_ms={response.latency_ms} stop_reason={response.stop_reason}")
    print(f"answer={response.parsed.answer!r}")
    print(f"saw_document={response.parsed.saw_document} quote={response.parsed.quote!r}")
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
