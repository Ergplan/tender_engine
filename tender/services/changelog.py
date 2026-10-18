"""The changelog of a tender across its versions (Stage 5C): per version, the canonical
facts it changed against what stood before, each with its evidence, the decision's date
and the reviewer's role. An unreviewed version lists the fields it may touch as pending,
by path only: no reading is shown as a fact before a reviewer decides it.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Approval, CanonicalFact, Document
from tender.models import Tender, TenderVersion, TenderVersionDocument
from tender.services.packs import Catalog
from tender.services.publication import fields_touched, reviewed_version_of
from tender.services.published import DEFAULT_ROLE, Evidence, reviewer_roles
from tender.services.summary import SUMMARY_FIELD
from tender.services.tenders import OBJECT_TYPE


class Change(BaseModel):
    field_path: str
    label: str
    section: str
    value_type: str
    unit: str | None
    before: Any = None
    after: Any = None
    # The version removed the provision: `after` is null and the removing words are the
    # evidence.
    withdrawn: bool = False
    evidence: list[Evidence] = []
    decided_at: datetime | None = None
    reviewer_role: str | None = None


class ChangelogVersion(BaseModel):
    version_no: int
    kind: str
    issued_on: date | None
    summary_of_change: str | None
    documents: list[str]
    reviewed: bool
    changes: list[Change] = []
    # For an unreviewed version: the fields its readings may touch, by path.
    pending: list[str] = []


class Changelog(BaseModel):
    tender_id: str
    title: str
    reviewed_version: int | None
    versions: list[ChangelogVersion]


def changelog(session: Session, catalog: Catalog, tender: Tender) -> Changelog:
    compiled = catalog.get(tender.tender_type)
    defs = {field.path: field for field in compiled.fields}
    derived = {section.name for section in compiled.sections if section.derived}
    reviewed = reviewed_version_of(session, tender)
    versions = list(
        session.scalars(
            select(TenderVersion)
            .where(
                TenderVersion.tender_id == tender.id, TenderVersion.tenant_id == tender.tenant_id
            )
            .order_by(TenderVersion.version_no)
        )
    )
    documents: dict[str, list[str]] = {v.id: [] for v in versions}
    for version_id, filename in session.execute(
        select(TenderVersionDocument.tender_version_id, Document.filename)
        .join(Document, Document.id == TenderVersionDocument.document_id)
        .where(
            TenderVersionDocument.tenant_id == tender.tenant_id,
            TenderVersionDocument.tender_version_id.in_(list(documents)),
        )
        .order_by(TenderVersionDocument.created_at)
    ):
        documents[version_id].append(filename)
    filenames = {
        document_id: filename
        for document_id, filename in session.execute(
            select(Document.id, Document.filename).where(Document.tenant_id == tender.tenant_id)
        )
    }
    facts = list(
        session.scalars(
            select(CanonicalFact)
            .where(
                CanonicalFact.tenant_id == tender.tenant_id,
                CanonicalFact.object_type == OBJECT_TYPE,
                CanonicalFact.object_id == tender.id,
                CanonicalFact.is_current.is_(True),
            )
            .order_by(CanonicalFact.object_version, CanonicalFact.field_path)
        )
    )
    approvals = {
        row.id: row
        for row in session.scalars(
            select(Approval).where(
                Approval.tenant_id == tender.tenant_id,
                Approval.id.in_([f.approval_id for f in facts]),
            )
        )
    }
    roles = reviewer_roles(session, tender.tenant_id, {a.reviewer for a in approvals.values()})
    standing: dict[str, CanonicalFact] = {}
    by_version: dict[int, list[Change]] = {v.version_no: [] for v in versions}
    for fact in facts:
        path = fact.field_path
        definition = defs.get(path)
        if definition is None or path == SUMMARY_FIELD or definition.section in derived:
            continue
        before = standing.get(path)
        states = fact.value is not None or fact.withdrawn
        if before is not None and not states:
            # A later version silent on the field leaves the earlier fact standing.
            continue
        if before is not None and before.value == fact.value and not fact.withdrawn:
            standing[path] = fact
            continue
        if before is None and fact.value is None and not fact.withdrawn:
            standing[path] = fact
            continue
        approval = approvals.get(fact.approval_id)
        by_version.setdefault(fact.object_version, []).append(
            Change(
                field_path=path,
                label=definition.label,
                section=definition.section,
                value_type=definition.value_type,
                unit=definition.unit,
                before=before.value if before else None,
                after=fact.value,
                withdrawn=fact.withdrawn,
                evidence=[
                    Evidence(
                        document_id=str(item.get("document_id")),
                        filename=filenames.get(str(item.get("document_id"))),
                        page_no=int(item.get("page_no") or 0),
                        quote=str(item.get("quote") or ""),
                    )
                    for item in fact.evidence
                    if item.get("document_id") and item.get("page_no")
                ],
                decided_at=approval.decided_at if approval else fact.effective_at,
                reviewer_role=roles.get(approval.reviewer, DEFAULT_ROLE) if approval else None,
            )
        )
        standing[path] = fact
    out = []
    for version in versions:
        is_reviewed = reviewed is not None and version.version_no <= reviewed
        pending = (
            sorted(
                p
                for p in fields_touched(session, tender, version.version_no)
                if p in defs and p != SUMMARY_FIELD and defs[p].section not in derived
            )
            if not is_reviewed
            else []
        )
        out.append(
            ChangelogVersion(
                version_no=version.version_no,
                kind=version.kind,
                issued_on=version.issued_on,
                summary_of_change=version.summary_of_change,
                documents=documents[version.id],
                reviewed=is_reviewed,
                changes=by_version.get(version.version_no, []) if is_reviewed else [],
                pending=pending,
            )
        )
    return Changelog(
        tender_id=tender.id, title=tender.title, reviewed_version=reviewed, versions=out
    )
