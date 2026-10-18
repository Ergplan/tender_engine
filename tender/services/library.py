"""The public library tier (Stage 5D): search over what a principal may read, matching
a document in the user's hand to a library tender, free sign-up, the watchlist, a user's
model assumptions and the financial model built on the one engine.

Nothing here writes a fact. Search and matching see only tenders whose publication state
shows them (published, update_pending); a suspended or unreviewed tender is absent.
Row-level security already limits every query to the principal's read tenants; the
queries filter by them as well.
"""

import re
import secrets
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.db import SYSTEM_TENANT, set_tenant
from core.models import AppUser, Tenant
from core.services import audit
from core.services.identity import Principal, read_tenants_of
from tender.models import ModelAssumption, Tender, WatchlistEntry
from tender.models.library import MODEL_TYPES
from tender.services.finance import Assumptions, Outputs, power_project_finance
from tender.services.model_inputs import PATHS, fixed_inputs
from tender.services.packs import Catalog
from tender.services.publication import PublicationState, publication_state
from tender.services.published import (
    AUTHORITY_NOTE,
    DEFAULT_ROLE,
    Evidence,
    PublishedField,
    PublishedTender,
    Reliability,
    published_tender,
    reliability_of,
    reviewer_roles,
)
from tender.services.review import latest_snapshot
from tender.services.tenders import TenderService

ACTOR = "library"
VISIBLE_STATES = ("published", "update_pending")
DEADLINE_FIELD = "core.key_dates.bid_submission_deadline"
CAPACITY_FIELD = "sector.power.common.total_capacity_mw"
# Words a user says that tell nothing apart.
STOPWORDS = frozenset(
    {
        "the", "one", "a", "an", "of", "for", "and", "tender", "tenders", "rfs", "rfp", "rfq",
        "nit", "no", "number", "document", "request", "selection", "procurement", "bid", "bids",
        "power", "project", "projects", "in", "india", "under",
    }
)  # fmt: skip
AGENCY_ALIASES = {
    "solar energy corporation of india": "seci",
    "solar energy corporation of india limited": "seci",
    "ntpc limited": "ntpc",
    "ntpc ltd": "ntpc",
    "ntpc renewable energy limited": "ntpc rel",
    "ntpc renewable energy": "ntpc rel",
    "nhpc limited": "nhpc",
    "nhpc ltd": "nhpc",
    "rec power development and consultancy limited": "recpdcl",
    "west bengal state electricity distribution company limited": "wbsedcl",
}
ROMAN = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9,
    "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15, "xvi": 16,
    "xvii": 17, "xviii": 18, "xix": 19, "xx": 20,
}  # fmt: skip


class LibraryError(ValueError):
    """The request cannot be carried out as asked. The message is safe to show."""


class TenderSearchHit(BaseModel):
    """A tender as search and matching return it: identity, publication state and the
    same provenance and reliability block every public response carries."""

    tender_id: str
    tenant_id: str
    slug: str | None
    title: str
    issuing_agency: str
    tender_type: str
    external_ref: str | None
    publication: PublicationState
    banner: str | None
    reviewed_at: datetime | None = None
    reviewer_role: str | None = None
    reliability: Reliability | None = None


class SearchResult(BaseModel):
    hits: list[TenderSearchHit]
    authority_note: str = AUTHORITY_NOTE


class MatchCandidate(BaseModel):
    tender_id: str
    title: str
    issuing_agency: str
    tender_type: str
    external_ref: str | None
    score: float
    # What tells it apart from the others offered: agency, number, capacity.
    distinguishing: str


class Match(BaseModel):
    kind: Literal["match"] = "match"
    tender: TenderSearchHit
    score: float
    authority_note: str = AUTHORITY_NOTE


class NoMatch(BaseModel):
    kind: Literal["no_match"] = "no_match"
    reason: str
    candidates: list[MatchCandidate]
    authority_note: str = AUTHORITY_NOTE


class WatchedTender(BaseModel):
    tender_id: str
    title: str
    issuing_agency: str
    tender_type: str
    publication_state: str
    bid_deadline: date | None
    days_remaining: int | None


class FixedParameter(BaseModel):
    """One tender-fixed parameter as the widget shows it: locked, with its page chip, or
    a typed gap saying why there is none."""

    name: str
    label: str
    value: Any = None
    unit: str | None = None
    path: str | None = None
    version_no: int | None = None
    status: str  # reviewed | not_reviewed | possibly_superseded | not_in_schema
    evidence: list[Evidence] = []
    gap_reason: str | None = None


