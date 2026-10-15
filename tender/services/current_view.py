"""The current view of a tender: a projection of its canonical facts over its versions.

Per field, the value comes from the latest version that set it, and the view says which
version that was. A later version that says nothing about a field leaves the earlier
fact in place; so does a later decision that the field is not in that version's document.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Candidate, CanonicalFact, ExtractionRun
from tender.models import Tender, TenderVersion
from tender.services.packs import Catalog
from tender.services.tenders import OBJECT_TYPE


class FieldView(BaseModel):
    field_path: str
    label: str
    section: str
    value_type: str
    unit: str | None
    decided: bool
    value: Any
    version_no: int | None
    version_kind: str | None
    canonical_fact_id: str | None
    approval_id: str | None
    effective_at: datetime | None
    evidence: list[dict[str, Any]]
    # The provision was withdrawn by `version_no`: no value stands. A ceiling that never
    # existed (`decided` false, or a decided null) is told apart from one removed by an
    # amendment, which keeps the value it removed and the version it stood from.
    withdrawn: bool = False
    withdrawn_value: Any = None
    withdrawn_from_version: int | None = None


class TenderView(BaseModel):
    tender_id: str
    tender_type: str
    current_version_no: int | None
    decided: int
    total: int
    fields: list[FieldView]


def current_view(session: Session, catalog: Catalog, tender: Tender) -> TenderView:
    compiled = catalog.get(tender.tender_type)
    kinds = {
        version_no: kind
        for version_no, kind in session.execute(
            select(TenderVersion.version_no, TenderVersion.kind).where(
                TenderVersion.tender_id == tender.id, TenderVersion.tenant_id == tender.tenant_id
            )
        )
    }
    chosen: dict[str, CanonicalFact] = {}
    withdrawn_from: dict[str, CanonicalFact] = {}
    for current in session.scalars(
        select(CanonicalFact)
        .where(
            CanonicalFact.tenant_id == tender.tenant_id,
            CanonicalFact.object_type == OBJECT_TYPE,
            CanonicalFact.object_id == tender.id,
            CanonicalFact.is_current.is_(True),
        )
        .order_by(CanonicalFact.object_version)
    ):
        earlier = chosen.get(current.field_path)
        # A later version replaces the earlier fact when it states a value, or when it
        # withdraws the provision: then the view holds no value and says which version
        # withdrew it, and what stood before.
        if earlier is None or current.value is not None or current.withdrawn:
            chosen[current.field_path] = current
            if current.withdrawn and earlier is not None and not earlier.withdrawn:
                withdrawn_from[current.field_path] = earlier
    fields = []
    for field in compiled.fields:
        fact: CanonicalFact | None = chosen.get(field.path)
        before = withdrawn_from.get(field.path)
        fields.append(
            FieldView(
                field_path=field.path,
                label=field.label,
                section=field.section,
                value_type=field.value_type,
                unit=field.unit,
                decided=fact is not None,
                value=fact.value if fact else None,
                version_no=fact.object_version if fact else None,
                version_kind=kinds.get(fact.object_version) if fact else None,
                canonical_fact_id=fact.id if fact else None,
                approval_id=fact.approval_id if fact else None,
                effective_at=fact.effective_at if fact else None,
                evidence=fact.evidence if fact else [],
                withdrawn=bool(fact and fact.withdrawn),
                withdrawn_value=before.value if before else None,
                withdrawn_from_version=before.object_version if before else None,
            )
        )
    return TenderView(
        tender_id=tender.id,
        tender_type=tender.tender_type,
        current_version_no=max(kinds) if kinds else None,
        decided=sum(1 for field in fields if field.decided),
        total=len(fields),
        fields=fields,
    )


def missing_required(
    session: Session, catalog: Catalog, tender: Tender, version_no: int | None = None
) -> list[str]:
    """Required fields the tender does not have up to the given version (the latest by
    default): no live candidate with a value in any of its versions, and no canonical
    fact with a value. A corrigendum need not restate a required field; the tender must
    have it."""
    compiled = catalog.get(tender.tender_type)
    required = [field.path for field in compiled.fields if field.required]
    limit = version_no if version_no is not None else 10**9
    stated = set(
        session.scalars(
            select(Candidate.field_path)
            .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
            .where(
                Candidate.tenant_id == tender.tenant_id,
                ExtractionRun.tenant_id == tender.tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.object_id == tender.id,
                ExtractionRun.object_version <= limit,
                Candidate.field_path.in_(required),
                Candidate.value.is_not(None),
                Candidate.status.in_(("validated", "needs_review")),
            )
        )
    )
    stated |= set(
        session.scalars(
            select(CanonicalFact.field_path).where(
                CanonicalFact.tenant_id == tender.tenant_id,
                CanonicalFact.object_type == OBJECT_TYPE,
                CanonicalFact.object_id == tender.id,
                CanonicalFact.object_version <= limit,
                CanonicalFact.is_current.is_(True),
                CanonicalFact.value.is_not(None),
            )
        )
    )
    return [path for path in required if path not in stated]
