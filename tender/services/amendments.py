"""The amendments of a tender as a reviewer checks them: per later version, what it
changed against what stood before, with that version's reading to decide.

A projection of the review (`tender.services.review.tender_review`): a change is a field
a later version states (or that was decided on it). Nothing here is written; a decision on
an amendment's reading goes through `POST /approvals` like any other, and setting it aside
as "not in document" brings the earlier reading back (`tender_review._current`).
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import ExtractionRun
from core.models.extraction import RECORD_MODES
from core.schemas import KeyDef, SchemaRegistry
from core.services.review_state import ReviewStateService
from tender.models import Tender
from tender.services.derive import derived_rules
from tender.services.packs import Catalog
from tender.services.review import ReviewDocument, ReviewEntry, TenderReview, tender_review
from tender.services.summary import SUMMARY_FIELD
from tender.services.tenders import OBJECT_TYPE, TenderService

# removed: the version withdraws the provision (a `withdrawn` reading); what stood before is
# shown as the value it removes.
ChangeKind = Literal["added", "changed", "restated", "removed"]
DECIDED = ("approved", "edited", "not_in_document")


class ChangeBefore(BaseModel):
    """What stood for the field before this version: the latest earlier reading, as the
    reviewer left it (their edit if they made one)."""

    version_no: int
    version_kind: str
    value: Any
    decision: str | None


class AmendmentChange(BaseModel):
    field_path: str
    label: str
    section: str
    section_label: str
    value_type: str
    unit: str | None
    required: bool
    help_text: str
    enum_values: list[str] | None
    keys: list[KeyDef] | None = None
    # added: nothing stood before; changed: the value differs; restated: the same value.
    kind: ChangeKind
    before: ChangeBefore | None
    # This version's reading, with its candidate, evidence and decision.
    entry: ReviewEntry
    # Whether this reading is the one the review decides the field on.
    is_current: bool
    decided: bool
    set_aside: bool
    flagged: bool
    # Impact cues. `changes_decided`: what stood before is a reviewer's decision (approved
    # or edited), so this reading, once decided, replaces a canonical value. `impacts`: the
    # derived tables whose rules read this field (their labels), written again from it.
    changes_decided: bool = False
    impacts: list[str] = []


class AmendmentVersion(BaseModel):
    version_no: int
    kind: str
    issued_on: date | None
    summary_of_change: str | None
    documents: list[ReviewDocument]
    # The sections its documents were read for (the routing's union).
    sections_read: list[str]
    changes: list[AmendmentChange]
    added: int
    changed: int
    restated: int
    removed: int = 0
    decided: int
    undecided: int


class TenderAmendments(BaseModel):
    tender_id: str
    title: str
    versions: list[AmendmentVersion]
    # Fields no later version touches: they stand as the original states them.
    untouched: int


def tender_amendments(
    session: Session,
    catalog: Catalog,
    tenders: TenderService,
    review_state: ReviewStateService,
    schemas: SchemaRegistry,
    tender: Tender,
    review: TenderReview | None = None,
) -> TenderAmendments:
    compiled = catalog.get(tender.tender_type)
    review = review or tender_review(session, catalog, tenders, review_state, tender)
    labels = {section.name: section.label for section in compiled.sections}
    # The summary is written from the record, and a derived table from decisions: neither
    # is something an amendment states.
    derived = {section.name for section in compiled.sections if section.derived}
    defs = {item.path: item for item in compiled.schema.fields}
    # Per field, the derived tables whose rules read it.
    read_by: dict[str, list[str]] = {}
    for rule in derived_rules(compiled):
        table = next(
            (f.label for f in compiled.fields if f.path == rule.field_path), rule.field_path
        )
        for path in rule.inputs:
            read_by.setdefault(path, []).append(table)

    def comparable(path: str, value: Any) -> Any:
        try:
            return schemas.value_types.coerce(value, defs[path])
        except (ValueError, KeyError):
            return value

    versions = [
        entry.version for entry in tenders.versions(session, tender) if entry.version.version_no > 1
    ]
    by_number = {version.version_no: version for version in versions}
    changes: dict[int, list[AmendmentChange]] = {number: [] for number in by_number}
    untouched = 0
    for field in review.fields:
        if field.field_path == SUMMARY_FIELD or field.section in derived:
            continue
        if not any(entry.version_no > 1 for entry in field.entries):
            untouched += 1
            continue
        for index, entry in enumerate(field.entries):
            if entry.version_no == 1 or entry.version_no not in changes:
                continue
            before = _before(field.entries[:index])
            after = _value_of(entry)
            candidate = entry.state.candidate
            if candidate is not None and candidate.withdrawn and after is None:
                # The version removes the provision: what stood before no longer applies.
                kind: ChangeKind = "removed"
            elif before is None or before.value is None:
                kind = "added"
            elif comparable(field.field_path, before.value) == comparable(field.field_path, after):
                kind = "restated"
            else:
                kind = "changed"
            decision = entry.state.approval.decision if entry.state.approval else None
            changes[entry.version_no].append(
                AmendmentChange(
                    field_path=field.field_path,
                    label=field.label,
                    section=field.section,
                    section_label=labels.get(field.section, field.section),
                    value_type=field.value_type,
                    unit=field.unit,
                    required=field.required,
                    help_text=field.help_text,
                    enum_values=field.enum_values,
                    keys=field.keys,
                    kind=kind,
                    before=before,
                    entry=entry,
                    is_current=field.current == index,
                    decided=decision in DECIDED,
                    set_aside=decision == "not_in_document",
                    flagged=decision == "flagged",
                    changes_decided=before is not None
                    and before.decision in ("approved", "edited"),
                    impacts=read_by.get(field.field_path, []),
                )
            )
    sections_read = _sections_read(session, tender)
    documents = {version.version_no: version.documents for version in review.versions}
    return TenderAmendments(
        tender_id=tender.id,
        title=tender.title,
        versions=[
            AmendmentVersion(
                version_no=version.version_no,
                kind=version.kind,
                issued_on=version.issued_on,
                summary_of_change=version.summary_of_change,
                documents=documents.get(version.version_no, []),
                sections_read=sections_read.get(version.version_no, []),
                changes=own,
                added=sum(1 for c in own if c.kind == "added"),
                changed=sum(1 for c in own if c.kind == "changed"),
                restated=sum(1 for c in own if c.kind == "restated"),
                removed=sum(1 for c in own if c.kind == "removed"),
                decided=sum(1 for c in own if c.decided),
                undecided=sum(1 for c in own if not c.decided),
            )
            for version in versions
            for own in [changes[version.version_no]]
        ],
        untouched=untouched,
    )


def _value_of(entry: ReviewEntry) -> Any:
    """The reading as the reviewer left it: their edit, else the model's value."""
    approval = entry.state.approval
    if approval is not None and approval.decision == "edited":
        return approval.final_value
    candidate = entry.state.candidate
    return candidate.value if candidate is not None else None


