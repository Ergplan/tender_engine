"""Which tender an amending document belongs to (Stage 7, Block 3 a).

An amendment, corrigendum or clarification names its tender on its first pages: the RfS or
tender reference number ("RfS No. SECI/C&P/IPP/13/0002/26-27", "Ref No. …/Amendment-01",
"Tender Reference No.", a CPPP id like 2024_NHPC_800202_1), the issuer, and the tender's
title words. The link is made from those, in two steps:

1. a reference the document prints that equals a tender's `external_ref` (normalised:
   case, spaces and the amendment suffix set aside) is the tender, confidence 0.98, when
   exactly one tender carries it;
2. otherwise the title words and the issuer are scored against every tender with the
   library matcher's rules (`tender.services.library.score_match`), and the best tender is
   linked only above LINK_THRESHOLD with a margin of LINK_MARGIN over the next.

Anything less is `ask`: the candidates come back, with what tells them apart, and a person
chooses. A wrong link would put a corrigendum on the wrong tender, which is worse than no
link. Nothing here writes; the caller adds the version once the link is settled.
"""

import re
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Document, Page
from tender.models import Tender
from tender.services.library import normalise

PAGES_READ = 3
LINK_THRESHOLD = 0.85
LINK_MARGIN = 0.10
EXACT_CONFIDENCE = 0.98
# A reference: letters and digits joined by slashes, underscores or dashes, with at least
# one slash or underscore and one digit (SECI/C&P/IPP/13/0002/26-27, NTPC/RE-CS/2024-25/
# HYBRID-03, 2024_NHPC_800202_1, NRE-CS-5846-004).
REFERENCE = re.compile(
    r"\b(?=[A-Z0-9/&_\-.]*\d)(?=[A-Z0-9/&_\-.]*[A-Z])(?=[A-Z0-9/&_\-.]*[/_\-])"
    r"[A-Z0-9][A-Z0-9&]*(?:[/_\-.][A-Z0-9&]+){2,}\b"
)
AMENDMENT_SUFFIX = re.compile(
    r"[/\-_](AMENDMENT|CORRIGENDUM|ADDENDUM|CLARIFICATION|AMD|CORR)[\-_ ]?\d*$", re.IGNORECASE
)
ISSUERS = ("SECI", "NTPC", "NHPC", "SJVN", "IREDA", "RECPDCL", "WBSEDCL", "NRE", "NTPC RENEWABLE")

LinkState = Literal["linked", "ask", "none"]


class LinkCandidate(BaseModel):
    tender_id: str
    slug: str | None
    title: str
    issuing_agency: str
    external_ref: str | None
    score: float
    why: str


class AmendmentLink(BaseModel):
    state: LinkState
    tender_id: str | None
    confidence: float
    method: Literal["reference", "title", "none"]
    references_found: list[str]
    candidates: list[LinkCandidate]
    reason: str


def normalise_reference(text: str) -> str:
    ref = re.sub(r"\s+", "", text.upper())
    ref = AMENDMENT_SUFFIX.sub("", ref)
    return ref.strip("/-_.")


def references_in(text: str) -> list[str]:
    """Reference-like tokens in document order, amendment suffixes set aside, once each."""
    seen: list[str] = []
    for match in REFERENCE.finditer(text.upper()):
        ref = normalise_reference(match.group(0))
        if len(ref) >= 6 and ref not in seen:
            seen.append(ref)
    return seen


def issuer_in(text: str) -> str | None:
    upper = text.upper()
    for issuer in sorted(ISSUERS, key=len, reverse=True):
        if issuer in upper:
            return issuer
    return None


def link_amendment(
    session: Session, tenant_id: str, document_id: str, *, pages: int = PAGES_READ
) -> AmendmentLink:
    document = session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if document is None:
        raise LookupError(f"document {document_id} not found")
    if document.status != "parsed":
        raise ValueError(f"document is {document.status}, not parsed")
    text = "\n".join(
        session.scalars(
            select(Page.text)
            .where(Page.document_id == document.id, Page.tenant_id == tenant_id)
            .order_by(Page.page_no)
            .limit(pages)
        )
    )
    tenders = list(
        session.scalars(
            select(Tender).where(Tender.tenant_id == tenant_id, Tender.status != "superseded")
        )
    )
    return link_from_text(text, tenders, filename=document.filename)


