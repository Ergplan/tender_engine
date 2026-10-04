from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import AuditMixin, Base


class Tenant(AuditMixin, Base):
    """One row per tenant. Phase 1 has a single row, 'ergplan', seeded by migration 0001."""

    __tablename__ = "tenant"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