def _before(earlier: list[ReviewEntry]) -> ChangeBefore | None:
    """What stood before this version's reading: the latest earlier reading the reviewer
    did not set aside. One set aside as not in its document never stood, so the reading
    before it is what this version changes; none left, nothing stood before."""
    for entry in reversed(earlier):
        approval = entry.state.approval
        if approval is not None and approval.decision == "not_in_document":
            continue
        return ChangeBefore(
            version_no=entry.version_no,
            version_kind=entry.version_kind,
            value=_value_of(entry),
            decision=approval.decision if approval else None,
        )
    return None


def _sections_read(session: Session, tender: Tender) -> dict[int, list[str]]:
    """Per version, the sections its page runs read (not the record or derived passes)."""
    read: dict[int, set[str]] = {}
    for version_no, groups in session.execute(
        select(ExtractionRun.object_version, ExtractionRun.groups).where(
            ExtractionRun.tenant_id == tender.tenant_id,
            ExtractionRun.object_type == OBJECT_TYPE,
            ExtractionRun.object_id == tender.id,
            ExtractionRun.mode.not_in(RECORD_MODES),
            ExtractionRun.status != "failed",
        )
    ):
        read.setdefault(version_no, set()).update(groups or [])
    return {number: sorted(groups) for number, groups in read.items()}
