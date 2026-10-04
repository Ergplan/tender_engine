"""Shared validators of the core pack: rules on fields every tender has. Plain Python."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Candidate, EvidenceSpan, ExtractionRun
from core.schemas import CandidateOutcome, CrossFieldRule, RuleOutcome, RunRule
from tender.models import TenderVersion, TenderVersionDocument

DATE_CHAIN = (
    ("core.key_dates.nit_date", "date of issue"),
    ("core.key_dates.pre_bid_meeting_date", "pre-bid meeting"),
    ("core.key_dates.query_deadline", "last date for queries"),
    ("core.key_dates.bid_submission_deadline", "bid submission deadline"),
    ("core.key_dates.technical_opening_date", "technical bid opening"),
)
EMD = "core.guarantees.emd_per_mw_inr"
PBG = "core.guarantees.pbg_per_mw_inr"


def date_order(values: dict[str, Any]) -> list[RuleOutcome]:
    """Issue <= pre-bid <= queries <= bid deadline <= technical opening, for the dates
    that have a value. Each neighbouring pair is one outcome."""
    present = [(path, label, values[path]) for path, label in DATE_CHAIN if path in values]
    outcomes = []
    for (path_a, label_a, a), (path_b, label_b, b) in zip(present, present[1:], strict=False):
        if a <= b:
            message = f"{label_a} ({a}) is not after {label_b} ({b})"
        else:
            message = f"{label_a} ({a}) is after {label_b} ({b})"
        outcomes.append(RuleOutcome((path_a, path_b), a <= b, message))
    return outcomes


def emd_pbg_within_10x(values: dict[str, Any]) -> list[RuleOutcome]:
    """EMD and PBG per MW are positive and within ten times of each other."""
    emd, pbg = values.get(EMD), values.get(PBG)
    if emd is None or pbg is None:
        return []
    if emd <= 0 or pbg <= 0:
        return [RuleOutcome((EMD, PBG), False, "EMD and PBG per MW must be positive")]
    ratio = max(emd, pbg) / min(emd, pbg)
    if ratio <= 10:
        return [RuleOutcome((EMD, PBG), True, "EMD and PBG per MW are within 10x of each other")]
    message = f"EMD per MW ({emd:g}) and PBG per MW ({pbg:g}) differ by more than 10x"
    return [RuleOutcome((EMD, PBG), False, message)]


def later_version_evidence(
    session: Session, run: ExtractionRun, candidates: Sequence[Candidate]
) -> list[CandidateOutcome]:
    """Corrigendum rule: a value produced for a later version of a tender must carry
    evidence from a document of that version, not from the original."""
    if run.object_type != "tender" or run.object_version <= 1 or not candidates:
        return []
    own_documents = set(
        session.scalars(
            select(TenderVersionDocument.document_id)
            .join(TenderVersion, TenderVersionDocument.tender_version_id == TenderVersion.id)
            .where(
                TenderVersion.tender_id == run.object_id,
                TenderVersion.version_no == run.object_version,
                TenderVersion.tenant_id == run.tenant_id,
                TenderVersionDocument.tenant_id == run.tenant_id,
            )
        )
    )
    located: dict[str, list[str]] = {candidate.id: [] for candidate in candidates}
    for candidate_id, document_id in session.execute(
        select(EvidenceSpan.candidate_id, EvidenceSpan.document_id).where(
            EvidenceSpan.candidate_id.in_(list(located)),
            EvidenceSpan.tenant_id == run.tenant_id,
            EvidenceSpan.char_start.is_not(None),
        )
    ):
        located[candidate_id].append(document_id)
    outcomes = []
    for candidate in candidates:
        documents = located[candidate.id]
        if not documents:
            continue
        if all(document_id in own_documents for document_id in documents):
            message = f"evidence comes from a document of version {run.object_version}"
            outcomes.append(CandidateOutcome(candidate.id, True, message))
        else:
            message = (
                f"a value for version {run.object_version} must carry evidence from that "
                "version's own document"
            )
            outcomes.append(CandidateOutcome(candidate.id, False, message))
    return outcomes


CROSS_FIELD_RULES: dict[str, CrossFieldRule] = {
    "date_order": date_order,
    "emd_pbg_within_10x": emd_pbg_within_10x,
}
RUN_RULES: dict[str, RunRule] = {"later_version_evidence": later_version_evidence}
