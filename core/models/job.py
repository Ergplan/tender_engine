from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin

JOB_STATUSES = ("queued", "running", "done", "failed")


class Job(IdMixin, TenantAuditMixin, Base):
    """A unit of background work. The worker polls this table; there is no other queue."""

    __tablename__ = "job"

    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The first attempt plus three retries.
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
