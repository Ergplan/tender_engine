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

from core.models import CanonicalFact
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
        # A later version replaces the earlier fact only when it states a value.
        if earlier is None or current.value is not None:
            chosen[current.field_path] = current
    fields = []
    for field in compiled.fields:
        fact: CanonicalFact | None = chosen.get(field.path)
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
