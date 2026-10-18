"""The agent pass tables: one row per run, one per finding (or attempt at one).

`agent_finding` is a table of its own by design (master prompt, Stage 5A): the agent's
reading is compared with the engine's and the reviewer's, never merged into them."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin

# queued: waiting for the agent container. running: the agent is reading. done: the agent
# ended its pass. stopped: the pass ended at the turn limit or on a model error, with the
# findings made so far. failed: nothing could be run (inputs, provider).
AGENT_RUN_STATUSES = ("queued", "running", "done", "stopped", "failed")
# accepted: a value with evidence located on a page the agent had read. not_found: the
# agent said the documents do not state the field. withdrawn: null with the removing words
# located as evidence. rejected: an attempt the harness refused, kept with its reason.
# superseded: a later finding for the same field stands instead.
FINDING_STATUSES = ("accepted", "not_found", "withdrawn", "rejected", "superseded")


class AgentRun(IdMixin, TenantAuditMixin, Base):
    """One pass of the agent over one object version with one schema and prompt version."""

    __tablename__ = "agent_run"

    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    object_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_name: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Model calls made (one per turn of the agent loop).
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_cached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal(0))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per document (by its number in the pass, from 1): the pages the section map named
    # for the schema's groups, and the pages the agent read.
    pages_offered: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    pages_read: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # The documents of the pass by number: id, filename, version.
    documents: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    is_fixture: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AgentFinding(IdMixin, TenantAuditMixin, Base):
    """What the agent submitted for one field, as the harness judged it. Never updated
    except for status (accepted -> superseded)."""

    __tablename__ = "agent_finding"

    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_run.id"), nullable=False, index=True
    )
    # The attempt's place in the run, from 1: rejected attempts count too.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    field_path: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    value: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    value_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # For a rejected attempt: why the harness refused it.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Each quote as the agent cited it and as the resolver located it on the cited page:
    # document_id, document_no, page_no, quote, char_start, char_end, bbox, match_score,
    # match_method. An attempt rejected for an unlocated quote keeps the quote with nulls.
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
