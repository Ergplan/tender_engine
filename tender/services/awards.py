"""Awards (Stage 6): a result publication as a reviewed object beside the tenders.

An award is one source publication of the RE-tender-results dataset: a result sheet, a
CERC adoption order, an allocation. Its fields are candidates the importer wrote
(`tender.services.results_import`), reviewed through core's review state and the one
approval route, and canonical only when the reviewer approves them. This module is the
award's view for the reviewer screen, the completion of its review, and the canonical
results a reader (or a tender) sees: approved rows and nothing else.
"""

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Candidate, Document, EvidenceSpan, ExtractionRun
from core.services import audit
from core.services.approve import ApprovalError, ApprovalService
from core.services.review_state import ReviewStateService
from tender.models import Award, ReviewToken
from tender.services.packs import Catalog
from tender.services.review import (
    VALUE_DECISIONS,
    ReviewDocument,
    ReviewEntry,
    ReviewField,
    ReviewSection,
    ReviewVersion,
)

OBJECT_TYPE = "award"
AWARD_TYPE = "award"
FIELDS = {
    name: f"result.award.{name}"
    for name in ("procurer", "reference", "result_kind", "result_date", "winners")
}


class AwardError(ValueError):
    """A request about an award that cannot be met."""


class AwardReview(BaseModel):
    """The award as the reviewer sees it: the same field list the tender screen reads,
    over the one version an award has (the publication itself)."""

    award_id: str
    object_type: str = OBJECT_TYPE
    title: str
    procurer: str
    reference: str
    result_kind: str
    status: str
    document_id: str
    source_url: str
    source_sha256: str
    dataset: str
    verification: str
    tender_id: str | None
    tender_link_basis: str | None
    tender_link_page: int | None
    versions: list[ReviewVersion]
    sections: list[ReviewSection]
    fields: list[ReviewField]
    decided: int
    total: int
    required_undecided: int
    can_complete: bool


class AwardResults(BaseModel):
    """What a reader may see of an award: its canonical facts, approved by a reviewer,
    and nothing from the dataset that was not. An award without an approved winners
    table has no rows."""

    award_id: str
    document_id: str
    source_url: str
    source_sha256: str
    dataset: str
    status: str
    tender_id: str | None
    tender_link_basis: str | None
    tender_link_page: int | None
    procurer: str | None
    reference: str | None
    result_kind: str | None
    result_date: str | None
    rows: list[dict[str, Any]]
    # The pages the approved rows' evidence sits on, for a reader who opens the file.
    evidence_pages: list[int]
    reviewed: bool
    authority_note: str = (
        "The source publication is the authoritative record; every value shown was approved "
        "by a reviewer against it."
    )


class TenderAwards(BaseModel):
    tender_id: str
    awards: list[AwardResults]


