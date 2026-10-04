from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
