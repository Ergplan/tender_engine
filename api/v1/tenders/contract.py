"""REST v1 for any caller (Stage 7, Block 6 a), behind API keys: submit a tender (a file or
an official URL) and an amendment, the extraction status, the snapshot (contract v1,
`GET /tenders/{id}/fields`), a review link for a named reviewer, and the webhook
registry (Block 6 b). The published, changes and ask routes stand where they were. Routes
only; the services do the work. Nothing here writes a fact."""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from api.deps import (
    ActorDep,
    CatalogDep,
    ReviewStateDep,
    SessionDep,
    SettingsDep,
    SubmitDep,
    TenantDep,
    TendersDep,
    TokensDep,
)
from api.middleware.errors import AppError
from api.v1.tenders.review import review_url
from api.v1.tenders.tenders import _tender
from core.services import webhooks
from tender.services.snapshot import TenderSnapshot, tender_snapshot
from tender.services.status import TenderStatus, tender_status
from tender.services.submit import Submission, SubmitError

router = APIRouter(tags=["contract v1"])


class SubmitOut(BaseModel):
    tender_id: str
    slug: str | None
    version_no: int
    document_id: str
    created: bool
    status_path: str


class ReviewLinkRequest(BaseModel):
    reviewer_name: str = Field(min_length=1, max_length=200)


class ReviewLinkOut(BaseModel):
    url: str
    tender_id: str
    reviewer_name: str
    expires_at: datetime | None


class WebhookCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    events: list[str] = Field(min_length=1)
    secret: str = Field(min_length=webhooks.MIN_SECRET, max_length=200)
    description: str | None = Field(default=None, max_length=200)


class WebhookOut(BaseModel):
    id: str
    url: str
    events: list[Any]
    description: str | None
    active: bool
    created_at: datetime


class DeliveryOut(BaseModel):
    id: str
    endpoint_id: str
    event: str
    status: str
    attempts: int
    last_status: int | None
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None


def _submission(submission: Submission) -> SubmitOut:
    return SubmitOut(
        tender_id=submission.tender.id,
        slug=submission.tender.slug,
        version_no=submission.version.version_no,
        document_id=submission.document.id,
        created=submission.created,
        status_path=f"/api/v1/tenders/{submission.tender.id}/status",
    )


@router.post("/tenders/submit", response_model=SubmitOut, status_code=202)
async def submit_tender(
    session: SessionDep,
    submit: SubmitDep,
    actor: ActorDep,
    file: Annotated[UploadFile | None, File()] = None,
    source_url: Annotated[str | None, Form()] = None,
    tender_type: Annotated[str | None, Form()] = None,
    agency: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    external_ref: Annotated[str | None, Form()] = None,
    issued_on: Annotated[date | None, Form()] = None,
    priority: Annotated[bool, Form()] = False,
) -> SubmitOut:
    """A new tender from its RfS: a file, or the official URL it is published at (the host
    must be on infra/source-domains.yaml). Without `tender_type` the classifier names the
    type. The document is parsed, mapped, indexed and read without another call;
    `GET /tenders/{id}/status` says where it stands. `priority` reads with direct calls
    instead of the batch API. Needs the `write` scope."""
    data = await file.read() if file is not None else None
    try:
        submission = submit.submit_tender(
            session,
            filename=file.filename if file is not None else None,
            data=data,
            source_url=source_url or None,
            tender_type=tender_type or None,
            agency=agency or None,
            title=title or None,
            external_ref=external_ref or None,
            issued_on=issued_on,
            created_by=actor,
            priority=priority,
        )
    except SubmitError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return _submission(submission)