class AwardService:
    def __init__(self, catalog: Catalog, tenant_id: str) -> None:
        self._catalog = catalog
        self._tenant_id = tenant_id

    def get(self, session: Session, award_id: str) -> Award:
        award = session.scalar(
            select(Award).where(Award.id == award_id, Award.tenant_id == self._tenant_id)
        )
        if award is None:
            raise LookupError(f"award {award_id} not found")
        return award

    def by_source(self, session: Session, source: str) -> Award | None:
        """An award by its dataset source id or its source file's sha256."""
        return session.scalar(
            select(Award).where(
                Award.tenant_id == self._tenant_id,
                (Award.source_id == source)
                | (Award.source_sha256 == source)
                | (Award.id == source),
            )
        )

    def all(self, session: Session, *, tender_id: str | None = None) -> list[Award]:
        query = select(Award).where(Award.tenant_id == self._tenant_id)
        if tender_id is not None:
            query = query.where(Award.tender_id == tender_id)
        return list(session.scalars(query.order_by(Award.procurer, Award.reference, Award.id)))

    def review(
        self, session: Session, review_state: ReviewStateService, award: Award
    ) -> AwardReview:
        """The award for the reviewer screen: every field of the result schema with its
        candidate, evidence, validation and decision, as one entry of version 1."""
        compiled = self._catalog.get(AWARD_TYPE)
        state = review_state.for_object(session, OBJECT_TYPE, award.id, 1)
        by_path = {field.field_path: field for field in state.fields}
        fields: list[ReviewField] = []
        for field in compiled.fields:
            own = by_path.get(field.path)
            entries = (
                [ReviewEntry(version_no=1, version_kind="original", state=own)]
                if own is not None and (own.candidate is not None or own.approval is not None)
                else []
            )
            approval = own.approval if own is not None and entries else None
            fields.append(
                ReviewField(
                    field_path=field.path,
                    label=field.label,
                    section=field.section,
                    value_type=field.value_type,
                    unit=field.unit,
                    required=field.required,
                    help_text=field.help_text,
                    enum_values=field.enum_values,
                    keys=field.keys,
                    review_order=field.review_order,
                    entries=entries,
                    current=0 if entries else None,
                    decided=approval is not None
                    and approval.decision in (*VALUE_DECISIONS, "not_in_document"),
                    flagged=approval is not None and approval.decision == "flagged",
                )
            )
        # A required field of an award always has an entry (the importer writes every
        # field); should one lack it, it still holds the review back.
        required_undecided = sum(1 for f in fields if f.required and not f.decided)
        source = session.scalar(
            select(Document).where(
                Document.id == award.document_id, Document.tenant_id == self._tenant_id
            )
        )
        return AwardReview(
            award_id=award.id,
            title=award.source_name,
            procurer=award.procurer,
            reference=award.reference,
            result_kind=award.result_kind,
            status=award.status,
            document_id=award.document_id,
            source_url=award.source_url,
            source_sha256=award.source_sha256,
            dataset=award.dataset,
            verification=award.verification,
            tender_id=award.tender_id,
            tender_link_basis=award.tender_link_basis,
            tender_link_page=award.tender_link_page,
            versions=[
                ReviewVersion(
                    version_no=1,
                    kind="original",
                    issued_on=None,
                    documents=[
                        ReviewDocument(
                            document_id=award.document_id,
                            role="result",
                            filename=source.filename if source else award.source_name,
                            page_count=source.page_count if source else None,
                        )
                    ],
                )
            ],
            sections=[
                ReviewSection(name=section.name, label=section.label, order=section.order)
                for section in sorted(compiled.sections, key=lambda s: s.order)
            ],
            fields=fields,
            decided=sum(1 for f in fields if f.decided),
            total=len(fields),
            required_undecided=required_undecided,
            can_complete=required_undecided == 0 and any(f.decided for f in fields),
        )

    def complete_review(
        self,
        session: Session,
        review_state: ReviewStateService,
        award: Award,
        token: ReviewToken,
    ) -> Award:
        """Close the award's review: refused while a required field is undecided; then the
        token is completed and the award marked reviewed. No canonical fact is written
        here; the approvals already made are the award's facts."""
        if (token.object_type, token.object_id) != (OBJECT_TYPE, award.id):
            raise LookupError("the review token belongs to another object")
        if token.completed_at is not None:
            raise AwardError("this review has already been completed")
        review = self.review(session, review_state, award)
        if not review.can_complete:
            raise AwardError(
                f"{review.required_undecided} required field(s) have no decision yet"
                if review.required_undecided
                else "no field has been decided yet"
            )
        now = datetime.now(UTC)
        token.completed_at = now
        before = award.status
        award.status = "reviewed"
        session.flush()
        audit.record(
            session,
            tenant_id=award.tenant_id,
            actor=token.reviewer_name,
            action="complete_review",
            table_name="award",
            row_id=award.id,
            before={"status": before},
            after={
                "status": "reviewed",
                "review_token_id": token.id,
                "decided": review.decided,
                "total": review.total,
            },
        )
        session.commit()
        return award

    def results(
        self, session: Session, review_state: ReviewStateService, award: Award
    ) -> AwardResults:
        """The award's canonical facts and nothing else."""
        facts = {
            fact.field_path: fact for fact in review_state.canonical(session, OBJECT_TYPE, award.id)
        }

        def value(name: str) -> Any:
            fact = facts.get(FIELDS[name])
            return None if fact is None else fact.value

        winners = facts.get(FIELDS["winners"])
        rows = (
            list(winners.value) if winners is not None and isinstance(winners.value, list) else []
        )
        pages = sorted(
            {
                int(span["page_no"])
                for fact in facts.values()
                for span in fact.evidence
                if isinstance(span, dict) and span.get("page_no") is not None
            }
        )
        return AwardResults(
            award_id=award.id,
            document_id=award.document_id,
            source_url=award.source_url,
            source_sha256=award.source_sha256,
            dataset=award.dataset,
            status=award.status,
            tender_id=award.tender_id,
            tender_link_basis=award.tender_link_basis,
            tender_link_page=award.tender_link_page,
            procurer=value("procurer"),
            reference=value("reference"),
            result_kind=value("result_kind"),
            result_date=value("result_date"),
            rows=rows,
            evidence_pages=pages,
            reviewed=award.status == "reviewed",
        )

    def tender_awards(
        self, session: Session, review_state: ReviewStateService, tender_id: str
    ) -> TenderAwards:
        """The awards linked to a tender, each with its approved rows only."""
        return TenderAwards(
            tender_id=tender_id,
            awards=[
                self.results(session, review_state, award)
                for award in self.all(session, tender_id=tender_id)
            ],
        )


