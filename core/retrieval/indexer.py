"""The indexer: a parsed, section-mapped document becomes chunks in the store, with the
page, clause, section and whatever the domain layer adds (tender, version, role) on each
chunk. Safe to re-run: a document's chunks are replaced. The worker runs it as the
`index_document` job after `section_map`; `embed_pending` embeds chunks written while the
embedding provider was down (the key missing, the service unreachable)."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from haystack import Document as HDocument
from haystack.document_stores.types import DuplicatePolicy
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.config import Settings
from core.models import Document, Page, RetrievalChunk, Section
from core.retrieval.chunks import chunk_page, last_clause
from core.retrieval.embeddings import Embedders, embed_documents
from core.retrieval.store import TenantChunkStore

log = logging.getLogger("retrieval")
MetaFor = Callable[[Session, Document], dict[str, Any]]


@dataclass(frozen=True)
class IndexResult:
    document_id: str
    chunks: int
    embedded: bool
    seconds: float
    note: str = ""


class ChunkIndexer:
    def __init__(
        self,
        store: TenantChunkStore,
        embedders: Embedders,
        settings: Settings,
        *,
        meta_for: MetaFor | None = None,
    ) -> None:
        self._store = store
        self._embedders = embedders
        self._settings = settings
        self._tenant_id = settings.tenant_id
        self._meta_for = meta_for

    def index_document(
        self, session: Session, document_id: str, *, created_by: str = "worker"
    ) -> IndexResult:
        started = time.monotonic()
        document = session.scalar(
            select(Document).where(
                Document.id == document_id, Document.tenant_id == self._tenant_id
            )
        )
        if document is None or document.status != "parsed":
            raise LookupError(f"document {document_id} is not parsed")
        pages = session.scalars(
            select(Page)
            .where(Page.document_id == document.id, Page.tenant_id == self._tenant_id)
            .order_by(Page.page_no)
        ).all()
        sections = session.scalars(
            select(Section)
            .where(Section.document_id == document.id, Section.tenant_id == self._tenant_id)
            .order_by(Section.start_page)
        ).all()
        extra = self._meta_for(session, document) if self._meta_for else {}
        docs: list[HDocument] = []
        carry: str | None = None
        for page in pages:
            section = next(
                (s for s in sections if s.start_page <= page.page_no <= s.end_page), None
            )
            chunks = chunk_page(page.page_no, page.text, carry_clause=carry)
            for chunk in chunks:
                docs.append(
                    HDocument(
                        id=chunk.id(document.id),
                        content=chunk.text,
                        meta={
                            "document_id": document.id,
                            "filename": document.filename,
                            "page_no": chunk.page_no,
                            "clause": chunk.clause,
                            "char_start": chunk.char_start,
                            "char_end": chunk.char_end,
                            "section_kind": section.kind if section else None,
                            "section_heading": section.heading if section else None,
                            "parser_layer": page.parser_layer,
                            "embedded": False,
                            **extra,
                        },
                    )
                )
            carry = last_clause(chunks) or carry
        docs, failure = embed_documents(
            self._embedders, docs, session=session, settings=self._settings, created_by="worker"
        )
        embedded = failure is None and self._embedders.enabled
        for doc in docs:
            doc.meta["embedded"] = embedded and doc.embedding is not None
        with self._store.lock:
            old = [d.id for d in self._store.chunks_of(document.id)]
            if old:
                self._store.delete_documents(old)
            if docs:
                self._store.write_documents(docs, policy=DuplicatePolicy.OVERWRITE)
        if docs:
            # The audit column the store's own insert cannot fill: who the chunks were
            # written for (the database stamps `created_at`).
            session.execute(
                update(RetrievalChunk)
                .where(RetrievalChunk.meta["document_id"].astext == document.id)
                .values(created_by=created_by)
            )
        session.commit()
        result = IndexResult(
            document.id, len(docs), embedded, time.monotonic() - started, failure or ""
        )
        log.info(
            "indexed %s: %d chunks, embedded=%s %s", document.id, len(docs), embedded, failure or ""
        )
        return result

    def embed_pending(self, session: Session, limit: int = 2000) -> int:
        """Embed chunks written without an embedding. Returns how many were embedded."""
        if not self._embedders.enabled:
            return 0
        with self._store.lock:
            pending = self._store.filter_documents(
                {"field": "meta.embedded", "operator": "==", "value": False}
            )[:limit]
        if not pending:
            return 0
        docs, failure = embed_documents(
            self._embedders, pending, session=session, settings=self._settings, created_by="worker"
        )
        if failure is not None:
            session.commit()
            return 0
        for doc in docs:
            doc.meta["embedded"] = doc.embedding is not None
        with self._store.lock:
            self._store.write_documents(docs, policy=DuplicatePolicy.OVERWRITE)
        session.commit()
        return sum(1 for d in docs if d.embedding is not None)


def job_handlers(indexer: ChunkIndexer) -> dict[str, Callable[[Session, dict[str, Any]], None]]:
    def index(session: Session, payload: dict[str, Any]) -> None:
        indexer.index_document(
            session, payload["document_id"], created_by=str(payload.get("created_by") or "worker")
        )

    def pending(session: Session, payload: dict[str, Any]) -> None:
        indexer.embed_pending(session, int(payload.get("limit", 2000)))

    return {"index_document": index, "embed_pending": pending}
