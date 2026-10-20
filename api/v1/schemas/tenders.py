"""Pydantic I/O models for the tender routers."""

from datetime import date, datetime
from typing import Any, Literal

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
    prompt_version: str = "v2"
    # batch: through the batch API, at half the price, when nobody waits for the result.
    mode: Literal["sync", "batch"] = "sync"


class TenderReviewState(BaseModel):
    """Core's review state for one version of a tender. For a version after the original,
    changed_fields lists the fields that version gives a value for; every other field
    keeps what the earlier versions say. A required field is required of the tender, not
    of each version: missing_required lists those no version up to this one states."""

    tender_id: str
    version_no: int | None
    version_kind: str | None
    changed_fields: list[str] = Field(default_factory=list)
    # Required fields the tender as a whole lacks up to this version.
    missing_required: list[str] = Field(default_factory=list)
    state: ReviewState


class SummaryQueued(BaseModel):
    tender_id: str
    # False when an extraction of the tender is still under way (the summary is queued
    # by the worker when it ends) or the summary is queued already.
    queued: bool


class ReviewTokenCreate(BaseModel):
    """A link for one object: a tender (`tender_id`) or, since Stage 6, an award
    (`award_id`); exactly one of the two."""

    tender_id: str | None = None
    award_id: str | None = None
    reviewer_name: str


class ReviewTokenOut(BaseModel):
    url: str
    token: str
    object_type: str = "tender"
    object_id: str
    tender_id: str | None
    reviewer_name: str
    expires_at: datetime


class ReviewSessionOut(BaseModel):
    # The object the link opens: a tender (tender_id set) or an award (Stage 6).
    object_type: str = "tender"
    object_id: str
    tender_id: str | None
    reviewer_name: str
    expires_at: datetime
    # Set once the review is completed: it can then be read and no longer changed.
    completed_at: datetime | None
    # The review round the link opens: 1 over the whole tender; a later round is opened by
    # a version (from_version) and asks only about the fields it touched.
    round_no: int = 1
    from_version: int | None = None


class SnapshotOut(BaseModel):
    id: str
    tender_id: str
    reviewer: str
    created_at: datetime
    snapshot: dict[str, Any]


class TenderSchemaOut(BaseModel):
    tender_type: str
    pack: str
    schema_name: str
    schema_version: str
    sections: list[CompiledSection]
    fields: list[TenderField]
