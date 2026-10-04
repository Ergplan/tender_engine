from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin

TENDER_TYPES = (
    "fdre",
    "solar",
    "wind",
    "hybrid",
    "bess",
    "transmission",
    "generation",
    "epc",
    "ipp",
)
TENDER_STATUSES = ("ingested", "extracted", "in_review", "reviewed", "published")
VERSION_KINDS = ("original", "corrigendum", "amendment", "clarification")
DOCUMENT_ROLES = (
    "rfs",
    "amendment",
    "clarification",
    "ppa",
    "psa",
    "cfda",
    "technical",
    "contractual",
    "nit",
)


class Tender(IdMixin, TenantAuditMixin, Base):
    """A tender. Its content lives in its versions; canonical facts are attached to
    object_type='tender', object_id=tender.id, object_version=tender_version.version_no."""

    __tablename__ = "tender"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_tender_tenant_slug"),)

    tender_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    issuing_agency: Mapped[str] = mapped_column(String(200), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # Folder name under /work/tenders/<type>/ for tenders ingested by the management
    # command; makes the command safe to repeat. Null for tenders created through the API.
    slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ingested")
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("tender_version.id", use_alter=True, name="fk_tender_current_version"),
        nullable=True,
    )


class TenderVersion(IdMixin, TenantAuditMixin, Base):
    """The original tender or one corrigendum, amendment or clarification. Never edited in
    place: a change to the tender is a new version."""

    __tablename__ = "tender_version"
    __table_args__ = (
        UniqueConstraint("tender_id", "version_no", name="uq_tender_version_tender_no"),
    )

    tender_id: Mapped[str] = mapped_column(ForeignKey("tender.id"), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    issued_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary_of_change: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("tender_version.id"), nullable=True
    )


class TenderVersionDocument(IdMixin, TenantAuditMixin, Base):
    """A document of a tender version, with its role (rfs, ppa, amendment, ...)."""

    __tablename__ = "tender_version_document"
    __table_args__ = (
        UniqueConstraint(
            "tender_version_id", "document_id", name="uq_tender_version_document_once"
        ),
    )

    tender_version_id: Mapped[str] = mapped_column(
        ForeignKey("tender_version.id"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)


class TenderFieldDef(IdMixin, TenantAuditMixin, Base):
    """The compiled schemas, one row per tender type and field, for introspection.
    Generated from the domain-pack YAML at start-up; never hand-edited."""

    __tablename__ = "tender_field_def"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "tender_type", "field_path", name="uq_tender_field_def_type_path"
        ),
    )

    tender_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    field_path: Mapped[str] = mapped_column(String(200), nullable=False)
    namespace: Mapped[str] = mapped_column(String(20), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subdomain: Mapped[str | None] = mapped_column(String(50), nullable=True)
    section: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    value_type: Mapped[str] = mapped_column(String(50), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    help_text: Mapped[str] = mapped_column(Text, nullable=False)
    review_order: Mapped[int] = mapped_column(Integer, nullable=False)
