from fastapi import APIRouter, Response, UploadFile
from sqlalchemy import select

from api.deps import ActorDep, IngestDep, SessionDep, StorageDep, TenantDep
from api.middleware.errors import AppError
from api.v1.schemas.core import DocumentOut, SectionOut
from core.models import Document, Page, Section
from core.services.ingest import IngestError

router = APIRouter(tags=["documents"])


def _document(session: SessionDep, tenant_id: str, document_id: str) -> Document:
    document = session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if document is None:
        raise AppError("not_found", f"document {document_id} does not exist")
    return document


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile, response: Response, session: SessionDep, ingest: IngestDep, actor: ActorDep
) -> Document:
    """Upload a PDF. The same file uploaded twice returns the first document with 200."""
    data = await file.read()
    try:
        document, created = ingest.upload(
            session, filename=file.filename or "upload.pdf", data=data, created_by=actor
        )
    except IngestError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    if not created:
        response.status_code = 200
    return document


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, session: SessionDep, tenant_id: TenantDep) -> Document:
    return _document(session, tenant_id, document_id)


@router.get("/documents/{document_id}/pages/{page_no}/render")
def get_page_render(
    document_id: str, page_no: int, session: SessionDep, tenant_id: TenantDep, storage: StorageDep
) -> Response:
    """The page as a PNG at the configured render resolution."""
    _document(session, tenant_id, document_id)
    render_path = session.scalar(
        select(Page.render_path).where(
            Page.document_id == document_id, Page.page_no == page_no, Page.tenant_id == tenant_id
        )
    )
    if render_path is None or not storage.exists(render_path):
        raise AppError("not_found", f"page {page_no} has no render")
    return Response(
        content=storage.get(render_path),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )


@router.get("/documents/{document_id}/sections", response_model=list[SectionOut])
def get_sections(document_id: str, session: SessionDep, tenant_id: TenantDep) -> list[Section]:
    _document(session, tenant_id, document_id)
    return list(
        session.scalars(
            select(Section)
            .where(Section.document_id == document_id, Section.tenant_id == tenant_id)
            .order_by(Section.start_page, Section.end_page)
        )
    )