# Shown beside the engine's inputs, locked, though the engine does not compute with it.
DISPLAY_PATHS: dict[str, tuple[str, ...]] = {
    **PATHS,
    "payment_security": (
        "sector.power.ipp.payment_security_mechanism",
        "core.commercial.payment_security_mechanism",
    ),
}


def fixed_parameters(view: PublishedTender) -> list[FixedParameter]:
    """Every parameter the widget's left panel lists, from the published view only."""
    by_path: dict[str, PublishedField] = {f.path: f for s in view.sections for f in s.fields}
    out: list[FixedParameter] = []
    for name, paths in DISPLAY_PATHS.items():
        field = next((by_path[p] for p in paths if p in by_path), None)
        if field is None:
            out.append(
                FixedParameter(
                    name=name,
                    label=name.replace("_", " "),
                    path=paths[0],
                    status="not_in_schema",
                    gap_reason="the tender type's schema has no field for it",
                )
            )
            continue
        reviewed = field.status == "reviewed" and field.value is not None and not field.withdrawn
        out.append(
            FixedParameter(
                name=name,
                label=field.label,
                value=field.value if reviewed else None,
                unit=field.unit,
                path=field.path,
                version_no=field.version_no,
                status=field.status,
                evidence=field.evidence if reviewed else [],
                gap_reason=(
                    None
                    if reviewed
                    else (
                        f"withdrawn by version {field.version_no}"
                        if field.withdrawn
                        else (field.gap.reason if field.gap else "not reviewed")
                    )
                ),
            )
        )
    return out


class ModelResult(BaseModel):
    tender_id: str
    model_type: str
    label: str = "indicative"
    authority_note: str = AUTHORITY_NOTE
    fixed: list[FixedParameter]
    assumptions: Assumptions
    assumptions_saved: bool
    outputs: Outputs | None
    note: str


# -- normalisation and matching ----------------------------------------------------------


