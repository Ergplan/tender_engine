from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, UploadFile
from sqlalchemy import select

from api.deps import (
    ActorDep,
    CatalogDep,
    IngestDep,
    ReviewStateDep,
    SessionDep,
    SettingsDep,
    TenantDep,
    TendersDep,
)
from api.middleware.errors import AppError
from api.v1.schemas.core import ExtractionRunOut
from api.v1.schemas.tenders import (
    TenderCreate,
    TenderExtractRequest,
    TenderOut,
    TenderReviewState,
    TenderSchemaOut,
    VersionDocumentOut,
    VersionOut,
)
from core.llm.registry import UnregisteredPromptError
from core.models import ExtractionRun
from core.schemas import UnknownSchemaError
from core.services.extract import ExtractionError
from core.services.ingest import IngestError
from tender.models import Tender, TenderVersion
from tender.services import extraction_summary
from tender.services.current_view import TenderView, current_view, missing_required
from tender.services.extraction_summary import ExtractionSummary
from tender.services.tenders import OBJECT_TYPE, TenderError, TenderService, VersionDocuments

router = APIRouter(tags=["tenders"])


def _tender(tenders: TenderService, session: SessionDep, tender_id: str) -> Tender:
    try:
        return tenders.get(session, tender_id)
    except LookupError as exc:
        raise AppError("not_found", f"tender {tender_id} does not exist") from exc


def _tender_out(session: SessionDep, tender: Tender) -> TenderOut:
    current = session.scalar(
        select(TenderVersion.version_no).where(
            TenderVersion.id == tender.current_version_id,
            TenderVersion.tenant_id == tender.tenant_id,
        )
    )
    return TenderOut(
        id=tender.id,
        tender_type=tender.tender_type,
        issuing_agency=tender.issuing_agency,
        external_ref=tender.external_ref,
        title=tender.title,
        slug=tender.slug,
        status=tender.status,
        current_version_no=current,
        created_at=tender.created_at,
        created_by=tender.created_by,
    )


def _version_out(entry: VersionDocuments) -> VersionOut:
    version = entry.version
    return VersionOut(
        id=version.id,
        tender_id=version.tender_id,
        version_no=version.version_no,
        kind=version.kind,
        issued_on=version.issued_on,
        summary_of_change=version.summary_of_change,
        supersedes_version_id=version.supersedes_version_id,
        documents=[
            VersionDocumentOut(
                document_id=document.id,
                role=link.role,
                filename=document.filename,
                page_count=document.page_count,
                status=document.status,
            )
            for link, document in entry.documents
        ],
    )


@router.post("/tenders", response_model=TenderOut, status_code=201)
def create_tender(
    body: TenderCreate, session: SessionDep, tenders: TendersDep, actor: ActorDep
) -> TenderOut:
    """Create a tender. Its documents are added as versions."""
    try:
        tender = tenders.create(
            session,
            tender_type=body.type,
            issuing_agency=body.agency,
            external_ref=body.external_ref,
            title=body.title,
            created_by=actor,
        )
    except (TenderError, LookupError) as exc:
        raise AppError("validation_failed", str(exc)) from exc
    return _tender_out(session, tender)


@router.get("/tenders", response_model=list[TenderOut])
def list_tenders(session: SessionDep, tenders: TendersDep) -> list[TenderOut]:
    found = tenders.all(session)
    for tender in found:
        tenders.refresh_status(session, tender)
    return [_tender_out(session, tender) for tender in found]


@router.get("/tenders/{tender_id}", response_model=TenderOut)
def get_tender(tender_id: str, session: SessionDep, tenders: TendersDep) -> TenderOut:
    tender = _tender(tenders, session, tender_id)
    tenders.refresh_status(session, tender)
    return _tender_out(session, tender)


@router.post("/tenders/{tender_id}/versions", response_model=VersionOut, status_code=201)
async def add_version(
    tender_id: str,
    file: UploadFile,
    session: SessionDep,
    tenders: TendersDep,
    ingest: IngestDep,
    actor: ActorDep,
    kind: Annotated[str | None, Form()] = None,
    issued_on: Annotated[date | None, Form()] = None,
    role: Annotated[str | None, Form()] = None,
    summary_of_change: Annotated[str | None, Form()] = None,
    version_no: Annotated[int | None, Form()] = None,
) -> VersionOut:
    """Upload a document as a new version of the tender: the original first, then one
    version per corrigendum, amendment or clarification; `kind` is required. With
    `version_no`, the document is added to that existing version instead (a PPA or a
    technical volume): `role` is required and `kind`, if sent, must be that version's own
    kind, so a change to the tender can never be filed inside an existing version. The
    document is parsed in the background; start extraction once it is."""
    tender = _tender(tenders, session, tender_id)
    data = await file.read()
    try:
        if version_no is None and kind is None:
            raise TenderError("`kind` is required for a new version")
        if version_no is not None:
            existing = next(
                (
                    entry.version
                    for entry in tenders.versions(session, tender)
                    if entry.version.version_no == version_no
                ),
                None,
            )
            if existing is None:
                raise LookupError(f"tender {tender.id} has no version {version_no}")
            if kind is not None and kind != existing.kind:
                raise TenderError(
                    f"version {version_no} is {existing.kind!r}; a {kind!r} document is a "
                    "new version, not an addition to this one"
                )
        document, _ = ingest.upload(
            session, filename=file.filename or "upload.pdf", data=data, created_by=actor
        )
        if version_no is None and kind is not None:
            version = tenders.add_version(
                session,
                tender,
                document,
                kind,
                issued_on,
                created_by=actor,
                role=role,
                summary_of_change=summary_of_change,
            )
        elif version_no is not None:
            if role is None:
                raise TenderError("`role` is required when adding a document to a version")
            version = tenders.attach_document(
                session, tender, version_no, document, role, created_by=actor
            )
    except (TenderError, IngestError) as exc:
        raise AppError("validation_failed", str(exc)) from exc
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc
    entry = next(e for e in tenders.versions(session, tender) if e.version.id == version.id)
    return _version_out(entry)


