"""IngestService: accept an upload, deduplicate on sha256, store it, enqueue parsing."""

import hashlib

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
        self, session: Session, *, filename: str, data: bytes, created_by: str
    ) -> tuple[Document, bool]:
        """Returns (document, created). An identical file returns the existing document."""
        if not data.startswith(b"%PDF-"):
            raise IngestError("the file is not a PDF")
        sha256 = hashlib.sha256(data).hexdigest()
        by_hash = select(Document).where(
            Document.tenant_id == self._tenant_id, Document.sha256 == sha256
        )
        existing = session.scalar(by_hash)
        if existing is not None:
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
