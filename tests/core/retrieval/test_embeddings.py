"""The embedding switch (Stage 7, Block 5): `none` and an unknown provider give no embedder
with the reason; a provider that fails is a logged failure, not a crash, and the chunks
are written without embeddings; a run that works is logged with its size and no cost."""

from decimal import Decimal
from typing import Any

import pytest
from haystack import Document
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import LLMCallLog
from core.retrieval.embeddings import Embedders, embed_documents, make_embedders
from tests.conftest import Pipeline


class _Embedder:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def run(self, documents: list[Document]) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("model file missing")
        for doc in documents:
            doc.embedding = [0.1, 0.2, 0.3]
        return {"documents": documents}


def test_none_and_unknown_providers_give_no_embedder_with_the_reason(pipeline: Pipeline) -> None:
    none = make_embedders(pipeline.settings.model_copy(update={"embeddings_provider": "none"}))
    assert not none.enabled and "full-text search alone" in none.reason
    bad = make_embedders(pipeline.settings.model_copy(update={"embeddings_provider": "other"}))
    assert not bad.enabled and "unknown" in bad.reason


def test_the_local_provider_that_cannot_load_is_reported_not_raised(
    pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    import haystack_integrations.components.embedders.fastembed as fastembed

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no network, no cached model")

    monkeypatch.setattr(fastembed, "FastembedDocumentEmbedder", boom)
    settings = pipeline.settings.model_copy(
        update={"embeddings_provider": "local", "embeddings_cache_dir": "/tmp/fastembed-test"}
    )
    embedders = make_embedders(settings)
    assert not embedders.enabled
    assert "unavailable" in embedders.reason and "no network" in embedders.reason
    assert embedders.model == settings.local_embedding_model


def test_a_run_is_logged_with_its_size_and_a_failure_with_its_reason(
    pipeline: Pipeline, db: Session
) -> None:
    docs = [Document(id="a", content="x" * 400), Document(id="b", content="y" * 400)]
    good = Embedders("local", _Embedder(), _Embedder(), model="BAAI/bge-small-en-v1.5")
    out, failure = embed_documents(
        good, docs, session=db, settings=pipeline.settings, created_by="pytest"
    )
    assert failure is None and all(d.embedding for d in out)
    row = db.scalars(
        select(LLMCallLog)
        .where(LLMCallLog.prompt_name == "embed_chunks")
        .order_by(LLMCallLog.created_at.desc())
    ).first()
    assert row is not None
    assert (row.status, row.model, row.tokens_in, row.cost_usd) == (
        "ok",
        "BAAI/bge-small-en-v1.5",
        200,
        Decimal(0),
    )
    assert row.created_by == "pytest" and row.output_schema == "embedding"

    bad = Embedders("local", _Embedder(fail=True), _Embedder(), model="BAAI/bge-small-en-v1.5")
    fresh = [Document(id="c", content="z" * 100)]
    out, failure = embed_documents(
        bad, fresh, session=db, settings=pipeline.settings, created_by="pytest"
    )
    assert failure is not None and "model file missing" in failure
    assert out[0].embedding is None
    err = db.scalars(
        select(LLMCallLog)
        .where(LLMCallLog.prompt_name == "embed_chunks", LLMCallLog.status == "error")
        .order_by(LLMCallLog.created_at.desc())
    ).first()
    assert err is not None and err.error is not None and "model file missing" in err.error

    disabled = Embedders("none", None, None, "EMBEDDINGS_PROVIDER=none: full-text search alone")
    out, failure = embed_documents(
        disabled, fresh, session=db, settings=pipeline.settings, created_by="pytest"
    )
    assert failure == disabled.reason and out is fresh
