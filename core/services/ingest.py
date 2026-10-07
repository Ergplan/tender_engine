"""IngestService: accept an upload, deduplicate on sha256, store it, enqueue parsing."""

import hashlib
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models import Document
from core.services import jobs
from core.storage import Storage


class IngestError(ValueError):
    pass


class IngestService:
    def __init__(self, storage: Storage, tenant_id: str) -> None:
        self._storage = storage
        self._tenant_id = tenant_id

    def upload(
        self,
        session: Session,
        *,
        filename: str,
        data: bytes,
        created_by: str,
        source_url: str | None = None,
        retrieved_on: date | None = None,
    ) -> tuple[Document, bool]:
        """Returns (document, created). An identical file returns the existing document;
        provenance given for it fills what the existing document lacks, never overwrites."""
        if not data.startswith(b"%PDF-"):
            raise IngestError("the file is not a PDF")
        sha256 = hashlib.sha256(data).hexdigest()
        by_hash = select(Document).where(
            Document.tenant_id == self._tenant_id, Document.sha256 == sha256
        )
        existing = session.scalar(by_hash)
        if existing is not None:
            if fill_provenance(existing, source_url, retrieved_on):
                session.commit()
            return existing, False
        key = self._storage.put(f"documents/{sha256}.pdf", data)
        document = Document(
            tenant_id=self._tenant_id,
            created_by=created_by,
            sha256=sha256,
            filename=filename,
            mime="application/pdf",
            storage_path=key,
            status="uploaded",
            source_url=source_url,
            retrieved_on=retrieved_on,
        )
        session.add(document)
        try:
            session.flush()
        except IntegrityError:
            # The same file was uploaded by another request a moment ago.
            session.rollback()
            return session.scalars(by_hash).one(), False
        jobs.enqueue(
            session,
            tenant_id=self._tenant_id,
            kind="parse",
            payload={"document_id": document.id},
            created_by=created_by,
        )
        session.commit()
        return document, True


def fill_provenance(document: Document, source_url: str | None, retrieved_on: date | None) -> bool:
    """Set the provenance the document lacks. Returns whether anything changed."""
    changed = False
    if source_url and document.source_url is None:
        document.source_url = source_url
        changed = True
    if retrieved_on and document.retrieved_on is None:
        document.retrieved_on = retrieved_on
        changed = True
    return changed
