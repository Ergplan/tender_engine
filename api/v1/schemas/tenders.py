"""Pydantic I/O models for the tender routers."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from core.services.review_state import ReviewState
from tender.services.packs import CompiledSection, TenderField


class TenderCreate(BaseModel):
    type: str
    agency: str
    external_ref: str | None = None
    title: str


class TenderOut(BaseModel):
    id: str
    tender_type: str
    issuing_agency: str
    external_ref: str | None
    title: str
    slug: str | None
    status: str
    current_version_no: int | None
    created_at: datetime
    created_by: str


class VersionDocumentOut(BaseModel):
    document_id: str
    role: str
    filename: str
    page_count: int | None
    status: str


class VersionOut(BaseModel):
    id: str
    tender_id: str
    version_no: int
    kind: str
    issued_on: date | None
    summary_of_change: str | None
    supersedes_version_id: str | None
    documents: list[VersionDocumentOut]


class TenderExtractRequest(BaseModel):
    version_no: int | None = None
    prompt_version: str = "v1"


class TenderReviewState(BaseModel):
    """Core's review state for one version of a tender. For a version after the original,
    changed_fields lists the fields that version gives a value for; every other field
    keeps what the earlier versions say."""

    tender_id: str
    version_no: int | None
    version_kind: str | None
    changed_fields: list[str] = Field(default_factory=list)
    state: ReviewState


class TenderSchemaOut(BaseModel):
    tender_type: str
    pack: str
    schema_name: str
    schema_version: str
    sections: list[CompiledSection]
    fields: list[TenderField]