def normalise(text: str) -> list[str]:
    """Tokens a reader would match on: lower case, agency aliases folded, Roman numerals
    as numbers, MWh and MW kept, punctuation gone, stopwords out."""
    lowered = " " + text.lower() + " "
    # 4,800 and 1,50,000 are one number each, not two or three.
    lowered = re.sub(r"(?<=\d),(?=\d)", "", lowered)
    for alias, short in sorted(AGENCY_ALIASES.items(), key=lambda kv: -len(kv[0])):
        lowered = lowered.replace(f" {alias} ", f" {short} ")
    lowered = re.sub(r"(\d)\s*mwh\b", r"\1 mwh", lowered)
    lowered = re.sub(r"(\d)\s*mw\b", r"\1 mw", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    tokens: list[str] = []
    for token in lowered.split():
        if token in ROMAN:
            token = str(ROMAN[token])
        if token in STOPWORDS or len(token) < 2 and not token.isdigit():
            continue
        tokens.append(token)
    return tokens


def _tender_tokens(tender: Tender) -> set[str]:
    parts = [tender.title, tender.issuing_agency, tender.external_ref or "", tender.slug or ""]
    return set(normalise(" ".join(parts)))


def _numbers(tokens: list[str] | set[str]) -> set[str]:
    return {t for t in tokens if t.isdigit()}


def visible_tenders(
    session: Session, tenants: tuple[str, ...], catalog: Catalog
) -> list[tuple[Tender, PublicationState]]:
    """The tenders a principal may read whose publication state shows them."""
    rows = session.scalars(
        select(Tender)
        .where(Tender.tenant_id.in_(list(tenants)), Tender.status != "superseded")
        .order_by(Tender.tender_type, Tender.created_at)
    )
    out = []
    for tender in rows:
        state = publication_state(session, catalog, tender)
        if state.state in VISIBLE_STATES:
            out.append((tender, state))
    return out


def _hit(
    session: Session,
    catalog: Catalog,
    tender: Tender,
    state: PublicationState,
    results_root: Path | None = None,
) -> TenderSearchHit:
    from tender.services.published import _banner

    snapshot = latest_snapshot(session, tender)
    role = None
    if snapshot is not None:
        role = reviewer_roles(session, tender.tenant_id, {snapshot.reviewer}).get(
            snapshot.reviewer, DEFAULT_ROLE
        )
    return TenderSearchHit(
        tender_id=tender.id,
        tenant_id=tender.tenant_id,
        slug=tender.slug,
        title=tender.title,
        issuing_agency=tender.issuing_agency,
        tender_type=tender.tender_type,
        external_ref=tender.external_ref,
        publication=state,
        banner=_banner(state),
        reviewed_at=snapshot.created_at if snapshot else None,
        reviewer_role=role,
        reliability=reliability_of(tender.tenant_id, tender.tender_type, results_root),
    )


def search_tenders(
    session: Session,
    catalog: Catalog,
    tenants: tuple[str, ...],
    *,
    query: str = "",
    tender_type: str | None = None,
    agency: str | None = None,
    state: str | None = None,
    results_root: Path | None = None,
) -> SearchResult:
    """Published tenders (and those with an update pending) the principal may read,
    narrowed by words, type, agency and state."""
    wanted = set(normalise(query)) if query.strip() else set()
    hits: list[TenderSearchHit] = []
    for tender, pub in visible_tenders(session, tenants, catalog):
        if tender_type and tender.tender_type != tender_type:
            continue
        if agency and set(normalise(agency)) - _tender_tokens(tender):
            continue
        if state and pub.state != state:
            continue
        if wanted and not wanted <= _tender_tokens(tender):
            continue
        hits.append(_hit(session, catalog, tender, pub, results_root))
    return SearchResult(hits=hits)


def score_match(
    query_tokens: list[str], tender: Tender, agency: str | None, capacity_mw: float | None
) -> tuple[float, str]:
    """How well a tender answers the words a user gave: the share of the words found on
    the tender, with a number the user gave that the tender lacks counting against it,
    the agency counting for it, and a capacity within five percent counting for it."""
    have = _tender_tokens(tender)
    words = list(query_tokens)
    if not words:
        return 0.0, ""
    found = sum(1 for t in words if t in have)
    score = found / len(words)
    # A number the user gave that the tender does not carry counts against it, whatever
    # else agrees: "FDRE IX" is not "FDRE X" at the same capacity.
    if _numbers(words) - have:
        score = min(score, 0.5)
    if agency:
        agreed = set(normalise(agency)) <= have
        score = min(1.0, score + 0.1) if agreed else min(score, 0.5)
    if capacity_mw is not None:
        close = any(t.isdigit() and abs(float(t) - capacity_mw) <= 0.05 * capacity_mw for t in have)
        score = min(1.0, score + 0.1) if close else min(score, 0.6)
    distinguishing = ", ".join(
        p for p in (tender.issuing_agency, tender.external_ref or "", tender.tender_type) if p
    )
    return round(score, 3), distinguishing


def find_matching_tender(
    session: Session,
    catalog: Catalog,
    settings: Settings,
    tenants: tuple[str, ...],
    title_or_number: str,
    *,
    agency: str | None = None,
    capacity_mw: float | None = None,
) -> Match | NoMatch:
    """The library tender a document in the user's hand is, or no_match with up to three
    candidates and what tells them apart. A false match is worse than none: below the
    threshold, or with two candidates too close to tell apart, it is no_match."""
    tokens = normalise(title_or_number)
    if not tokens:
        return NoMatch(reason="nothing to match on", candidates=[])
    scored: list[tuple[float, str, Tender, PublicationState]] = []
    for tender, state in visible_tenders(session, tenants, catalog):
        score, why = score_match(tokens, tender, agency, capacity_mw)
        if score > 0:
            scored.append((score, why, tender, state))
    scored.sort(key=lambda s: (-s[0], s[2].title))
    candidates = [
        MatchCandidate(
            tender_id=t.id,
            title=t.title,
            issuing_agency=t.issuing_agency,
            tender_type=t.tender_type,
            external_ref=t.external_ref,
            score=score,
            distinguishing=why,
        )
        for score, why, t, _ in scored[:3]
    ]
    if not scored:
        return NoMatch(reason="no library tender shares those words", candidates=[])
    best, why, tender, state = scored[0]
    if best < settings.match_threshold:
        return NoMatch(reason=f"the best candidate scores {best:.2f}", candidates=candidates)
    if len(scored) > 1 and scored[1][0] >= best - 0.05:
        return NoMatch(reason="two tenders fit the words equally well", candidates=candidates)
    results_root = Path(settings.results_root) if settings.results_root else None
    return Match(tender=_hit(session, catalog, tender, state, results_root), score=best)


# -- free sign-up ----------------------------------------------------------------------


def signup(
    session: Session, *, email: str, display_name: str, oidc_subject: str
) -> tuple[Tenant, AppUser]:
    """A free account: its own tenant with no tenders, reading the public library. The
    user's role is `reviewer` — the least role there is; on a tenant without tenders it
    decides nothing, and the public library is read-only to it at the database. Written in
    the system scope: a tenant is made by the registry, not by a principal."""
    address = email.strip().lower()
    if "@" not in address:
        raise LibraryError("sign-up needs an email address")
    # The one look-up that cannot filter by tenant: the account's tenant is what the
    # look-up finds out. Everything written after it names the new tenant.
    set_tenant(session, SYSTEM_TENANT)
    if session.scalar(select(AppUser.id).where(AppUser.oidc_subject == oidc_subject)):
        raise LibraryError("this account already exists")
    tenant = Tenant(
        tenant_id=f"free-{secrets.token_hex(6)}",
        name=display_name.strip()[:200] or address,
        created_by=ACTOR,
        plan="free",
    )
    session.add(tenant)
    session.flush()
    user = AppUser(
        tenant_id=tenant.tenant_id,
        created_by=ACTOR,
        email=address,
        display_name=display_name.strip()[:200] or address,
        role="reviewer",
        status="active",
        oidc_subject=oidc_subject,
        last_login_at=datetime.now(UTC),
    )
    session.add(user)
    session.flush()
    audit.record(
        session,
        tenant_id=tenant.tenant_id,
        actor=ACTOR,
        action="signup",
        table_name="app_user",
        row_id=user.id,
        after={"email": address, "tenant_id": tenant.tenant_id, "plan": "free"},
    )
    session.commit()
    return tenant, user


def is_free(session: Session, tenant_id: str) -> bool:
    plan = session.scalar(select(Tenant.plan).where(Tenant.tenant_id == tenant_id))
    return plan == "free"


# -- watchlist ---------------------------------------------------------------------------


def _owner(principal: Principal) -> tuple[str, str | None]:
    return principal.tenant_id, principal.user_id


def _readable(principal: Principal, tender: Tender) -> None:
    if tender.tenant_id not in read_tenants_of(principal.tenant_id):
        raise LookupError(f"tender {tender.id} not found")


def watchlist_add(session: Session, principal: Principal, tender: Tender) -> WatchlistEntry:
    _readable(principal, tender)
    tenant_id, user_id = _owner(principal)
    existing = session.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.tenant_id == tenant_id,
            WatchlistEntry.user_id == user_id,
            WatchlistEntry.tender_id == tender.id,
        )
    )
    if existing is not None:
        return existing
    entry = WatchlistEntry(
        tenant_id=tenant_id,
        created_by=principal.name or ACTOR,
        user_id=user_id,
        tender_id=tender.id,
        tender_tenant_id=tender.tenant_id,
    )
    session.add(entry)
    session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=principal.name or ACTOR,
        action="insert",
        table_name="watchlist_entry",
        row_id=entry.id,
        after={"tender_id": tender.id, "user_id": user_id},
    )
    session.commit()
    return entry


