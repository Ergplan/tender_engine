"""The query side: a Haystack pipeline with hybrid retrieval. Full-text search
(`PgvectorKeywordRetriever`, Postgres `ts_rank_cd`) and, when an embedder is configured,
embedding retrieval (`PgvectorEmbeddingRetriever`, cosine) joined by reciprocal rank
fusion. Filters (tender, documents of the version asked about) apply to both legs. When the
embedding leg fails at query time (the key is wrong, the provider is down) the keyword leg's
answer is returned and the mode says so: the caller is never left without an answer and
never told the search was hybrid when it was not."""

import logging
from dataclasses import dataclass
from typing import Any

from haystack import Document, Pipeline
from haystack.components.joiners import DocumentJoiner
from haystack.document_stores.types import FilterPolicy
from haystack_integrations.components.retrievers.pgvector import (
    PgvectorEmbeddingRetriever,
    PgvectorKeywordRetriever,
)

from core.retrieval.embeddings import Embedders
from core.retrieval.store import TenantChunkStore

log = logging.getLogger("retrieval")


@dataclass(frozen=True)
class Hit:
    id: str
    content: str
    score: float | None
    meta: dict[str, Any]


def _hit(document: Document) -> Hit:
    return Hit(document.id, document.content or "", document.score, dict(document.meta))


class Retriever:
    def __init__(self, store: TenantChunkStore, embedders: Embedders, top_k: int = 8) -> None:
        self._store = store
        self._embedders = embedders
        self._top_k = top_k
        self._keyword = PgvectorKeywordRetriever(
            document_store=store, top_k=top_k * 2, filter_policy=FilterPolicy.REPLACE
        )
        self._pipeline: Pipeline | None = None
        if embedders.enabled:
            assert embedders.text is not None
            pipeline = Pipeline()
            pipeline.add_component("embedder", embedders.text)
            pipeline.add_component(
                "embedding",
                PgvectorEmbeddingRetriever(
                    document_store=store, top_k=top_k * 2, filter_policy=FilterPolicy.REPLACE
                ),
            )
            pipeline.add_component("keyword", self._keyword)
            pipeline.add_component(
                "joiner", DocumentJoiner(join_mode="reciprocal_rank_fusion", top_k=top_k)
            )
            pipeline.connect("embedder.embedding", "embedding.query_embedding")
            pipeline.connect("embedding.documents", "joiner.documents")
            pipeline.connect("keyword.documents", "joiner.documents")
            self._pipeline = pipeline

    @property
    def mode(self) -> str:
        return "hybrid" if self._pipeline is not None else "keyword"

    def retrieve(self, question: str, filters: dict[str, Any] | None) -> tuple[list[Hit], str]:
        """The best chunks for the question under the filters, and the mode that found
        them: `hybrid`, `keyword`, or `keyword (embedding failed: …)`."""
        question = question.strip()
        if not question:
            return [], self.mode
        with self._store.lock:
            if self._pipeline is not None:
                try:
                    out = self._pipeline.run(
                        {
                            "embedder": {"text": question},
                            "embedding": {"filters": filters},
                            "keyword": {"query": question, "filters": filters},
                        }
                    )
                    return [_hit(d) for d in out["joiner"]["documents"]], "hybrid"
                except Exception as exc:
                    log.warning("embedding leg failed, keyword alone: %s", exc)
                    mode = f"keyword (embedding failed: {type(exc).__name__})"
            else:
                mode = "keyword"
            out = self._keyword.run(query=question, filters=filters, top_k=self._top_k)
            return [_hit(d) for d in out["documents"]], mode
