"""Corrections and takedown on a published tender (Stage 5D).

A correction case records a claim that a published field is wrong and queues the field
for re-review: it opens a review round for the reviewer who completed the last review,
scoped to the version that set the field (a round's scope is a version, so the round may
show that version's other fields too). Nothing here changes a value: the reviewer's new
approval, through the normal pipeline, is the only thing that can, and the change then
shows in the changelog with its date.

A hold (a takedown request, or a correction hold) suspends publication whatever the
review state (`tender.services.publication.standing_hold`); a takedown is also written to
docs/KNOWN-GAPS.md, as the master prompt asks, beside the audit row.

The rows live under the tender's tenant — the public library for library tenders — and
are written in the system scope on the claimant's behalf: no end-user principal writes
to `public`.
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import SYSTEM_TENANT, set_tenant
from core.services import audit
from core.services.identity import Principal
from tender.models import CorrectionCase, PublicationHold, Tender
from tender.models.library import CORRECTION_STATUSES, HOLD_KINDS
from tender.services.current_view import current_view
from tender.services.packs import Catalog
from tender.services.tokens import TokenService

ACTOR = "corrections"
KNOWN_GAPS = Path(__file__).resolve().parents[2] / "docs" / "KNOWN-GAPS.md"
TAKEDOWN_HEADER = "## Takedowns"
# One source of truth for the ledger: the header and every row follow this order.
TAKEDOWN_COLUMNS = ("Date", "Requested", "Tender", "Requested by", "Reason", "State")
TAKEDOWN_TABLE = "| " + " | ".join(TAKEDOWN_COLUMNS) + " |\n|" + " --- |" * len(TAKEDOWN_COLUMNS)


class CorrectionError(ValueError):
    """The request cannot be carried out as asked. The message is safe to show."""


def open_case(
    session: Session,
    catalog: Catalog,
    *,
    tender: Tender,
    field_path: str,
    claimed_error: str,
    reasoning: str,
    claimant: Principal | None,
    claimant_email: str | None = None,
) -> CorrectionCase:
    """Record the claim and queue the field for re-review. Never changes a value."""
    known = {field.path for field in catalog.get(tender.tender_type).fields}
    if field_path not in known:
        raise CorrectionError(f"{field_path!r} is not a field of a {tender.tender_type} tender")
    if not claimed_error.strip() or not reasoning.strip():
        raise CorrectionError("a correction needs the claimed error and the reasoning")
    if claimant is None and not (claimant_email or "").strip():
        raise CorrectionError("a correction from the public form needs an email address")
    set_tenant(session, SYSTEM_TENANT)
    case = CorrectionCase(
        tenant_id=tender.tenant_id,
        created_by=claimant.name if claimant and claimant.name else ACTOR,
        tender_id=tender.id,
        field_path=field_path,
        claimed_error=claimed_error.strip(),
        reasoning=reasoning.strip(),
        claimant_tenant_id=claimant.tenant_id if claimant else None,
        claimant_user_id=claimant.user_id if claimant else None,
        claimant_email=(claimant_email or "").strip().lower() or None,
        status="open",
    )
    session.add(case)
    session.flush()
    # The round: scoped to the version that set the field; without a completed review
    # there is nothing to re-review and the case waits for the first review.
    view = current_view(session, catalog, tender)
    field = next((f for f in view.fields if f.field_path == field_path), None)
    from_version = field.version_no if field and field.version_no else 1
    token = TokenService(tender.tenant_id).open_round(
        session, tender, from_version=from_version, created_by=ACTOR
    )
    note = (
        f"round {token.round_no} opened for {token.reviewer_name} from version {from_version}"
        if token
        else "no round opened: the tender has no completed review, or a review is open"
    )
    if token is not None:
        tender.status = "in_review"
    audit.record(
        session,
        tenant_id=tender.tenant_id,
        actor=case.created_by,
        action="insert",
        table_name="correction_case",
        row_id=case.id,
        after={
            "tender_id": tender.id,
            "field_path": field_path,
            "claimant_tenant_id": case.claimant_tenant_id,
            "claimant_email": case.claimant_email,
            "round": note,
        },
    )
    case.resolution = None if token else note
    session.commit()
    return case


def resolve_case(
    session: Session, case: CorrectionCase, *, accepted: bool, resolution: str, by: str
) -> CorrectionCase:
    """Close the case. Accepting it records that the reviewer agreed; the value itself
    changed, if it did, through the reviewer's approval."""
    if case.status not in CORRECTION_STATUSES or case.status != "open":
        raise CorrectionError("the case is already resolved")
    set_tenant(session, SYSTEM_TENANT)
    before = {"status": case.status}
    case.status = "accepted" if accepted else "rejected"
    case.resolution = resolution.strip()
    case.resolved_by = by
    case.resolved_at = datetime.now(UTC)
    audit.record(
        session,
        tenant_id=case.tenant_id,
        actor=by,
        action="resolve",
        table_name="correction_case",
        row_id=case.id,
        before=before,
        after={"status": case.status, "resolution": case.resolution},
    )
    session.commit()
    return case


