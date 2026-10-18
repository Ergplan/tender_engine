"""I/O models of the independent agent pass (Stage 5A)."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentPassRequest(BaseModel):
    # The version the agent reads the tender at; the current one when omitted.
    version_no: int | None = None


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    object_id: str
    object_version: int
    schema_name: str
    schema_version: str
    prompt_name: str
    prompt_version: str
    model: str
    # queued, running, done, stopped (the turn limit or a model error; the findings made
    # so far stand) or failed.
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    turns: int
    tokens_in: int
    tokens_cached: int
    tokens_out: int
    cost_usd: Decimal
    error: str | None
    # Per document number: the pages the section map named, and the pages the agent read.
    pages_offered: dict[str, Any]
    pages_read: dict[str, Any]
    documents: list[Any]
    created_at: datetime
    created_by: str


class AgentFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ordinal: int
    field_path: str
    value: Any | None
    value_type: str
    confidence: float
    rationale: str
    # accepted, not_found, withdrawn, rejected (with its reason) or superseded.
    status: str
    reason: str | None
    # The quotes as cited and as located on the cited page.
    evidence: list[Any]
    created_at: datetime


class AgentPassOut(BaseModel):
    run: AgentRunOut
    findings: list[AgentFindingOut]
    # Fields of the pass's schema for which no finding stands.
    unsubmitted: list[str]
