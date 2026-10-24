from datetime import date
from typing import Any

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, IdMixin, TenantAuditMixin

DOCUMENT_STATUSES = ("uploaded", "parsed", "failed")


class Document(IdMixin, TenantAuditMixin, Base):
    """An uploaded file. Immutable content, addressed by sha256; deduplicated per tenant."""

    __tablename__ = "document"
    __table_args__ = (UniqueConstraint("tenant_id", "sha256", name="uq_document_tenant_sha256"),)

    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provenance: the URL the file was taken from and the day it was fetched. Null on
    # documents ingested before 2026-10-07 whose manifest does not say.
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    retrieved_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The type classifier's answer for this document (Stage 7, Block 2 d): tender_type,
    # state (set, unsure, unknown), confidence, reasons, alternatives, prompt_version. Null
    # until the `classify_type` job has run. A guess, never a fact; a tender created from
    # it carries the same provenance on its own row.
    # Deferred: loaded only when read (`api.v1.core.documents` reads it through a savepoint
    # so a database that has not yet run migration 0022 still serves documents).
    classification: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, deferred=True
    )


class Page(IdMixin, TenantAuditMixin, Base):
    """One page: text, size in PDF points, a 150 dpi render, and a box for every character.

    char_boxes is aligned with text: char_boxes[i] is [x0, top, x1, bottom] for text[i],
    or null for whitespace the text layout inserted. Origin is the page's top-left corner.
    """

    __tablename__ = "page"
    __table_args__ = (UniqueConstraint("document_id", "page_no", name="uq_page_document_page_no"),)

    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False, index=True)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    render_path: Mapped[str] = mapped_column(String(500), nullable=False)
    char_boxes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    has_text_layer: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Which parsing layer produced the text and boxes (Stage 7, Block 2): `pdfplumber` for
    # a native text layer, `docling` for a page OCR'd or re-read on the VM, `llamaparse`
    # for a page read by LlamaParse (only when the tender allows the document to leave
    # the VM). `layer_detail` carries what the layer reported (OCR engine, tables found,
    # confidence) for the parser benchmark and the page view.
    parser_layer: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pdfplumber", default="pdfplumber"
    )
    layer_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class Section(IdMixin, TenantAuditMixin, Base):
    """A contiguous page range with a heading and a free-text kind; from the section mapper."""

    __tablename__ = "section"

    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False, index=True)
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