def cases(
    session: Session, tenants: tuple[str, ...], *, status: str | None = None
) -> list[CorrectionCase]:
    query = select(CorrectionCase).where(CorrectionCase.tenant_id.in_(list(tenants)))
    if status:
        query = query.where(CorrectionCase.status == status)
    return list(session.scalars(query.order_by(CorrectionCase.created_at)))


def place_hold(
    session: Session,
    *,
    tender: Tender,
    kind: str,
    reason: str,
    requested_by: str,
    requested_at: datetime | None = None,
    known_gaps: Path | None = None,
) -> PublicationHold:
    """Suspend publication. `requested_at` is when the request arrived, as the operator
    states it (the hold's own created_at is when it was placed). A takedown is also
    written to docs/KNOWN-GAPS.md."""
    if kind not in HOLD_KINDS:
        raise CorrectionError(f"unknown hold kind {kind!r}; one of {list(HOLD_KINDS)}")
    if not reason.strip():
        raise CorrectionError("a hold needs a reason")
    set_tenant(session, SYSTEM_TENANT)
    hold = PublicationHold(
        tenant_id=tender.tenant_id,
        created_by=requested_by,
        tender_id=tender.id,
        kind=kind,
        reason=reason.strip(),
        requested_by=requested_by,
        requested_at=requested_at,
    )
    session.add(hold)
    session.flush()
    audit.record(
        session,
        tenant_id=tender.tenant_id,
        actor=requested_by,
        action="insert",
        table_name="publication_hold",
        row_id=hold.id,
        after={
            "tender_id": tender.id,
            "kind": kind,
            "reason": hold.reason,
            "requested_at": requested_at.isoformat() if requested_at else None,
        },
    )
    session.commit()
    if kind == "takedown":
        append_takedown_row(
            known_gaps or KNOWN_GAPS,
            when=hold.created_at or datetime.now(UTC),
            requested=requested_at,
            tender=tender.slug or tender.id,
            requested_by=requested_by,
            reason=hold.reason,
            state="suspended",
        )
    return hold


def lift_hold(
    session: Session, hold: PublicationHold, *, by: str, known_gaps: Path | None = None
) -> PublicationHold:
    if hold.lifted_at is not None:
        raise CorrectionError("the hold is already lifted")
    set_tenant(session, SYSTEM_TENANT)
    hold.lifted_at = datetime.now(UTC)
    hold.lifted_by = by
    audit.record(
        session,
        tenant_id=hold.tenant_id,
        actor=by,
        action="lift",
        table_name="publication_hold",
        row_id=hold.id,
        before={"lifted_at": None},
        after={"lifted_at": hold.lifted_at.isoformat()},
    )
    session.commit()
    if hold.kind == "takedown":
        append_takedown_row(
            known_gaps or KNOWN_GAPS,
            when=hold.lifted_at,
            requested=hold.requested_at,
            tender=hold.tender_id,
            requested_by=by,
            reason=f"lifted: {hold.reason}",
            state="lifted",
        )
    return hold


def _cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def append_takedown_row(
    path: Path,
    *,
    when: datetime,
    tender: str,
    requested_by: str,
    reason: str,
    state: str,
    requested: datetime | None = None,
) -> None:
    """One row under "## Takedowns" in docs/KNOWN-GAPS.md, the table made on first use."""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if TAKEDOWN_HEADER not in text:
        text = text.rstrip("\n") + f"\n\n{TAKEDOWN_HEADER}\n\n{TAKEDOWN_TABLE}\n"
    cells = {
        "Date": when.date().isoformat(),
        "Requested": requested.date().isoformat() if requested else "",
        "Tender": _cell(tender),
        "Requested by": _cell(requested_by),
        "Reason": _cell(reason),
        "State": _cell(state),
    }
    row = "| " + " | ".join(cells[column] for column in TAKEDOWN_COLUMNS) + " |\n"
    path.write_text(text.rstrip("\n") + "\n" + row, encoding="utf-8")
