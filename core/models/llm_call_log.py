from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
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
    # tokens_in is the input billed at the full price: what was neither written to the prompt
    # cache nor read from it. The whole input is tokens_in + cache_write_tokens +
    # cache_read_tokens.
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # sync: a caller waited for the answer. batch: sent through the batch API.
    mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="sync", server_default="sync"
    )
    batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # At the configured prices, with the cache and batch factors applied.
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0), server_default="0"
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_fixture: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


BATCH_STATUSES = ("submitted", "collected")


class LLMBatch(IdMixin, TenantAuditMixin, Base):
    """A batch of calls handed to the provider's batch API, written by
    core.llm.client.LLMClient.submit_batch. Each of its calls gets its llm_call_log row
    when the batch is collected. `requests` maps the custom id of each call to its input
    hash and prompt."""

    __tablename__ = "llm_batch"

    extraction_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_run.id"), nullable=True, index=True
    )
    provider_batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # 1: the calls that write a shared page window to the cache (and those that share
    # nothing). 2: the calls that read a window the first wave wrote.
    wave: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    requests: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
