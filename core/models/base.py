"""Declarative base and the tenant/audit mixin every table uses."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


class AuditMixin:
    """created_at and created_by; on every table."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)


class TenantAuditMixin(AuditMixin):
    """tenant_id plus the audit columns; on every table except tenant itself."""

    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenant.tenant_id"), nullable=False, index=True
    )
