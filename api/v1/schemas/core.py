"""Pydantic I/O models for the core routers."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sha256: str
    filename: str
    mime: str
    page_count: int | None
    status: str
    error: str | None
    created_at: datetime
    created_by: str


class SectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    start_page: int
    end_page: int
    heading: str
    kind: str
    confidence: float


class ExtractRequest(BaseModel):
    schema_name: str
    schema_version: str
    prompt_version: str


class ExtractionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    object_type: str
    object_id: str
    object_version: int
    schema_name: str
    schema_version: str
    prompt_version: str
    model: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    mode: str
    token_in: int
    token_cached: int
    token_out: int
    cost_usd: Decimal
    error: str | None


class ReviewerEvidence(BaseModel):
    """Evidence the reviewer gives for an edited value: the page and the text on it."""

    page_no: int
    quote: str


class ApprovalRequest(BaseModel):
    candidate_id: str
    decision: Literal["approved", "edited", "not_in_document", "rejected"]
    final_value: Any = None
    note: str | None = None
    evidence: list[ReviewerEvidence] | None = None


class ApprovalOut(BaseModel):
    id: str
    candidate_id: str
    field_path: str
    decision: str
    final_value: Any
    reviewer: str
    note: str | None
    decided_at: datetime
    status: str
    canonical_fact_id: str | None
    feedback_delta_kind: str | None
    created: bool