@router.post("/tenders/{tender_id}/submit-amendment", response_model=SubmitOut, status_code=202)
async def submit_amendment(
    tender_id: str,
    session: SessionDep,
    submit: SubmitDep,
    tenders: TendersDep,
    actor: ActorDep,
    kind: Annotated[str, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    source_url: Annotated[str | None, Form()] = None,
    issued_on: Annotated[date | None, Form()] = None,
    summary_of_change: Annotated[str | None, Form()] = None,
    force: Annotated[bool, Form()] = False,
    priority: Annotated[bool, Form()] = False,
) -> SubmitOut:
    """A corrigendum, amendment or clarification as the tender's next version, a file or
    an official URL. Before it is read, the engine checks the document names this tender;
    one that names another is refused unless `force`. Needs the `write` scope."""
    tender = _tender(tenders, session, tender_id)
    data = await file.read() if file is not None else None
    try:
        submission = submit.submit_amendment(
            session,
            tender,
            kind=kind,
            filename=file.filename if file is not None else None,
            data=data,
            source_url=source_url or None,
            issued_on=issued_on,
            summary_of_change=summary_of_change or None,
            created_by=actor,
            force=force,
            priority=priority,
        )
    except SubmitError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return _submission(submission)


@router.get("/tenders/{tender_id}/status", response_model=TenderStatus)
def get_status(
    tender_id: str, session: SessionDep, tenders: TendersDep, catalog: CatalogDep
) -> TenderStatus:
    """Where the tender's reading stands: per version its documents, runs and pending
    jobs; the tender's review and publication state."""
    tender = _tender(tenders, session, tender_id)
    return tender_status(session, catalog, tenders, tender)


@router.get("/tenders/{tender_id}/fields", response_model=TenderSnapshot)
def get_fields(
    tender_id: str,
    session: SessionDep,
    tenders: TendersDep,
    catalog: CatalogDep,
    review: ReviewStateDep,
) -> TenderSnapshot:
    """The snapshot (contract v1): every field with value, unit, page, quote, version,
    state (value, withdrawn, not_stated), approved or machine, and confidence."""
    tender = _tender(tenders, session, tender_id)
    return tender_snapshot(session, catalog, tenders, review, tender)


@router.post("/tenders/{tender_id}/review-link", response_model=ReviewLinkOut, status_code=201)
def mint_review_link(
    tender_id: str,
    body: ReviewLinkRequest,
    session: SessionDep,
    tenders: TendersDep,
    tokens: TokensDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> ReviewLinkOut:
    """A review link for a named reviewer (one reviewer per tender; an earlier link stops
    working). The link is a credential: hand it to the reviewer, store it nowhere else.
    Needs the `review:mint` scope."""
    tender = _tender(tenders, session, tender_id)
    try:
        token = tokens.create_for(
            session, "tender", tender.id, body.reviewer_name, created_by=actor
        )
    except ValueError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return ReviewLinkOut(
        url=review_url(settings.public_base_url, token.token),
        tender_id=tender.id,
        reviewer_name=token.reviewer_name,
        expires_at=token.expires_at,
    )


@router.post("/webhooks", response_model=WebhookOut, status_code=201)
def register_webhook(
    body: WebhookCreate, session: SessionDep, tenant_id: TenantDep, actor: ActorDep
) -> WebhookOut:
    """Register a URL for events (extraction_done, review_complete, new_version,
    amendment_detected). Every delivery is signed with the secret
    (`X-Tender-Signature: t=<unix>,v1=<HMAC-SHA256 of "<t>.<body>">`) and retried with
    backoff. Needs the `write` scope."""
    try:
        row = webhooks.register(
            session,
            tenant_id=tenant_id,
            url=body.url,
            events=body.events,
            secret=body.secret,
            created_by=actor,
            description=body.description,
        )
    except webhooks.WebhookError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return WebhookOut.model_validate(row, from_attributes=True)


@router.get("/webhooks", response_model=list[WebhookOut])
def list_webhooks(session: SessionDep, tenant_id: TenantDep) -> list[WebhookOut]:
    return [
        WebhookOut.model_validate(row, from_attributes=True)
        for row in webhooks.endpoints(session, tenant_id)
    ]


@router.delete("/webhooks/{endpoint_id}", response_model=WebhookOut)
def deactivate_webhook(
    endpoint_id: str, session: SessionDep, tenant_id: TenantDep, actor: ActorDep
) -> WebhookOut:
    """Stop deliveries to the endpoint; its record and its deliveries stay."""
    row = webhooks.deactivate(session, tenant_id=tenant_id, endpoint_id=endpoint_id, by=actor)
    if row is None:
        raise AppError("not_found", f"webhook {endpoint_id} does not exist")
    return WebhookOut.model_validate(row, from_attributes=True)


@router.get("/webhooks/{endpoint_id}/deliveries", response_model=list[DeliveryOut])
def list_deliveries(
    endpoint_id: str, session: SessionDep, tenant_id: TenantDep
) -> list[DeliveryOut]:
    """The latest deliveries to the endpoint, newest first, with each one's outcome."""
    return [
        DeliveryOut.model_validate(row, from_attributes=True)
        for row in webhooks.deliveries(session, tenant_id, endpoint_id)
    ]
