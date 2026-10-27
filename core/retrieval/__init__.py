"""Retrieval over document text (Stage 7, Block 5): chunks of pages in the existing
Postgres (pgvector), a Haystack pipeline with hybrid retrieval (full-text search plus
embeddings), and the indexer the worker runs after a document's section map.

Nothing here writes a fact. The chunks are a projection of `page.text`; dropping the table
loses nothing that a re-index does not bring back."""

from core.retrieval.chunks import Chunk, chunk_page
from core.retrieval.embeddings import Embedders, make_embedders
from core.retrieval.indexer import ChunkIndexer, IndexResult, job_handlers
from core.retrieval.query import Hit, Retriever
from core.retrieval.store import TABLE, ChunkStores, TenantChunkStore

__all__ = [
    "TABLE",
    "Chunk",
    "ChunkIndexer",
    "ChunkStores",
    "Embedders",
    "Hit",
    "IndexResult",
    "Retriever",
    "TenantChunkStore",
    "chunk_page",
    "job_handlers",
    "make_embedders",
]
