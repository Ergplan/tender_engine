from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, Response, UploadFile
from sqlalchemy import select

from api.deps import ActorDep, IngestDep, SessionDep, StorageDep, TenantDep
from api.middleware.errors import AppError
from api.v1.schemas.core import DocumentOut, PageOut, SearchHit, SectionOut
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


FILES = "/files/"
MAX_HITS = 200


def _out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        sha256=document.sha256,
        filename=document.filename,
        mime=document.mime,
        page_count=document.page_count,
        status=document.status,
        error=document.error,
        created_at=document.created_at,
        created_by=document.created_by,
        file_url=FILES + document.storage_path,
        source_url=document.source_url,
        retrieved_on=document.retrieved_on,
    )


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile,
    response: Response,
    session: SessionDep,
    ingest: IngestDep,
    actor: ActorDep,
    source_url: Annotated[str | None, Form(max_length=1000)] = None,
    retrieved_on: Annotated[date | None, Form()] = None,
) -> DocumentOut:
    """Upload a PDF with, where known, the URL it was taken from and the day it was fetched.
    The same file uploaded twice returns the first document with 200; provenance given
    then fills what the first upload left blank."""
    data = await file.read()
    try:
        document, created = ingest.upload(
            session,
            filename=file.filename or "upload.pdf",
            data=data,
            created_by=actor,
            source_url=source_url,
            retrieved_on=retrieved_on,
        )
    except IngestError as exc:
        raise AppError("validation_failed", str(exc)) from exc
    if not created:
        response.status_code = 200
    return _out(document)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, session: SessionDep, tenant_id: TenantDep) -> DocumentOut:
    return _out(_document(session, tenant_id, document_id))


@router.get("/documents/{document_id}/pages", response_model=list[PageOut])
def get_pages(document_id: str, session: SessionDep, tenant_id: TenantDep) -> list[PageOut]:
    """Every page with its size, so a viewer can lay the document out before any page is
    drawn, and where its image is served."""
    _document(session, tenant_id, document_id)
    return [
        PageOut(
            page_no=page_no,
            width=width,
            height=height,
            has_text_layer=has_text_layer,
            render_url=FILES + render_path if render_path else None,
        )
        for page_no, width, height, has_text_layer, render_path in session.execute(
            select(Page.page_no, Page.width, Page.height, Page.has_text_layer, Page.render_path)
            .where(Page.document_id == document_id, Page.tenant_id == tenant_id)
            .order_by(Page.page_no)
        )
    ]


@router.get("/documents/{document_id}/search", response_model=list[SearchHit])
def search_document(
    document_id: str, q: str, session: SessionDep, tenant_id: TenantDep
) -> list[SearchHit]:
    """Where the text occurs in the document, ignoring case: page, box and the words
    around it. At most 200 places."""
    _document(session, tenant_id, document_id)
    needle = " ".join(q.split()).casefold()
    if len(needle) < 2:
        raise AppError("validation_failed", "search for at least two characters")
    hits: list[SearchHit] = []
    # Only pages that hold the first word are loaded with their character boxes.
    first_word = needle.split(" ")[0].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    for page_no, text, boxes in session.execute(
        select(Page.page_no, Page.text, Page.char_boxes)
        .where(
            Page.document_id == document_id,
            Page.tenant_id == tenant_id,
            Page.text.ilike(f"%{first_word}%", escape="\\"),
        )
        .order_by(Page.page_no)
    ):
        # A line break inside the phrase counts as a space.
        haystack = "".join(" " if char.isspace() else char for char in text).casefold()
        # Case folding can change the length of a text; boxes are then not looked up.
        aligned = len(haystack) == len(text)
        start = haystack.find(needle)
        while start != -1 and len(hits) < MAX_HITS:
            end = start + len(needle)
            hits.append(
                SearchHit(
                    page_no=page_no,
                    bbox=_union(boxes[start:end]) if aligned and boxes else None,
                    snippet=" ".join(text[max(start - 40, 0) : end + 40].split()),
                )
            )
            start = haystack.find(needle, end)
        if len(hits) >= MAX_HITS:
            break
    return hits


def _union(boxes: list[list[float] | None]) -> list[float] | None:
    found = [box for box in boxes if box]
    if not found:
        return None
    return [
        min(box[0] for box in found),
        min(box[1] for box in found),
        max(box[2] for box in found),
        max(box[3] for box in found),
    ]


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
