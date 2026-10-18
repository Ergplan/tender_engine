from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import AuditMixin, Base


class Tenant(AuditMixin, Base):
    """One row per tenant. Phase 1 has a single row, 'ergplan', seeded by migration 0001."""

    __tablename__ = "tenant"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # enterprise: a customer with its own tenders. free: reads the public library only.
    # public: the reserved library tenant (Stage 5D), written only by reviewer and
    # ingestion service accounts.
    plan: Mapped[str] = mapped_column(
        String(20), nullable=False, default="enterprise", server_default="enterprise"
    )
