from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin

# flagged: "unsure, come back". It records the reviewer's note, withdraws an earlier
# decision on the field and decides nothing.
DECISIONS = ("approved", "edited", "not_in_document", "rejected", "flagged")
DELTA_KINDS = ("exact", "format", "wrong_value", "missing", "extra")


class Approval(IdMixin, TenantAuditMixin, Base):
    """A reviewer's decision on a candidate. A later decision supersedes the earlier one."""

    __tablename__ = "approval"
    # The database refuses a second active decision for one field of one object version.
    __table_args__ = (
        Index(
            "uq_approval_one_active_per_field",
            "tenant_id",
            "object_type",
            "object_id",
            "object_version",
            "field_path",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate.id"), nullable=False, index=True
    )
    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    object_version: Mapped[int] = mapped_column(Integer, nullable=False)
    field_path: Mapped[str] = mapped_column(String(200), nullable=False)
    final_value: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    supersedes_approval_id: Mapped[str | None] = mapped_column(
        ForeignKey("approval.id"), nullable=True
    )


class CanonicalFact(IdMixin, TenantAuditMixin, Base):
    """Truth. Written only by core.services.approve.ApprovalService.approve().

    A database trigger accepts a row only under a live approval of the same field, and
    afterwards lets it be retired (is_current, superseded_at) but never changed or deleted."""

    __tablename__ = "canonical_fact"
    __table_args__ = (
        Index(
            "uq_canonical_fact_one_current_per_field",
            "tenant_id",
            "object_type",
            "object_id",
            "object_version",
            "field_path",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    object_version: Mapped[int] = mapped_column(Integer, nullable=False)
    field_path: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    value_type: Mapped[str] = mapped_column(String(50), nullable=False)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approval.id"), nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Feedback(IdMixin, TenantAuditMixin, Base):
    """The difference between a candidate and the reviewer's final value. Never auto-applied."""

    __tablename__ = "feedback"

    approval_id: Mapped[str] = mapped_column(ForeignKey("approval.id"), nullable=False, index=True)
    field_path: Mapped[str] = mapped_column(String(200), nullable=False)
    candidate_value: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    final_value: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    delta_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)


class AuditLog(IdMixin, TenantAuditMixin, Base):
    """Append-only (DB trigger). One row per write to a truth table."""

    __tablename__ = "audit_log"

    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    table_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    row_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