def link_from_text(text: str, tenders: list[Tender], *, filename: str = "") -> AmendmentLink:
    refs = references_in(text)
    by_ref: dict[str, list[Tender]] = {}
    for tender in tenders:
        if tender.external_ref:
            by_ref.setdefault(normalise_reference(tender.external_ref), []).append(tender)
    for ref in refs:
        hits = by_ref.get(ref, [])
        if len(hits) == 1:
            tender = hits[0]
            return AmendmentLink(
                state="linked",
                tender_id=tender.id,
                confidence=EXACT_CONFIDENCE,
                method="reference",
                references_found=refs,
                candidates=[_candidate(tender, EXACT_CONFIDENCE, f"reference {ref}")],
                reason=f"the document prints the tender's reference {ref}",
            )
        if len(hits) > 1:
            return AmendmentLink(
                state="ask",
                tender_id=None,
                confidence=0.5,
                method="reference",
                references_found=refs,
                candidates=[_candidate(t, 0.5, f"shares reference {ref}") for t in hits],
                reason=f"{len(hits)} tenders carry the reference {ref}",
            )
    # No printed reference matched: how much of each tender's own title the document's
    # opening words carry, with the issuer agreeing or not.
    head = " ".join(text.split()[:150])
    present = set(normalise(f"{filename} {head}"))
    issuer = issuer_in(head)
    scored: list[tuple[float, str, Tender]] = []
    for tender in tenders:
        score, why = title_recall(present, tender, issuer)
        if score > 0:
            scored.append((score, why, tender))
    scored.sort(key=lambda s: (-s[0], s[2].title))
    candidates = [_candidate(t, score, why) for score, why, t in scored[:3]]
    if not scored:
        return AmendmentLink(
            state="none",
            tender_id=None,
            confidence=0.0,
            method="none",
            references_found=refs,
            candidates=[],
            reason="no tender shares the document's reference or words",
        )
    best, _, tender = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best >= LINK_THRESHOLD and best - runner_up >= LINK_MARGIN:
        return AmendmentLink(
            state="linked",
            tender_id=tender.id,
            confidence=round(best, 3),
            method="title",
            references_found=refs,
            candidates=candidates,
            reason=f"the title words fit one tender ({best:.2f}, next {runner_up:.2f})",
        )
    return AmendmentLink(
        state="ask",
        tender_id=None,
        confidence=round(best, 3),
        method="title",
        references_found=refs,
        candidates=candidates,
        reason=(
            f"the best tender scores {best:.2f}"
            + (f", the next {runner_up:.2f}" if runner_up else "")
            + ": a person chooses"
        ),
    )


def title_recall(present: set[str], tender: Tender, issuer: str | None) -> tuple[float, str]:
    """The share of the tender's title words (agency aliases expanded, as the library
    matcher normalises them) that the document's opening words carry. A number in the
    title the document lacks caps the score at 0.5 (FDRE IX is not FDRE X); an issuer the
    document names that is not the tender's caps it too."""
    title_tokens = normalise(f"{tender.title} {tender.external_ref or ''}")
    if not title_tokens:
        return 0.0, ""
    found = sum(1 for t in title_tokens if t in present)
    score = found / len(title_tokens)
    if any(t.isdigit() for t in title_tokens if t not in present):
        score = min(score, 0.5)
    if issuer:
        agency_tokens = set(normalise(tender.issuing_agency))
        if agency_tokens and not (agency_tokens & set(normalise(issuer))):
            score = min(score, 0.5)
    why = ", ".join(
        p for p in (tender.issuing_agency, tender.external_ref or "", tender.tender_type) if p
    )
    return round(score, 3), why


def _candidate(tender: Tender, score: float, why: str) -> LinkCandidate:
    return LinkCandidate(
        tender_id=tender.id,
        slug=tender.slug,
        title=tender.title,
        issuing_agency=tender.issuing_agency,
        external_ref=tender.external_ref,
        score=round(score, 3),
        why=why,
    )
