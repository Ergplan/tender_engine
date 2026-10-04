"""TenderService: tenders, their versions and documents, and the extraction of a version.

A tender is never edited in place. Its original documents are version 1; every
corrigendum, amendment or clarification is a new version with its own documents.
Candidates, approvals and canonical facts of a tender are attached to
object_type='tender', object_id=tender.id, object_version=version_no.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Approval, Document, ExtractionRun, Page
from core.services import audit
from core.services.extract import ExtractService
from tender.models import (
    DOCUMENT_ROLES,
    TENDER_TYPES,
    VERSION_KINDS,
    Tender,
    TenderVersion,
    TenderVersionDocument,
)
from tender.services.packs import Catalog
from tender.services.versioning import CHANGE_ROLES, plan_groups

OBJECT_TYPE = "tender"
DEFAULT_ROLE = {
    "original": "rfs",
    "corrigendum": "amendment",
    "amendment": "amendment",
    "clarification": "clarification",
}


class TenderError(ValueError):
    """The request cannot be carried out as asked. The message is safe to show a user."""


@dataclass(frozen=True)
class VersionDocuments:
    version: TenderVersion
    documents: list[tuple[TenderVersionDocument, Document]]


class TenderService:
    def __init__(self, catalog: Catalog, extract: ExtractService, tenant_id: str) -> None:
        self._catalog = catalog
        self._extract = extract
        self._tenant_id = tenant_id

    def create(
        self,
        session: Session,
        *,
        tender_type: str,
        issuing_agency: str,
        external_ref: str | None,
        title: str,
        created_by: str,
        slug: str | None = None,
    ) -> Tender:
        if tender_type not in TENDER_TYPES:
            raise TenderError(f"unknown tender type {tender_type!r}; one of {list(TENDER_TYPES)}")
        self._catalog.get(tender_type)
        if not issuing_agency.strip() or not title.strip():
            raise TenderError("a tender needs an issuing agency and a title")
        tender = Tender(
            tenant_id=self._tenant_id,
            created_by=created_by,
            tender_type=tender_type,
            issuing_agency=issuing_agency.strip(),
            external_ref=external_ref.strip() if external_ref and external_ref.strip() else None,
            title=title.strip(),
            slug=slug,
            status="ingested",
        )
        session.add(tender)
        session.commit()
        return tender

    def get(self, session: Session, tender_id: str) -> Tender:
        tender = session.scalar(
            select(Tender).where(Tender.id == tender_id, Tender.tenant_id == self._tenant_id)
        )
        if tender is None:
            raise LookupError(f"tender {tender_id} not found")
        return tender

    def by_slug(self, session: Session, slug: str) -> Tender | None:
        return session.scalar(
            select(Tender).where(Tender.slug == slug, Tender.tenant_id == self._tenant_id)
        )

    def all(self, session: Session) -> list[Tender]:
        return list(
            session.scalars(
                select(Tender)
                .where(Tender.tenant_id == self._tenant_id)
                .order_by(Tender.tender_type, Tender.created_at, Tender.id)
            )
        )

    def versions(self, session: Session, tender: Tender) -> list[VersionDocuments]:
        versions = list(
            session.scalars(
                select(TenderVersion)
                .where(
                    TenderVersion.tender_id == tender.id,
                    TenderVersion.tenant_id == self._tenant_id,
                )
                .order_by(TenderVersion.version_no)
            )
        )
        links: dict[str, list[tuple[TenderVersionDocument, Document]]] = {
            version.id: [] for version in versions
        }
        for link, document in session.execute(
            select(TenderVersionDocument, Document)
            .join(Document, TenderVersionDocument.document_id == Document.id)
            .where(
                TenderVersionDocument.tender_version_id.in_(list(links)),
                TenderVersionDocument.tenant_id == self._tenant_id,
                Document.tenant_id == self._tenant_id,
            )
            .order_by(TenderVersionDocument.created_at, TenderVersionDocument.id)
        ):
            links[link.tender_version_id].append((link, document))
        return [VersionDocuments(version, links[version.id]) for version in versions]

    def add_version(
        self,
        session: Session,
        tender: Tender,
        document: Document,
        kind: str,
        issued_on: date | None,
        *,
        created_by: str,
        role: str | None = None,
        summary_of_change: str | None = None,
    ) -> TenderVersion:
        """Create the next version of the tender with its first document. The first version
        is the original; every later one is a corrigendum, amendment or clarification.
        Extraction of the version is started separately, once its documents are parsed."""
        if kind not in VERSION_KINDS:
            raise TenderError(f"unknown version kind {kind!r}; one of {list(VERSION_KINDS)}")
        role = role or DEFAULT_ROLE[kind]
        self._check_document(document, role)
        latest = session.scalar(
            select(TenderVersion)
            .where(
                TenderVersion.tender_id == tender.id,
                TenderVersion.tenant_id == self._tenant_id,
            )
            .order_by(TenderVersion.version_no.desc())
            .limit(1)
            .with_for_update()
        )
        if latest is None and kind != "original":
            raise TenderError("the first version of a tender is the original")
        if latest is not None and kind == "original":
            raise TenderError(
                "the tender already has its original version; a change is a corrigendum, "
                "amendment or clarification"
            )
        version = TenderVersion(
            tenant_id=self._tenant_id,
            created_by=created_by,
            tender_id=tender.id,
            version_no=(latest.version_no + 1) if latest else 1,
            kind=kind,
            issued_on=issued_on,
            summary_of_change=summary_of_change.strip() if summary_of_change else None,
            supersedes_version_id=latest.id if latest else None,
        )
        session.add(version)
        session.flush()
        audit.record(
            session,
            tenant_id=self._tenant_id,
            actor=created_by,
            action="insert",
            table_name="tender_version",
            row_id=version.id,
            after={
                "tender_id": tender.id,
                "version_no": version.version_no,
                "kind": kind,
                "issued_on": issued_on.isoformat() if issued_on else None,
                "supersedes_version_id": version.supersedes_version_id,
            },
        )
        self._link(session, version, document, role, created_by)
        tender.current_version_id = version.id
        session.commit()
        return version

    def attach_document(
        self,
        session: Session,
        tender: Tender,
        version_no: int,
        document: Document,
        role: str,
        *,
        created_by: str,
    ) -> TenderVersion:
        """Add a further document (a PPA, a technical volume) to an existing version. An
        amendment or clarification is never added to a version: it is a version."""
        self._check_document(document, role)
        if role in CHANGE_ROLES:
            raise TenderError(
                f"a document of role {role!r} changes the tender: add it as a new version"
            )
        version = self._version(session, tender, version_no)
        already = session.scalar(
            select(TenderVersionDocument.id).where(
                TenderVersionDocument.tender_version_id == version.id,
                TenderVersionDocument.document_id == document.id,
                TenderVersionDocument.tenant_id == self._tenant_id,
            )
        )
        if already is None:
            self._link(session, version, document, role, created_by)
        session.commit()
        return version

    def start_extraction(
        self,
        session: Session,
        tender: Tender,
        *,
        version_no: int | None = None,
        prompt_version: str = "v1",
        created_by: str,
        is_fixture: bool = False,
    ) -> list[ExtractionRun]:
        """Queue the extraction of one version (the latest by default): one run per document
        that has groups to read. A later version is read only where it touches the tender."""
        compiled = self._catalog.get(tender.tender_type)
        entries = self.versions(session, tender)
        if not entries:
            raise TenderError("the tender has no version yet")
        entry = (
            entries[-1]
            if version_no is None
            else next((e for e in entries if e.version.version_no == version_no), None)
        )
        if entry is None:
            raise LookupError(f"tender {tender.id} has no version {version_no}")
        plan: list[tuple[Document, list[str]]] = []
        for link, document in entry.documents:
            if document.status != "parsed":
                raise TenderError(
                    f"document {document.filename!r} is {document.status}, not parsed yet"
                )
            page_texts = list(
                session.scalars(
                    select(Page.text)
                    .where(Page.document_id == document.id, Page.tenant_id == self._tenant_id)
                    .order_by(Page.page_no)
                )
            )
            groups = plan_groups(
                compiled,
                version_no=entry.version.version_no,
                role=link.role,
                page_texts=page_texts,
            )
            if groups:
                plan.append((document, groups))
        return [
            self._extract.start_run(
                session,
                document_id=document.id,
                schema_name=compiled.schema.name,
                schema_version=compiled.schema.version,
                prompt_version=prompt_version,
                created_by=created_by,
                object_type=OBJECT_TYPE,
                object_id=tender.id,
                object_version=entry.version.version_no,
                groups=groups,
                is_fixture=is_fixture,
            )
            for document, groups in plan
        ]

    def refresh_status(self, session: Session, tender: Tender) -> str:
        """ingested until every run of the tender is validated, then extracted; in_review
        once a reviewer has decided a field. reviewed and published are set in Stage 3."""
        if tender.status in ("reviewed", "published"):
            return tender.status
        decided = session.scalar(
            select(func.count())
            .select_from(Approval)
            .where(
                Approval.tenant_id == self._tenant_id,
                Approval.object_type == OBJECT_TYPE,
                Approval.object_id == tender.id,
                Approval.status == "active",
            )
        )
        statuses = set(
            session.scalars(
                select(ExtractionRun.status).where(
                    ExtractionRun.tenant_id == self._tenant_id,
                    ExtractionRun.object_type == OBJECT_TYPE,
                    ExtractionRun.object_id == tender.id,
                )
            )
        )
        if decided:
            status = "in_review"
        elif statuses and statuses <= {"validated"}:
            status = "extracted"
        else:
            status = "ingested"
        if tender.status != status:
            tender.status = status
            session.commit()
        return status

    def _version(self, session: Session, tender: Tender, version_no: int) -> TenderVersion:
        version = session.scalar(
            select(TenderVersion).where(
                TenderVersion.tender_id == tender.id,
                TenderVersion.version_no == version_no,
                TenderVersion.tenant_id == self._tenant_id,
            )
        )
        if version is None:
            raise LookupError(f"tender {tender.id} has no version {version_no}")
        return version

    def _check_document(self, document: Document, role: str) -> None:
        if role not in DOCUMENT_ROLES:
            raise TenderError(f"unknown document role {role!r}; one of {list(DOCUMENT_ROLES)}")
        if document.tenant_id != self._tenant_id:
            raise LookupError(f"document {document.id} not found")

    def _link(
        self,
        session: Session,
        version: TenderVersion,
        document: Document,
        role: str,
        created_by: str,
    ) -> None:
        link = TenderVersionDocument(
            tenant_id=self._tenant_id,
            created_by=created_by,
            tender_version_id=version.id,
            document_id=document.id,
            role=role,
        )
        session.add(link)
        session.flush()
        audit.record(
            session,
            tenant_id=self._tenant_id,
            actor=created_by,
            action="add_document",
            table_name="tender_version",
            row_id=version.id,
            after={"document_id": document.id, "role": role},
        )
