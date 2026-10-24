"""IngestService: accept an upload, deduplicate on sha256, store it, enqueue parsing."""

import hashlib
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models import Document
from core.services import jobs
from core.services.inputs import InputError, Kind, Rejected, bundle_members, normalise
from core.storage import Storage

# What the upload was, kept as the document's media type; the stored file is always a PDF.
MIME_BY_KIND: dict[Kind, str] = {
    "pdf": "application/pdf",
    "spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "zip": "application/zip",
}


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
        provenance given for it fills what the existing document lacks, never overwrites.
        What is stored is always a PDF (`core.services.inputs.normalise`): a workbook or a
        .docx is rendered to a text PDF, a protected PDF saved plain; the sha256 and the
        filename are the upload's own, the media type says what the upload was. A .zip is
        refused here: `upload_bundle` opens it."""
        try:
            kind, stored = normalise(filename, data)
        except InputError as exc:
            raise IngestError(str(exc)) from exc
        sha256 = hashlib.sha256(data).hexdigest()
        by_hash = select(Document).where(
            Document.tenant_id == self._tenant_id, Document.sha256 == sha256
        )
        existing = session.scalar(by_hash)
        if existing is not None:
            if fill_provenance(existing, source_url, retrieved_on):
                session.commit()
            return existing, False
        key = self._storage.put(f"documents/{sha256}.pdf", stored)
        document = Document(
            tenant_id=self._tenant_id,
            created_by=created_by,
            sha256=sha256,
            filename=filename,
            mime=MIME_BY_KIND[kind],
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

    def upload_bundle(
        self,
        session: Session,
        *,
        filename: str,
        data: bytes,
        created_by: str,
        source_url: str | None = None,
        retrieved_on: date | None = None,
    ) -> tuple[list[tuple[str, Document, bool]], list[Rejected]]:
        """A .zip of a tender pack: every member that is a document is uploaded as one
        (member name, document, created), in archive order; the members left out come back
        with their reasons. A member that fails to normalise is rejected, not fatal."""
        try:
            members, rejected = bundle_members(data)
        except InputError as exc:
            raise IngestError(str(exc)) from exc
        uploaded: list[tuple[str, Document, bool]] = []
        for member in members:
            try:
                document, created = self.upload(
                    session,
                    filename=member.name.rsplit("/", 1)[-1],
                    data=member.data,
                    created_by=created_by,
                    source_url=source_url,
                    retrieved_on=retrieved_on,
                )
            except IngestError as exc:
                rejected.append(Rejected(member.name, str(exc)))
                continue
            uploaded.append((member.name, document, created))
        if not uploaded and not rejected:
            raise IngestError(f"{filename}: the bundle holds no document")
        return uploaded, rejected


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
