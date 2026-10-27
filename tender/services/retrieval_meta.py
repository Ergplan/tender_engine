"""What the tender layer puts on a document's chunks: its tender, the version it arrived
with, its role and the tender type (`core.retrieval.ChunkIndexer`'s `meta_for`). A document
that belongs to no tender yet carries only its own fields; the index is rebuilt when it is
attached (`TenderService` queues `index_document` on attach)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Document
from tender.models import Tender, TenderVersion, TenderVersionDocument


def chunk_meta(session: Session, document: Document) -> dict[str, Any]:
    row = session.execute(
        select(
            Tender.id,
            Tender.slug,
            Tender.tender_type,
            TenderVersion.version_no,
            TenderVersion.kind,
            TenderVersionDocument.role,
        )
        .join(TenderVersion, TenderVersion.id == TenderVersionDocument.tender_version_id)
        .join(Tender, Tender.id == TenderVersion.tender_id)
        .where(
            TenderVersionDocument.document_id == document.id,
            TenderVersionDocument.tenant_id == document.tenant_id,
        )
        .order_by(TenderVersion.version_no)
        .limit(1)
    ).first()
    if row is None:
        return {}
    return {
        "tender_id": row.id,
        "tender_slug": row.slug,
        "tender_type": row.tender_type,
        "version_no": row.version_no,
        "version_kind": row.kind,
        "role": row.role,
    }
