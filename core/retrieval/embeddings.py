"""The embedding side of retrieval, behind one switch (`EMBEDDINGS_PROVIDER`): `local` (an
ONNX model on the VM through fastembed, `BAAI/bge-small-en-v1.5` at the table's dimension;
nothing leaves the machine) or `none` (full-text search alone). The owner's decision of
2026-10-25 took OpenAI out. Embedding runs are logged like model calls (`llm_call_log`,
prompt `embed_chunks`, model the local model's name, cost 0), so the ledger says what was
embedded and when, and a failure is on record with its reason."""

import hashlib
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from haystack import Document
from sqlalchemy.orm import Session

from core.config import Settings
from core.models import LLMCallLog

log = logging.getLogger("retrieval")
PROMPT_NAME = "embed_chunks"
PROMPT_VERSION = "v1"


@dataclass
class Embedders:
    """The two embedders a provider gives (documents at index time, the question at query
    time), or neither with the reason."""

    provider: str
    documents: Any | None
    text: Any | None
    reason: str = ""
    model: str = ""

    @property
    def enabled(self) -> bool:
        return self.documents is not None and self.text is not None


def make_embedders(settings: Settings) -> Embedders:
    provider = settings.embeddings_provider
    if provider == "none":
        return Embedders("none", None, None, "EMBEDDINGS_PROVIDER=none: full-text search alone")
    if provider == "local":
        model = settings.local_embedding_model
        try:
            from haystack_integrations.components.embedders.fastembed import (
                FastembedDocumentEmbedder,
                FastembedTextEmbedder,
            )

            cache = Path(settings.embeddings_cache_dir)
            cache.mkdir(parents=True, exist_ok=True)
            # One thread pool per process; the VM has two cores and the worker shares them
            # with pdfplumber and the API.
            documents = FastembedDocumentEmbedder(
                model=model, cache_dir=str(cache), threads=2, progress_bar=False, batch_size=32
            )
            text = FastembedTextEmbedder(model=model, cache_dir=str(cache), threads=2)
            documents.warm_up()
            text.warm_up()
        except Exception as exc:  # the model files are missing and cannot be fetched, …
            log.warning("local embedder unavailable: %s", exc)
            return Embedders("local", None, None, f"local embedder unavailable: {exc}", model)
        return Embedders("local", documents, text, model=model)
    return Embedders(provider, None, None, f"unknown EMBEDDINGS_PROVIDER {provider!r}")


def embed_documents(
    embedders: Embedders,
    documents: list[Document],
    *,
    session: Session,
    settings: Settings,
    created_by: str,
) -> tuple[list[Document], str | None]:
    """Embed the documents in place; log the run. Returns the documents and, when the
    provider failed, the reason (the documents then carry no embedding)."""
    if embedders.documents is None or not documents:
        return documents, embedders.reason or None
    started = time.monotonic()
    digest = hashlib.sha256("".join(d.id for d in documents).encode()).hexdigest()
    chars = sum(len(d.content or "") for d in documents)
    try:
        result = embedders.documents.run(documents=documents)
    except Exception as exc:
        _log(
            session,
            settings,
            created_by=created_by,
            model=embedders.model,
            input_hash=digest,
            status="error",
            error=str(exc)[:2000],
            chars=chars,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        log.warning("embedding failed: %s", exc)
        return documents, f"embedding failed: {exc}"
    _log(
        session,
        settings,
        created_by=created_by,
        model=embedders.model,
        input_hash=digest,
        status="ok",
        error=None,
        chars=chars,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return result["documents"], None


def _log(
    session: Session,
    settings: Settings,
    *,
    created_by: str,
    model: str,
    input_hash: str,
    status: str,
    error: str | None,
    chars: int,
    latency_ms: int,
) -> None:
    """One row per embedding run. A local model has no price and reports no token count;
    `tokens_in` carries the characters embedded divided by four, the usual estimate, so
    the size of the run is on record; `cost_usd` is 0."""
    session.add(
        LLMCallLog(
            tenant_id=settings.tenant_id,
            created_by=created_by,
            prompt_name=PROMPT_NAME,
            prompt_version=PROMPT_VERSION,
            output_schema="embedding",
            model=model or settings.embeddings_provider,
            input_hash=input_hash,
            output=None,
            status=status,
            error=error,
            tokens_in=chars // 4,
            tokens_out=0,
            cost_usd=Decimal(0),
            latency_ms=latency_ms,
        )
    )
    session.flush()
