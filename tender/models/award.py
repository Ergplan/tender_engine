from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin

AWARD_STATUSES = ("imported", "reviewed")
# How an award was linked to a tender: the dataset's RfS number equals the tender's
# external reference, or the tender number was found in the order's own page text.
LINK_BASES = ("rfs_number", "page_text")


class Award(IdMixin, TenantAuditMixin, Base):
    """One result publication (a result sheet, a CERC adoption order, an allocation list),
    imported from the RE-tender-results dataset (Stage 6). The row is the object's
    identity and provenance; what the publication says is in its candidates and, once a
    reviewer approves them, in canonical_fact. Nothing here is truth."""

    __tablename__ = "award"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_sha256", name="uq_award_tenant_source"),
    )

    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False, index=True)
    # The dataset's own id of the source, its archived file's sha256 (equal to the
    # document's), the URL it was fetched from and the dataset commit it came from.
    source_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_name: Mapped[str] = mapped_column(String(300), nullable=False)
    dataset: Mapped[str] = mapped_column(String(100), nullable=False)
    # For listing and matching, as the dataset gives them; the reviewed values are facts.
    procurer: Mapped[str] = mapped_column(String(100), nullable=False)
    reference: Mapped[str] = mapped_column(String(200), nullable=False)
    result_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # The dataset's verification tier and the number of rows it holds for the source.
    verification: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Set only on an exact match of the RfS number against tender.external_ref, or when
    # the tender number was found in the order's page text (then with the page).
    tender_id: Mapped[str | None] = mapped_column(
        ForeignKey("tender.id"), nullable=True, index=True
    )
    tender_link_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tender_link_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="imported")
