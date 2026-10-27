"""The chunk table of retrieval (Stage 7, Block 5). Its shape is Haystack's pgvector
document store's (id, embedding, content, blob_*, meta) plus `tenant_id`, which the
database fills from the connection's scope and row-level security binds like every other
table (migration 0023). Rows are written and read by `core.retrieval`, never by hand."""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base

EMBEDDING_DIMENSION = 384  # BAAI/bge-small-en-v1.5, the local model (migration 0023)


class RetrievalChunk(Base):
    __tablename__ = "retrieval_chunk"
    # The indexes migration 0023 made, as Postgres reports them, so `alembic check` finds
    # the model and the database alike: Haystack's keyword index under the name its store
    # looks for, the two meta look-ups the indexer and the filters use, the tenant.
    __table_args__ = (
        Index(
            "haystack_keyword_index",
            text("to_tsvector('english'::regconfig, content)"),
            postgresql_using="gin",
        ),
        Index("ix_retrieval_chunk_document", text("((meta ->> 'document_id'::text))")),
        Index("ix_retrieval_chunk_tender", text("((meta ->> 'tender_id'::text))")),
        Index("ix_retrieval_chunk_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    blob_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    blob_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    blob_mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenant.tenant_id"),
        nullable=False,
        server_default=text("current_setting('app.tenant_id', true)"),
    )
    # The audit columns every table carries (migration 0024). Haystack's insert names only
    # its own columns, so the database fills these; the indexer then writes the actor it
    # ran for on the chunks it wrote (`ChunkIndexer.index_document`).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default=text("'retrieval'")
    )
