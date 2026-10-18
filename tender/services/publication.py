"""Publication state (Stage 5C, the machine of the 5D public library): what a reader
outside the review may be shown of a tender, independent of its review state.

  not_published         no completed review yet
  published             the current version is reviewed
  update_pending        a later version exists and is not reviewed: the reviewed facts
                        stay visible with a banner naming the version and its issue date,
                        and the fields that version may touch are marked possibly superseded
  publication_suspended the unreviewed version touches a critical field (bid deadline,
                        capacity, EMD or PBG, tariff ceiling, SCOD, eligibility thresholds):
                        lookups return the suspension and the amending documents, never
                        the stale values

Which fields a version may touch comes from its own readings — the candidates its runs
produced with a value or a withdrawal — which is the section-map routing of Stage 2 seen
from the other side. A version is reviewed once a completed review (or round) has seen
it: the latest snapshot's `current_version_no`.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Candidate, ExtractionRun
from core.models.extraction import REVIEWABLE_STATUSES
from tender.models import PublicationHold, Tender, TenderVersion, TenderVersionDocument
from tender.services.packs import Catalog
from tender.services.review import latest_snapshot
from tender.services.tenders import OBJECT_TYPE

PublicationStatus = Literal["not_published", "published", "update_pending", "publication_suspended"]
# A change to one of these by an unreviewed version suspends publication: a reader must
# not act on a stale deadline, capacity, guarantee, ceiling, commissioning date or
# eligibility threshold.
CRITICAL_FIELDS = frozenset(
    {
        "core.key_dates.bid_submission_deadline",
        "sector.power.common.total_capacity_mw",
        "sector.power.common.total_capacity_mwh",
        "core.guarantees.emd_per_mw_inr",
        "core.guarantees.pbg_per_mw_inr",
        "sector.power.common.tariff_ceiling_inr_per_kwh",
        "sector.power.ipp.tariff_ceiling_inr_per_kwh",
        "sector.power.common.scod_months",
        "sector.power.ipp.scod_months",
        "sector.power.common.min_commissioned_mw",
        "sector.power.common.net_worth_per_mw_inr",
        "core.eligibility.turnover_requirement_inr",
        "core.eligibility.liquidity_requirement_inr",
    }
)


class UnreviewedVersion(BaseModel):
    version_no: int
    kind: str
    issued_on: date | None
    document_ids: list[str]


class PublicationState(BaseModel):
    state: PublicationStatus
    reviewed_version: int | None
    current_version: int | None
    # The latest version no completed review has seen, with the documents of every
    # unreviewed version.
    unreviewed_version: UnreviewedVersion | None = None
    # Fields the unreviewed versions read a value for: shown as possibly superseded.
    possibly_superseded: list[str] = []
    # The critical fields among them: when any, publication is suspended.
    suspended_by: list[str] = []


def standing_hold(session: Session, tender: Tender) -> PublicationHold | None:
    """The oldest hold on the tender that has not been lifted, or None."""
    return session.scalar(
        select(PublicationHold)
        .where(
            PublicationHold.tenant_id == tender.tenant_id,
            PublicationHold.tender_id == tender.id,
            PublicationHold.lifted_at.is_(None),
        )
        .order_by(PublicationHold.created_at)
        .limit(1)
    )


def reviewed_version_of(session: Session, tender: Tender) -> int | None:
    """The version the latest completed review saw, or None without one."""
    snapshot = latest_snapshot(session, tender)
    if snapshot is None:
        return None
    seen = (snapshot.snapshot.get("view") or {}).get("current_version_no")
    return int(seen) if seen else 1


def fields_touched(session: Session, tender: Tender, version_no: int) -> set[str]:
    """The fields a version states or withdraws: its live, reviewable readings."""
    return set(
        session.scalars(
            select(Candidate.field_path)
            .join(ExtractionRun, Candidate.extraction_run_id == ExtractionRun.id)
            .where(
                Candidate.tenant_id == tender.tenant_id,
                ExtractionRun.tenant_id == tender.tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.object_id == tender.id,
                ExtractionRun.object_version == version_no,
                Candidate.status.in_(REVIEWABLE_STATUSES),
                (Candidate.value.is_not(None)) | (Candidate.withdrawn.is_(True)),
            )
            .distinct()
        )
    )


def publication_state(session: Session, catalog: Catalog, tender: Tender) -> PublicationState:
    versions = list(
        session.scalars(
            select(TenderVersion)
            .where(
                TenderVersion.tender_id == tender.id, TenderVersion.tenant_id == tender.tenant_id
            )
            .order_by(TenderVersion.version_no)
        )
    )
    current = versions[-1].version_no if versions else None
    reviewed = reviewed_version_of(session, tender)
    hold = standing_hold(session, tender)
    if hold is not None:
        # A takedown or a correction hold suspends publication whatever the review state;
        # the "version" a reader is pointed at is the hold itself.
        return PublicationState(
            state="publication_suspended",
            reviewed_version=reviewed,
            current_version=current,
            unreviewed_version=UnreviewedVersion(
                version_no=current or 0,
                kind=f"hold:{hold.kind}",
                issued_on=hold.created_at.date(),
                document_ids=[],
            ),
            possibly_superseded=[],
            suspended_by=[f"hold:{hold.kind}"],
        )
    if reviewed is None:
        return PublicationState(
            state="not_published", reviewed_version=None, current_version=current
        )
    later = [v for v in versions if v.version_no > reviewed]
    if not later:
        return PublicationState(
            state="published", reviewed_version=reviewed, current_version=current
        )
    touched: set[str] = set()
    for version in later:
        touched |= fields_touched(session, tender, version.version_no)
    known = {field.path for field in catalog.get(tender.tender_type).fields}
    touched &= known
    critical = sorted(touched & CRITICAL_FIELDS)
    document_ids = list(
        session.scalars(
            select(TenderVersionDocument.document_id)
            .where(
                TenderVersionDocument.tenant_id == tender.tenant_id,
                TenderVersionDocument.tender_version_id.in_([v.id for v in later]),
            )
            .order_by(TenderVersionDocument.created_at)
        )
    )
    newest = later[-1]
    return PublicationState(
        state="publication_suspended" if critical else "update_pending",
        reviewed_version=reviewed,
        current_version=current,
        unreviewed_version=UnreviewedVersion(
            version_no=newest.version_no,
            kind=newest.kind,
            issued_on=newest.issued_on,
            document_ids=document_ids,
        ),
        possibly_superseded=sorted(touched),
        suspended_by=critical,
    )
