"""Gold records: a completed review, written as YAML per tender.

A record is made by `make gold TENDER=<slug>` after the owner confirms the review is
trustworthy, never on completion itself. Per field it keeps the reviewer's final value and
decision, the evidence pages they accepted, and the candidate they judged.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Approval, Candidate, EvidenceSpan
from tender.models import Tender, TenderReviewSnapshot
from tender.services.packs import Catalog

GOLD_ROOT = Path(__file__).resolve().parent / "gold"
DECIDED = ("approved", "edited", "not_in_document")


class GoldCandidate(BaseModel):
    id: str
    value: Any
    confidence: float
    prompt_name: str
    prompt_version: str
    pages: list[int]


class GoldField(BaseModel):
    field_path: str
    section: str
    value_type: str
    required: bool
    decision: str | None
    final_value: Any
    version_no: int | None
    evidence_pages: list[int]
    reviewer: str | None
    decided_at: str | None
    note: str | None
    candidate: GoldCandidate | None


class GoldRecord(BaseModel):
    tenant_id: str
    tender_id: str
    slug: str
    tender_type: str
    issuing_agency: str
    title: str
    schema_version: str
    reviewed_version: int
    reviewer: str
    completed_at: str
    snapshot_id: str
    made_at: str
    fields: list[GoldField]

    def field(self, path: str) -> GoldField | None:
        return next((f for f in self.fields if f.field_path == path), None)


class NoCompletedReview(LookupError):
    pass


def tender_key(tender: Tender) -> str:
    """The slug names the gold file; a tender without one is named by its id."""
    return tender.slug or tender.id


def build_gold(session: Session, catalog: Catalog, tender: Tender) -> GoldRecord:
    """The gold record of a tender from its latest completed-review snapshot."""
    snapshot = session.scalar(
        select(TenderReviewSnapshot)
        .where(
            TenderReviewSnapshot.tender_id == tender.id,
            TenderReviewSnapshot.tenant_id == tender.tenant_id,
        )
        .order_by(TenderReviewSnapshot.created_at.desc())
        .limit(1)
    )
    if snapshot is None:
        raise NoCompletedReview(f"{tender_key(tender)}: no completed review; complete it first")
    compiled = catalog.get(tender.tender_type)
    view = snapshot.snapshot["view"]
    reviewed_version = int(view.get("current_version_no") or 1)
    # The decisions that stand up to the version the review was completed at: per field the
    # decision of the version the snapshot shows it from (a field an amendment did not touch
    # keeps the decision made on the earlier version). A decision on a later version is not
    # part of this record.
    view_by_path = {f["field_path"]: f for f in view["fields"]}
    standing: dict[tuple[str, int], Approval] = {
        (a.field_path, a.object_version): a
        for a in session.scalars(
            select(Approval).where(
                Approval.tenant_id == tender.tenant_id,
                Approval.object_type == "tender",
                Approval.object_id == tender.id,
                Approval.object_version <= reviewed_version,
                Approval.status == "active",
            )
        )
    }
    approvals: dict[str, Approval] = {}
    for path, version in standing:
        shown_version = (view_by_path.get(path) or {}).get("version_no")
        wanted = shown_version if shown_version is not None else reviewed_version
        if version == wanted:
            approvals[path] = standing[(path, version)]
    for path, version in standing:
        # A field the view does not date (no value shown): its latest standing decision.
        # A field the view dates with no decision at that version is left undecided.
        undated = (view_by_path.get(path) or {}).get("version_no") is None
        if (
            path not in approvals
            and undated
            and all(v <= version for p, v in standing if p == path)
        ):
            approvals[path] = standing[(path, version)]
    candidate_ids = [a.candidate_id for a in approvals.values()]
    candidates = {
        c.id: c
        for c in session.scalars(
            select(Candidate).where(
                Candidate.tenant_id == tender.tenant_id, Candidate.id.in_(candidate_ids)
            )
        )
    }
    pages: dict[str, set[int]] = {cid: set() for cid in candidate_ids}
    for span in session.scalars(
        select(EvidenceSpan).where(
            EvidenceSpan.tenant_id == tender.tenant_id,
            EvidenceSpan.candidate_id.in_(candidate_ids),
        )
    ):
        pages[span.candidate_id].add(span.page_no)

    fields: list[GoldField] = []
    for field in compiled.fields:
        shown = view_by_path.get(field.path, {})
        approval = approvals.get(field.path)
        decided = approval if approval is not None and approval.decision in DECIDED else None
        decision = decided.decision if decided else None
        candidate = candidates.get(decided.candidate_id) if decided else None
        fields.append(
            GoldField(
                field_path=field.path,
                section=field.section,
                value_type=field.value_type,
                required=field.required,
                decision=decision,
                final_value=decided.final_value if decided else None,
                version_no=shown.get("version_no"),
                evidence_pages=sorted(
                    {int(e["page_no"]) for e in shown.get("evidence", []) if e.get("page_no")}
                ),
                reviewer=decided.reviewer if decided else None,
                decided_at=decided.decided_at.isoformat() if decided else None,
                note=decided.note if decided else None,
                candidate=None
                if candidate is None or decided is None
                else GoldCandidate(
                    id=candidate.id,
                    value=candidate.value,
                    confidence=candidate.confidence,
                    prompt_name=candidate.prompt_name,
                    prompt_version=candidate.prompt_version,
                    pages=sorted(pages.get(candidate.id, set())),
                ),
            )
        )
    return GoldRecord(
        tenant_id=tender.tenant_id,
        tender_id=tender.id,
        slug=tender_key(tender),
        tender_type=tender.tender_type,
        issuing_agency=tender.issuing_agency,
        title=tender.title,
        schema_version=compiled.schema.version,
        reviewed_version=reviewed_version,
        reviewer=snapshot.reviewer,
        completed_at=snapshot.snapshot["completed_at"],
        snapshot_id=snapshot.id,
        made_at=datetime.now(UTC).isoformat(timespec="seconds"),
        fields=fields,
    )


def gold_path(record: GoldRecord, root: Path | None = None) -> Path:
    return (root or GOLD_ROOT) / record.tender_type / f"{record.slug}.yaml"


def write_gold(record: GoldRecord, root: Path | None = None) -> Path:
    path = gold_path(record, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Gold record of {record.slug} ({record.tender_type}), reviewed by "
        f"{record.reviewer}, completed {record.completed_at}; written by make gold on "
        f"{record.made_at}. Never edited by hand.\n"
    )
    body = yaml.safe_dump(
        record.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=120
    )
    path.write_text(header + body, encoding="utf-8")
    return path


def load_gold(path: Path) -> GoldRecord:
    return GoldRecord.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_all(tenant_id: str | None = None, root: Path | None = None) -> list[GoldRecord]:
    """Every gold record, or those of one tenant."""
    records = [load_gold(path) for path in sorted((root or GOLD_ROOT).glob("*/*.yaml"))]
    return [r for r in records if tenant_id is None or r.tenant_id == tenant_id]
