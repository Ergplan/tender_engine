from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin


class ReviewToken(IdMixin, TenantAuditMixin, Base):
    """The link a reviewer opens: an unguessable token for one tender, mapped to the
    reviewer's name. One live token per tender; creating another revokes it. The only
    identity mechanism of phase 1."""

    __tablename__ = "review_token"

    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tender.id"), nullable=False, index=True)
    reviewer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A review round: the first link of a tender is round 1 over the whole tender; a round
    # opened by a later version (from_version) asks only about the fields that version and
    # the ones after it touched, the earlier decisions carrying forward.
    round_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    from_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TenderReviewSnapshot(IdMixin, TenantAuditMixin, Base):
    """The current view of a tender at the moment its review was completed: the final
    value of every field with its version and evidence. The gold set is made from these."""

    __tablename__ = "tender_review_snapshot"

    tender_id: Mapped[str] = mapped_column(ForeignKey("tender.id"), nullable=False, index=True)
    review_token_id: Mapped[str] = mapped_column(ForeignKey("review_token.id"), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
