"""Tender type classification with a calibrated confidence (Stage 7, Block 2 d).

One text-only model call over the opening pages of a parsed document gives a type and a
confidence. The bands decide what happens, and nothing is forced:

- at or above SURE: the type is `set`, source `model`;
- between UNSURE and SURE: the type is the model's best guess, state `unsure`, and the
  reviewer is asked (the tender record and the API say so; `set_type` records the answer);
- below UNSURE, or `unknown`: state `unknown`; the tender is read with the core sections
  only (`core_groups`) and the record says so.

The call is logged like every model call; the answer is never a fact.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.llm.client import LLMClient, LLMRequest, TextPart
from core.models import Document, Page
from core.schemas import ExtractionSchema
from tender.models.tender import TENDER_TYPES

PROMPT_NAME = "classify_type"
PROMPT_VERSION = "v1"
SURE = 0.8
UNSURE = 0.5
PAGES_READ = 8
CHARS_PER_PAGE = 2500

TenderTypeName = Literal[
    "solar",
    "wind",
    "hybrid",
    "fdre",
    "bess",
    "re_rtc",
    "transmission",
    "generation",
    "epc",
    "ipp",
    "unknown",
]
TypeState = Literal["set", "unsure", "unknown"]


class TenderTypeOutput(BaseModel):
    tender_type: TenderTypeName
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: str = ""
    alternatives: list[str] = []


class Classification(BaseModel):
    """What the engine does with the answer."""

    tender_type: str  # the schema to read with; the best guess when unsure or unknown
    state: TypeState
    confidence: float
    reasons: str
    alternatives: list[str]
    prompt_version: str = PROMPT_VERSION

    @property
    def ask_reviewer(self) -> bool:
        return self.state != "set"


def state_for(output: TenderTypeOutput) -> Classification:
    """The bands applied to a model answer. An `unknown` answer, or a confidence below the
    unsure band, is `unknown` and the type falls back to `ipp` (the generic procurement
    schema: its sector sections are not read when the state is unknown)."""
    alternatives = [a for a in output.alternatives if a in TENDER_TYPES and a != output.tender_type]
    if output.tender_type == "unknown" or output.confidence < UNSURE:
        guess = alternatives[0] if alternatives and output.tender_type == "unknown" else None
        if output.tender_type != "unknown":
            guess = output.tender_type
        return Classification(
            tender_type=guess or "ipp",
            state="unknown",
            confidence=output.confidence,
            reasons=output.reasons,
            alternatives=alternatives,
        )
    return Classification(
        tender_type=output.tender_type,
        state="set" if output.confidence >= SURE else "unsure",
        confidence=output.confidence,
        reasons=output.reasons,
        alternatives=alternatives,
    )


def core_groups(schema: ExtractionSchema) -> list[str]:
    """The field groups read when the type is unknown: those whose every field is a core
    field (path under `core.`), never a sector section."""
    paths_by_group: dict[str, list[str]] = {}
    for field in schema.fields:
        paths_by_group.setdefault(field.group, []).append(field.path)
    return [
        group.name
        for group in schema.groups
        if not (group.derived or group.imported)
        and paths_by_group.get(group.name)
        and all(path.startswith("core.") for path in paths_by_group[group.name])
    ]


class TypeClassifier:
    def __init__(self, llm: LLMClient, tenant_id: str) -> None:
        self._llm = llm
        self._tenant_id = tenant_id

    def classify(
        self, session: Session, document_id: str, *, created_by: str, is_fixture: bool = False
    ) -> Classification:
        document = session.scalar(
            select(Document).where(
                Document.id == document_id, Document.tenant_id == self._tenant_id
            )
        )
        if document is None:
            raise LookupError(f"document {document_id} not found")
        if document.status != "parsed":
            raise ValueError(f"document is {document.status}, not parsed")
        rows = session.execute(
            select(Page.page_no, Page.text)
            .where(Page.document_id == document.id, Page.tenant_id == self._tenant_id)
            .order_by(Page.page_no)
            .limit(PAGES_READ)
        ).all()
        digest = "\n\n".join(
            f"--- page {page_no} ---\n{' '.join(text.split())[:CHARS_PER_PAGE]}"
            for page_no, text in rows
        )
        response = self._llm.call(
            LLMRequest[TenderTypeOutput](
                prompt_name=PROMPT_NAME,
                prompt_version=PROMPT_VERSION,
                content=[
                    TextPart(
                        text=(
                            f"Document: {document.filename}\n"
                            f"Pages: {document.page_count}; the first {len(rows)} follow.\n\n"
                            f"{digest}"
                        )
                    )
                ],
                response_model=TenderTypeOutput,
                created_by=created_by,
                is_fixture=is_fixture,
            )
        )
        return state_for(response.parsed)


def job_handlers(classifier: TypeClassifier) -> dict[str, Any]:
    """`classify_type` {document_id, created_by?, tender_id?}: classify a parsed document
    and write the answer on the document; with a `tender_id`, also on that tender (source
    `model`, state from the bands) unless a person already set its type."""
    from core.models import Document
    from tender.models import Tender

    def classify_type(session: Session, payload: dict[str, Any]) -> None:
        created_by = str(payload.get("created_by") or "worker")
        found = classifier.classify(
            session,
            payload["document_id"],
            created_by=created_by,
            is_fixture=bool(payload.get("is_fixture", False)),
        )
        document = session.get(Document, payload["document_id"])
        assert document is not None
        document.classification = found.model_dump()
        tender_id = payload.get("tender_id")
        if tender_id:
            tender = session.get(Tender, tender_id)
            if tender is not None and tender.type_source != "reviewer":
                tender.tender_type = found.tender_type
                tender.type_source = "model"
                tender.type_state = found.state
                tender.type_confidence = found.confidence
        session.commit()

    return {"classify_type": classify_type}
