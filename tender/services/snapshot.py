"""The snapshot of a tender for any caller (Stage 7, Block 6 a): every field of the record
with its value, unit, page, quote, version, state (value, withdrawn, not_stated), whether it
is approved or a machine reading, and its confidence. Contract v1, additive only
(`docs/contracts/snapshot.v1.schema.json`, checked by `scripts.export_contract --check`).

Approved values come from the current view (canonical facts projected over the versions);
machine readings from the review state of each version, the latest valued version of a
field winning, the way the extraction summary picks them. Nothing here writes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.services.review_state import FieldState, ReviewStateService
from tender.models import Tender
from tender.services.current_view import current_view
from tender.services.packs import Catalog
from tender.services.publication import publication_state
from tender.services.published import AUTHORITY_NOTE
from tender.services.tenders import OBJECT_TYPE, TenderService

CONTRACT_VERSION = "1"

FieldStateName = Literal["value", "withdrawn", "not_stated"]
SourceName = Literal["approved", "machine", "none"]


class SnapshotEvidence(BaseModel):
    document_id: str
    filename: str | None = None
    page_no: int
    quote: str
    located: bool


class SnapshotField(BaseModel):
    path: str
    section: str
    label: str
    value_type: str
    unit: str | None = None
    state: FieldStateName
    source: SourceName
    value: Any = None
    confidence: float | None = Field(default=None, description="machine readings only")
    version_no: int | None = None
    version_kind: str | None = None
    withdrawn_from_version: int | None = None
    evidence: list[SnapshotEvidence] = []
    needs_review: bool = False


class TenderSnapshot(BaseModel):
    contract_version: str = CONTRACT_VERSION
    tender_id: str
    slug: str | None
    title: str
    issuing_agency: str
    tender_type: str
    external_ref: str | None
    status: str
    current_version: int | None
    reviewed_version: int | None
    publication: str
    generated_at: datetime
    fields: list[SnapshotField]
    approved: int
    machine: int
    not_stated: int
    authority_note: str = AUTHORITY_NOTE


def tender_snapshot(
    session: Session,
    catalog: Catalog,
    tenders: TenderService,
    review: ReviewStateService,
    tender: Tender,
) -> TenderSnapshot:
    compiled = catalog.get(tender.tender_type)
    view = current_view(session, catalog, tender)
    decided = {f.field_path: f for f in view.fields}
    entries = tenders.versions(session, tender)
    kinds = {e.version.version_no: e.version.kind for e in entries}
    filenames = {
        document.id: document.filename for entry in entries for _, document in entry.documents
    }
    chosen: dict[str, tuple[int, FieldState]] = {}
    for entry in entries:
        number = entry.version.version_no
        state = review.for_object(session, OBJECT_TYPE, tender.id, number)
        for item in state.fields:
            valued = item.candidate is not None and item.candidate.value is not None
            if valued or item.field_path not in chosen:
                chosen[item.field_path] = (number, item)
    derived = {section.name for section in compiled.sections if section.derived}
    fields: list[SnapshotField] = []
    for spec in compiled.fields:
        if spec.section in derived:
            continue
        base = dict(
            path=spec.path,
            section=spec.section,
            label=spec.label,
            value_type=spec.value_type,
            unit=spec.unit,
        )
        fact = decided.get(spec.path)
        if fact is not None and fact.decided:
            fields.append(
                SnapshotField(
                    **base,
                    state=_state(fact.value, fact.withdrawn),
                    source="approved",
                    value=fact.value,
                    version_no=fact.version_no,
                    version_kind=fact.version_kind,
                    withdrawn_from_version=fact.withdrawn_from_version,
                    evidence=[
                        SnapshotEvidence(
                            document_id=str(e.get("document_id") or ""),
                            filename=filenames.get(str(e.get("document_id") or "")),
                            page_no=int(e.get("page_no") or 0),
                            quote=str(e.get("quote") or ""),
                            located=e.get("char_start") is not None,
                        )
                        for e in fact.evidence
                    ],
                )
            )
            continue
        picked = chosen.get(spec.path)
        candidate = picked[1].candidate if picked else None
        if (
            picked is None
            or candidate is None
            or (candidate.value is None and not candidate.withdrawn)
        ):
            fields.append(SnapshotField(**base, state="not_stated", source="none"))
            continue
        number = picked[0]
        fields.append(
            SnapshotField(
                **base,
                state=_state(candidate.value, candidate.withdrawn),
                source="machine",
                value=_typed(review, compiled.schema, spec.path, candidate.value),
                confidence=candidate.confidence,
                version_no=number,
                version_kind=kinds.get(number),
                evidence=[
                    SnapshotEvidence(
                        document_id=e.document_id,
                        filename=filenames.get(e.document_id),
                        page_no=e.page_no,
                        quote=e.quote,
                        located=e.char_start is not None,
                    )
                    for e in candidate.evidence
                ],
                needs_review=candidate.status == "needs_review",
            )
        )
    publication = publication_state(session, catalog, tender)
    return TenderSnapshot(
        tender_id=tender.id,
        slug=tender.slug,
        title=tender.title,
        issuing_agency=tender.issuing_agency,
        tender_type=tender.tender_type,
        external_ref=tender.external_ref,
        status=tender.status,
        current_version=view.current_version_no,
        reviewed_version=publication.reviewed_version,
        publication=publication.state,
        generated_at=datetime.now(UTC),
        fields=fields,
        approved=sum(1 for f in fields if f.source == "approved"),
        machine=sum(1 for f in fields if f.source == "machine"),
        not_stated=sum(1 for f in fields if f.state == "not_stated"),
    )


def _typed(review: ReviewStateService, schema: Any, path: str, value: Any) -> Any:
    """A machine reading as its type (a date as ISO, a number as a number), the way an
    approval stores it; the raw text when it cannot be read as the type."""
    if value is None:
        return None
    try:
        return review.schemas.value_types.coerce(value, schema.field(path))
    except Exception:  # noqa: BLE001  (a reading the type refuses is shown as read)
        return value


def _state(value: Any, withdrawn: bool) -> FieldStateName:
    if withdrawn:
        return "withdrawn"
    return "value" if value is not None else "not_stated"