def watchlist_remove(session: Session, principal: Principal, tender_id: str) -> bool:
    tenant_id, user_id = _owner(principal)
    entry = session.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.tenant_id == tenant_id,
            WatchlistEntry.user_id == user_id,
            WatchlistEntry.tender_id == tender_id,
        )
    )
    if entry is None:
        return False
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=principal.name or ACTOR,
        action="delete",
        table_name="watchlist_entry",
        row_id=entry.id,
        before={"tender_id": tender_id, "user_id": user_id},
    )
    session.delete(entry)
    session.commit()
    return True


def watchlist(
    session: Session, catalog: Catalog, tenders: TenderService, principal: Principal
) -> list[WatchedTender]:
    """What the principal follows, with the bid deadline and the days left to it."""
    tenant_id, user_id = _owner(principal)
    entries = session.scalars(
        select(WatchlistEntry)
        .where(WatchlistEntry.tenant_id == tenant_id, WatchlistEntry.user_id == user_id)
        .order_by(WatchlistEntry.created_at)
    )
    out: list[WatchedTender] = []
    today = datetime.now(UTC).date()
    for entry in entries:
        # A followed tender may be the library's, not the principal's own: look it up
        # across the tenants the principal reads, not the service's one tenant.
        tender = session.scalar(
            select(Tender).where(
                Tender.id == entry.tender_id,
                Tender.tenant_id.in_(list(read_tenants_of(principal.tenant_id))),
                Tender.status != "superseded",
            )
        )
        if tender is None:
            continue
        view = published_tender(session, catalog, tender)
        deadline = next(
            (f.value for s in view.sections for f in s.fields if f.path == DEADLINE_FIELD), None
        )
        parsed = _date(deadline)
        out.append(
            WatchedTender(
                tender_id=tender.id,
                title=tender.title,
                issuing_agency=tender.issuing_agency,
                tender_type=tender.tender_type,
                publication_state=view.publication.state,
                bid_deadline=parsed,
                days_remaining=(parsed - today).days if parsed else None,
            )
        )
    return out


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