class AwardRowsGuard:
    """No row of an award table becomes canonical without located evidence (the
    invariant, row by row). The importer stores each row's quotes with the row's number
    as their ordinal; a row whose bidder or number was not found on the page is unlocated.
    Approving such a table as it stands is refused. On an edit, every row of the final
    table must either be a located row of the candidate kept exactly as it was (every key),
    or be vouched for by the reviewer's quotes: the quotes holding the row's bidder are the
    row's own, and every number the row carries (capacity, price, adopted capacity, adopted
    price) must be printed whole in one of those; the approval service then locates each
    quote on the page like any reviewer evidence. A row the reviewer renames, corrects or
    adds is such a row. Other decisions (not in document, rejected, flagged, cleared) are
    unaffected."""

    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    def before(
        self, session: Session, candidate: Candidate, run: ExtractionRun, decision: str
    ) -> None:
        return None

    def after(
        self, session: Session, service: ApprovalService, approval: Any, run: ExtractionRun
    ) -> None:
        return None

    def check(
        self,
        session: Session,
        candidate: Candidate,
        run: ExtractionRun,
        decision: str,
        final_value: Any,
        evidence: list[dict[str, Any]] | None,
    ) -> None:
        if run.object_type != OBJECT_TYPE or candidate.field_path != FIELDS["winners"]:
            return
        if decision not in ("approved", "edited") or not isinstance(candidate.value, list):
            return
        located: dict[int, bool] = {}
        for ordinal, char_start in session.execute(
            select(EvidenceSpan.ordinal, EvidenceSpan.char_start).where(
                EvidenceSpan.candidate_id == candidate.id,
                EvidenceSpan.tenant_id == self._tenant_id,
            )
        ):
            if ordinal is not None:
                located[ordinal] = located.get(ordinal, True) and char_start is not None
        rows = [row for row in candidate.value if isinstance(row, dict)]
        if decision == "approved":
            unlocated = [
                _row_name(row, index)
                for index, row in enumerate(rows, start=1)
                if not located.get(index, False)
            ]
            if unlocated:
                raise ApprovalError(
                    f"{len(unlocated)} row(s) were not found on the page "
                    f"({', '.join(unlocated)}): edit the table, dropping those rows or giving "
                    "the page and words of each"
                )
            return
        kept_as_was = [
            _row_key(row) for index, row in enumerate(rows, start=1) if located.get(index, False)
        ]
        final_rows = (
            [row for row in final_value if isinstance(row, dict)]
            if isinstance(final_value, list)
            else []
        )
        # The same words given twice are one printed occurrence.
        quotes = list(dict.fromkeys(_flat(str(item.get("quote", ""))) for item in (evidence or [])))
        bidders = {
            _flat(str(row.get("bidder") or "")) for row in [*rows, *final_rows] if row.get("bidder")
        }
        uncovered = [
            _row_name(row, index)
            for index, row in enumerate(final_rows, start=1)
            if _row_key(row) not in kept_as_was and not _covered(row, quotes, bidders)
        ]
        if uncovered:
            raise ApprovalError(
                f"{len(uncovered)} row(s) of the edited table are not located rows of the "
                f"import kept as they were ({', '.join(uncovered)}): give the page and words "
                "that state each one's bidder and every number it carries, or drop the row"
            )


def _flat(text: str) -> str:
    return " ".join(text.lower().split())


NUMBER_KEYS = ("capacity", "price", "adopted_capacity", "adopted_price")
_NUMBER_IN_TEXT = re.compile(r"(?<![\d.,])\d[\d,]*(?:\.\d+)?(?![\d.])")
# A unit printed right after a number says which quantity it is: a capacity (MW, kW, MWh,
# MT) or a price (INR, Rs, ₹, per kWh, per kg, paise). Without one, the table's header
# carries the unit and the number is taken as the reviewer assigns it.
_CAPACITY_UNIT = re.compile(r"^\s*(mw|kw|mwh|kwh|mt|mtpa|tonne|tons?)\b")
_PRICE_UNIT = re.compile(r"^\s*(inr|rs\.?|₹|rupees?|paise|/\s*k(wh|g)|per\s+k(wh|g)|/\s*mw)")
QUANTITY_OF_KEY = {
    "capacity": "capacity",
    "adopted_capacity": "capacity",
    "price": "price",
    "adopted_price": "price",
}


