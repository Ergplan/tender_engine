from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin


class LLMCallLog(IdMixin, TenantAuditMixin, Base):
    """One row per LLM call, written by core.llm.client.LLMClient.call for every outcome.

    Shape adapted from tariff-oder services/api/src/tariff_api/models.py:658-685
    (extraction_runs): prompt version, input hash, tokens, status, fixture flag.
    """

    __tablename__ = "llm_call_log"

    extraction_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_run.id"), nullable=True, index=True
    )
    prompt_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    output_schema: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_fixture: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