# -- assumptions and the model -------------------------------------------------------------


def upsert_assumptions(
    session: Session,
    principal: Principal,
    tender: Tender,
    model_type: str,
    assumptions: dict[str, Any],
) -> ModelAssumption:
    """The principal's assumptions for one model of one tender. Validated against the
    engine's own fields; never a canonical fact."""
    if model_type not in MODEL_TYPES:
        raise LibraryError(f"unknown model type {model_type!r}; one of {list(MODEL_TYPES)}")
    _readable(principal, tender)
    clean = Assumptions(
        **{k: v for k, v in assumptions.items() if k in Assumptions.__dataclass_fields__}
    )
    unknown = sorted(set(assumptions) - set(Assumptions.__dataclass_fields__))
    if unknown:
        raise LibraryError(f"unknown assumption(s) {unknown}")
    tenant_id, user_id = _owner(principal)
    row = session.scalar(
        select(ModelAssumption).where(
            ModelAssumption.tenant_id == tenant_id,
            ModelAssumption.user_id == user_id,
            ModelAssumption.tender_id == tender.id,
            ModelAssumption.model_type == model_type,
        )
    )
    payload = clean.__dict__.copy()
    if row is None:
        row = ModelAssumption(
            tenant_id=tenant_id,
            created_by=principal.name or ACTOR,
            user_id=user_id,
            tender_id=tender.id,
            tender_tenant_id=tender.tenant_id,
            model_type=model_type,
            assumptions=payload,
        )
        session.add(row)
        session.flush()
        before = None
    else:
        before = dict(row.assumptions)
        row.assumptions = payload
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=principal.name or ACTOR,
        action="upsert",
        table_name="model_assumption",
        row_id=row.id,
        before=before,
        after=payload,
    )
    session.commit()
    return row


def saved_assumptions(
    session: Session, principal: Principal, tender: Tender, model_type: str
) -> ModelAssumption | None:
    tenant_id, user_id = _owner(principal)
    return session.scalar(
        select(ModelAssumption).where(
            ModelAssumption.tenant_id == tenant_id,
            ModelAssumption.user_id == user_id,
            ModelAssumption.tender_id == tender.id,
            ModelAssumption.model_type == model_type,
        )
    )


def model_tender(
    session: Session,
    catalog: Catalog,
    principal: Principal,
    tender: Tender,
    model_type: str,
    assumptions: dict[str, Any] | None = None,
) -> ModelResult:
    """The model: the tender's fixed parameters with provenance, the assumptions (given
    now, else saved, else the engine's defaults marked assumed) and the engine's figures.
    Read-only: nothing is saved here."""
    if model_type not in MODEL_TYPES:
        raise LibraryError(f"unknown model type {model_type!r}; one of {list(MODEL_TYPES)}")
    _readable(principal, tender)
    view = published_tender(session, catalog, tender)
    fixed, inputs = fixed_parameters(view), fixed_inputs(view)
    saved = saved_assumptions(session, principal, tender, model_type)
    source: dict[str, Any] = dict(saved.assumptions) if saved else {}
    if assumptions:
        unknown = sorted(set(assumptions) - set(Assumptions.__dataclass_fields__))
        if unknown:
            raise LibraryError(f"unknown assumption(s) {unknown}")
        source.update(assumptions)
    used = Assumptions(**source)
    if inputs.capacity_mw <= 0:
        return ModelResult(
            tender_id=tender.id,
            model_type=model_type,
            fixed=fixed,
            assumptions=used,
            assumptions_saved=saved is not None,
            outputs=None,
            note="no capacity is published for this tender; the model cannot run",
        )
    outputs = power_project_finance(inputs, used)
    assumed = [k for k, v in outputs.used.items() if v == "assumed"]
    note = "indicative; " + (
        f"{', '.join(assumed)} taken from the assumptions, not the tender"
        if assumed
        else "every parameter from the tender"
    )
    return ModelResult(
        tender_id=tender.id,
        model_type=model_type,
        fixed=fixed,
        assumptions=used,
        assumptions_saved=saved is not None,
        outputs=outputs,
        note=note,
    )