def _row_key(row: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Every key of the row, normalised without loss, so that any change to any value is
    a change."""

    def normal(value: Any) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            return ""
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, int | float):
            return repr(float(value))
        try:
            return repr(float(str(value).replace(",", "")))
        except ValueError:
            return _flat(str(value))

    return tuple(sorted((str(key), normal(value)) for key, value in row.items()))


def _row_name(row: dict[str, Any], index: int) -> str:
    return str(row.get("bidder") or f"row {index}")


def _numbers_in(quote: str) -> list[tuple[float, str | None]]:
    """Every number printed in the quote, once per occurrence, with the quantity its
    trailing unit names (capacity, price) or None when no unit follows it."""
    found: list[tuple[float, str | None]] = []
    for match in _NUMBER_IN_TEXT.finditer(quote):
        try:
            number = float(match.group(0).replace(",", ""))
        except ValueError:
            continue
        after = quote[match.end() : match.end() + 12]
        kind = (
            "capacity"
            if _CAPACITY_UNIT.match(after)
            else "price"
            if _PRICE_UNIT.match(after)
            else None
        )
        found.append((number, kind))
    return found


def _distinct_places(stretches: list[str]) -> list[str]:
    """One stretch per place on the page: every own stretch starts right after the row's
    bidder, so two that begin alike are the same words quoted at two lengths, and only the
    longest counts (a quote that repeats part of another adds no printed occurrence)."""
    kept: list[str] = []
    for stretch in sorted(stretches, key=len, reverse=True):
        first = _numbers_in(stretch)[:1]
        same_place = any(
            other.startswith(stretch) or (first and _numbers_in(other)[:1] == first)
            for other in kept
        )
        if not same_place:
            kept.append(stretch)
    return kept


def _covered(row: dict[str, Any], quotes: list[str], bidders: set[str] | None = None) -> bool:
    """The reviewer's quotes state the row: the quotes that hold the row's bidder are the
    row's own, read from its bidder up to the next bidder of the table (so a quote that
    runs over two rows lends the second row's figures to nobody), and the numbers the row
    carries (capacity, price, adopted capacity, adopted price) must each be printed whole
    in that stretch, one printed occurrence per number, a unit printed after a number
    naming its quantity (4 MW does not cover a price of 4, 6.95 INR/kWh not a capacity of
    6.95; 2.45 does not cover 2.4, 200 not 20; one printed 2.41 does not cover a capacity
    and a price of 2.41). A number printed without a unit (a table cell under its header)
    counts for the quantity the reviewer assigns it. The row's categorical keys
    (allocation, units, status, notes) are the reviewer's reading of the page, not words
    the page prints, and are not quoted."""
    bidder = _flat(str(row.get("bidder") or ""))
    if not bidder:
        return False
    others = {other for other in (bidders or set()) if other and other != bidder}
    own: list[str] = []
    for quote in quotes:
        start = quote.find(bidder)
        if start < 0:
            continue
        stretch = quote[start + len(bidder) :]
        cut = min(
            (position for position in (stretch.find(other) for other in others) if position >= 0),
            default=len(stretch),
        )
        own.append(stretch[:cut])
    if not own:
        return False
    wanted: list[tuple[float, str]] = []
    for key in NUMBER_KEYS:
        value = row.get(key)
        if value is None or str(value).strip() == "":
            continue
        try:
            wanted.append((float(str(value).replace(",", "")), QUANTITY_OF_KEY[key]))
        except ValueError:
            return False
    # The row's figures are the first numbers after its bidder, as many as the row carries:
    # a stretch that runs on past them (into another row the table does not list) lends
    # nothing.
    printed = [item for quote in _distinct_places(own) for item in _numbers_in(quote)][
        : len(wanted)
    ]
    # Each wanted number takes one printed occurrence of itself whose unit, if any, is its
    # quantity; the typed occurrences are taken first so an untyped one is left for a
    # number of another quantity.
    for number, quantity in wanted:
        candidates = [
            index
            for index, (printed_number, kind) in enumerate(printed)
            if printed_number == number and kind in (None, quantity)
        ]
        if not candidates:
            return False
        chosen = min(candidates, key=lambda index: printed[index][1] is None)
        printed.pop(chosen)
    return True
