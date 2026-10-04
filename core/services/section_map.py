"""SectionMapper: the one full-document model pass. Everything after it works on sections."""

import re

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.llm.client import LLMClient, LLMRequest, TextPart
from core.models import Document, Page, Section

PROMPT_NAME = "section_map"
PAGE_PREVIEW_CHARS = 400
MAX_HEADINGS_PER_PAGE = 6
# Clause-style heading detection adapted from FDRE fdre_tender_rag.py:39 (CLAUSE_RE).
_HEADING = re.compile(
    r"^(?:(?:section|annexure|annex|format|chapter|article|schedule|appendix|part)\b[\s\-:–.]*\S.{0,90}"
    r"|\d{1,2}(?:\.\d{1,2}){0,2}\.?\s+[A-Z][^.]{3,90})$",
    re.IGNORECASE,
)


class MappedSection(BaseModel):
    start_page: int
    end_page: int
    heading: str
    kind: str
    confidence: float


class SectionMapOutput(BaseModel):
    sections: list[MappedSection]


class SectionMapper:
    def __init__(self, llm: LLMClient, tenant_id: str) -> None:
        self._llm = llm
        self._tenant_id = tenant_id

    def map(
        self,
        session: Session,
        document_id: str,
        prompt_version: str = "v1",
        *,
        is_fixture: bool = False,
    ) -> list[Section]:
        """Replace the document's sections with a fresh mapping."""
        document = session.scalar(
            select(Document).where(
                Document.id == document_id, Document.tenant_id == self._tenant_id
            )
        )
        if document is None or document.status != "parsed" or not document.page_count:
            raise LookupError(f"document {document_id} is not parsed")
        rows = session.execute(
            select(Page.page_no, Page.text)
            .where(Page.document_id == document.id, Page.tenant_id == self._tenant_id)
            .order_by(Page.page_no)
        ).all()
        digest = "\n\n".join(page_digest(page_no, text) for page_no, text in rows)
        response = self._llm.call(
            LLMRequest[SectionMapOutput](
                prompt_name=PROMPT_NAME,
                prompt_version=prompt_version,
                content=[
                    TextPart(
                        text=(
                            f"Document: {document.filename}\n"
                            f"Pages: 1 to {document.page_count}\n\n{digest}"
                        )
                    )
                ],
                response_model=SectionMapOutput,
                created_by="worker",
                is_fixture=is_fixture,
            )
        )
        sections = [
            Section(
                tenant_id=document.tenant_id,
                created_by="worker",
                document_id=document.id,
                start_page=item.start_page,
                end_page=item.end_page,
                heading=item.heading.strip()[:500] or "(untitled)",
                kind=normalise_kind(item.kind),
                confidence=min(max(item.confidence, 0.0), 1.0),
                prompt_version=prompt_version,
            )
            for item in clean_sections(response.parsed.sections, document.page_count)
        ]
        session.execute(
            delete(Section).where(
                Section.document_id == document.id, Section.tenant_id == self._tenant_id
            )
        )
        document.error = None
        session.add_all(sections)
        session.commit()
        return sections


def page_digest(page_no: int, text: str) -> str:
    preview = " ".join(text[:PAGE_PREVIEW_CHARS].split())
    lines = [f"=== page {page_no} ===", preview or "(no extractable text)"]
    headings = detect_headings(text)
    if headings:
        lines.append("Heading-like lines: " + " | ".join(headings))
    return "\n".join(lines)


def detect_headings(text: str) -> list[str]:
    found: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not 6 <= len(line) <= 100:
            continue
        letters = [char for char in line if char.isalpha()]
        all_caps = len(letters) >= 6 and all(char.isupper() for char in letters)
        if (_HEADING.match(line) or all_caps) and line not in found:
            found.append(line)
        if len(found) == MAX_HEADINGS_PER_PAGE:
            break
    return found


def normalise_kind(kind: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", kind.strip().lower()).strip("_")[:100] or "other"


def clean_sections(sections: list[MappedSection], page_count: int) -> list[MappedSection]:
    """Clamp ranges to the document and drop ranges that are empty or inverted."""
    cleaned = []
    for item in sorted(sections, key=lambda s: (s.start_page, s.end_page)):
        start, end = max(item.start_page, 1), min(item.end_page, page_count)
        if start <= end:
            cleaned.append(item.model_copy(update={"start_page": start, "end_page": end}))
    return cleaned