@router.get("/tenders/{tender_id}/versions", response_model=list[VersionOut])
def list_versions(tender_id: str, session: SessionDep, tenders: TendersDep) -> list[VersionOut]:
    tender = _tender(tenders, session, tender_id)
    return [_version_out(entry) for entry in tenders.versions(session, tender)]


@router.get("/tenders/{tender_id}/view", response_model=TenderView)
def get_view(
    tender_id: str, session: SessionDep, tenders: TendersDep, catalog: CatalogDep
) -> TenderView:
    """The current view: per field, the canonical value from the latest version that set
    it, with that version's number and kind. Canonical facts only, never candidates."""
    return current_view(session, catalog, _tender(tenders, session, tender_id))


@router.post("/tenders/{tender_id}/extract", response_model=list[ExtractionRunOut], status_code=202)
def start_extraction(
    tender_id: str,
    body: TenderExtractRequest,
    session: SessionDep,
    tenders: TendersDep,
    actor: ActorDep,
) -> list[ExtractionRun]:
    """Queue the extraction of one version (the latest by default): one run per document.
    A version after the original is read only for the sections its documents touch. A long
    amendment, or one whose text matches no section keyword, is first mapped in full by a
    background job, which then queues its run; such a run is not in this response."""
    tender = _tender(tenders, session, tender_id)
    try:
        return tenders.start_extraction(
            session,
            tender,
            version_no=body.version_no,
            prompt_version=body.prompt_version,
            created_by=actor,
        )
    except (TenderError, UnknownSchemaError, UnregisteredPromptError, ExtractionError) as exc:
        raise AppError("validation_failed", str(exc)) from exc
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc


@router.get("/tenders/{tender_id}/review-state", response_model=TenderReviewState)
def get_review_state(
    tender_id: str,
    session: SessionDep,
    tenders: TendersDep,
    review_state: ReviewStateDep,
    catalog: CatalogDep,
    tenant_id: TenantDep,
    version: int | None = None,
) -> TenderReviewState:
    """Core's review state for one version of the tender (the latest extracted by default)."""
    tender = _tender(tenders, session, tender_id)
    state = review_state.for_object(session, OBJECT_TYPE, tender.id, version)
    kind = session.scalar(
        select(TenderVersion.kind).where(
            TenderVersion.tender_id == tender.id,
            TenderVersion.version_no == state.object_version,
            TenderVersion.tenant_id == tenant_id,
        )
    )
    return TenderReviewState(
        tender_id=tender.id,
        version_no=state.object_version if state.run else version,
        version_kind=kind if state.run or version else None,
        changed_fields=[
            field.field_path
            for field in state.fields
            if field.candidate is not None and field.candidate.value is not None
        ],
        missing_required=missing_required(
            session, catalog, tender, state.object_version if state.run else version
        ),
        state=state,
    )


@router.get("/reports/extraction-summary", response_model=ExtractionSummary)
def get_extraction_summary(
    session: SessionDep,
    tenders: TendersDep,
    review_state: ReviewStateDep,
    catalog: CatalogDep,
    settings: SettingsDep,
    tenant_id: TenantDep,
) -> ExtractionSummary:
    """What extraction returned for every tender, before review: evidence-location rate,
    answer rate, validation failures, tokens and cost, as data and as the Markdown report."""
    return extraction_summary.build(
        session,
        catalog,
        tenders,
        review_state,
        settings.model_copy(update={"tenant_id": tenant_id}),
    )


@router.get("/schemas/tender/{tender_type}", response_model=TenderSchemaOut)
def get_schema(tender_type: str, catalog: CatalogDep) -> TenderSchemaOut:
    """The compiled field list of a tender type, in review order."""
    try:
        compiled = catalog.get(tender_type)
    except LookupError as exc:
        raise AppError("not_found", str(exc)) from exc
    return TenderSchemaOut(
        tender_type=compiled.tender_type,
        pack=compiled.pack,
        schema_name=compiled.schema.name,
        schema_version=compiled.schema.version,
        sections=compiled.sections,
        fields=compiled.fields,
    )
