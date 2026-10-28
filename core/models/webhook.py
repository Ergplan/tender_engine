"""Webhook endpoints and deliveries (Stage 7, Block 6 b; migration 0025). An endpoint is a
caller's URL with the events it wants and the secret the engine signs with; a delivery is
one event sent to one endpoint, with its attempts and outcome. Tenant-scoped and audited
like every table; the secret is shown to nobody after creation."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin


class WebhookEndpoint(IdMixin, TenantAuditMixin, Base):
    __tablename__ = "webhook_endpoint"

    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    events: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    secret: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WebhookDelivery(IdMixin, TenantAuditMixin, Base):
    __tablename__ = "webhook_delivery"

    endpoint_id: Mapped[str] = mapped_column(
        ForeignKey("webhook_endpoint.id"), nullable=False, index=True
    )
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # pending, delivered, failed, cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
