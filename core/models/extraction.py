from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin

RUN_STATUSES = ("queued", "running", "extracted", "validated", "failed")
RUN_MODES = ("sync", "batch")
# A run that read no page: its candidates were written from the object's other candidates
# (the record), and their evidence is inherited from those. Not a mode a caller can ask
# ExtractService.start_run for.
RECORD_MODE = "record"
# A run that read no page and made no model call: its candidates were derived by
# deterministic code from the object's decided fields, with their evidence inherited.
DERIVED_MODE = "derived"
# The modes whose candidates are written from the record rather than read from pages.
RECORD_MODES = (RECORD_MODE, DERIVED_MODE)
# raw: inserted, not yet validated. validated: every rule passed. needs_review: a rule failed.
# superseded: a later run produced a candidate for the same field.
# not_found: the model returned no value. rejected: a value came without evidence.
CANDIDATE_STATUSES = ("raw", "validated", "needs_review", "superseded", "not_found", "rejected")
REVIEWABLE_STATUSES = ("validated", "needs_review")


class ExtractionRun(IdMixin, TenantAuditMixin, Base):
    """One extraction of one document with one schema and prompt version, for one object.

    groups limits the run to the named field groups of the schema; null means all of them.
    An object version may be extracted by several runs, one per document it holds."""

    __tablename__ = "extraction_run"

    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_id: Mapped[str] = mapped_column(String(32), nullable=False)
    object_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_name: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    groups: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    # Per group, a prompt version to use instead of the section's pinned one (evaluation
    # of a prompt change before it becomes the default).
    prompt_overrides: Mapped[dict[str, str] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # sync: the worker makes each call and waits. batch: the calls go through the batch
    # API, for runs no human waits for.
    mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="sync", server_default="sync"
    )
    # token_in is the whole input of the run's calls, cached or not; token_cached is the
    # part of it read from the prompt cache.
    token_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_cached: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    token_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal(0))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_fixture: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Candidate(IdMixin, TenantAuditMixin, Base):
    """Model output for one field. Immutable after insert except for status (DB trigger)."""

    __tablename__ = "candidate"

    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_run.id"), nullable=False, index=True
    )
    field_path: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    value: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    value_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="raw")
    prompt_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    llm_call_log_id: Mapped[str | None] = mapped_column(
        ForeignKey("llm_call_log.id"), nullable=True
    )
    window_pages: Mapped[list[int]] = mapped_column(JSONB, nullable=False)


class EvidenceSpan(IdMixin, TenantAuditMixin, Base):
    """Where a candidate's value is written in the document. Immutable (DB trigger).

    resolution says how the quote was located: stated_page, adjacent_page, window_page,
    or unresolved (char range and bbox are then null and the stated page is kept).
    """

    __tablename__ = "evidence_span"

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate.id"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    stated_page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[list[float] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str] = mapped_column(String(20), nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # How the resolver found the quote: exact, fuzzy, reordered, interleaved, page_boundary.
    match_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The quote's place in the model's evidence list, from 1. A text that marks its
    # sentences [1], [2] refers to these. Null on spans stored before migration 0010.
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # For evidence inherited from the record: what it was inherited from (the label of the
    # field, or of several fields that share the passage). Null for evidence read from a page.
    source: Mapped[str | None] = mapped_column(String(300), nullable=True)


class ValidationResult(IdMixin, TenantAuditMixin, Base):
    __tablename__ = "validation_result"

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidate.id"), nullable=False, index=True
    )
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # error: a failure sends the candidate to needs_review. warning: it is only shown.
    severity: Mapped[str] = mapped_column(
        String(10), nullable=False, default="error", server_default="error"
    )
