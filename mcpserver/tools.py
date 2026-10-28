"""The library's tools, as plain functions over a session and a principal.

Each returns a `ToolResult`: a Pydantic model for `structured_content` and a complete
plain-text rendering for hosts without widgets. The search, the match, the watchlist,
the assumptions and the model are `tender.services.library` (one implementation, shared
with the API's routes); what is here is the plain-text rendering, the tier gate and the
metering. Free-tier tools read the public library and the caller's own tenant (row-level
security scopes the session to exactly that); paid tools need an enterprise tenant. Every
call is metered to the calling tenant (`IdentityService.record_usage`); the free tier has
its own rate limit and daily cap.

The base tool definitions were never specified by the owner (DECISIONS 2026-10-04): the
arguments and results below are drawn from the master prompt's widget and tier text.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, replace
from dataclasses import fields as dataclass_fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.db import set_tenant
from core.evidence import PageText, locate
from core.models import Document, Page, UsageRecord
from core.services.identity import IdentityService, Principal
from core.storage import Storage
from evals.reliability import Composite, composite
from tender.models import Tender
from tender.services import library
from tender.services.ask import AskAnswer, AskError, AskService
from tender.services.changelog import Changelog, changelog
from tender.services.compare import MAX_TENDERS, Comparison, compare_tenders
from tender.services.finance import Assumptions
from tender.services.library import (
    LibraryError,
    Match,
    ModelResult,
    NoMatch,
    TenderSearchHit,
    WatchedTender,
)
from tender.services.packs import Catalog
from tender.services.published import (
    AUTHORITY_NOTE,
    PublishedField,
    PublishedTender,
    Reliability,
    published_tender,
    reliability_of,
)
from tender.services.snapshot import TenderSnapshot
from tender.services.status import TenderStatus, tender_status
from tender.services.submit import SubmitError, SubmitService
from tender.services.tenders import TenderService
from tender.services.tokens import TokenService

ACTOR = "mcp"
DEADLINE = library.DEADLINE_FIELD
FREE_TOOLS = (
    "search_tenders",
    "get_tender",
    "get_field",
    "get_document_page",
    "find_matching_tender",
    "list_changes",
    "compare_tenders",
    "reliability_report",
)
PAID_TOOLS = (
    "model_tender",
    "save_model_assumptions",
    "my_watchlist",
    "ask_tender",
    "get_status",
    "get_changes",
    "submit_tender",
    "submit_amendment",
    "get_review_link",
)
# Block 6 c: a tool that changes the caller's tenant needs the write scope on the token
# (`own:write` from the OAuth consent, `write` on an API key); a review link its own.
WRITE_TOOLS = ("submit_tender", "submit_amendment")
MINT_TOOLS = ("get_review_link",)
ASSUMPTION_NAMES = tuple(f.name for f in dataclass_fields(Assumptions))


class ToolRefused(Exception):
    """A refusal the caller is told about: the type names the rule."""

    def __init__(self, error_type: str, message: str, status: int) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.status = status


@dataclass
class ToolContext:
    session: Session
    principal: Principal
    settings: Settings
    catalog: Catalog
    identity: IdentityService
    tenders: TenderService
    storage: Storage
    results_root: Path | None = None
    # The full-tender query (Stage 7, Block 5); None where the host built no retrieval.
    ask: AskService | None = None
    # Submissions and review links (Stage 7, Block 6 c).
    submit: SubmitService | None = None
    tokens: TokenService | None = None

    @property
    def public_base_url(self) -> str:
        return self.settings.public_base_url.rstrip("/")


@dataclass(frozen=True)
class ToolResult:
    structured: BaseModel
    text: str
    # Whose data was read: the tender's (or document's) tenant, for the usage record.
    resource_tenant_id: str | None = None

    def structured_content(self) -> dict[str, Any]:
        return self.structured.model_dump(mode="json")


# -- result models -----------------------------------------------------------------------


class Provenance(BaseModel):
    reviewed_at: datetime | None
    reviewer_role: str | None
    reviewed_version: int | None
    current_version: int | None
    publication_state: str
    banner: str | None


class SearchResult(BaseModel):
    query: str | None
    tenders: list[TenderSearchHit]
    reliability: list[Reliability]
    authority_note: str = AUTHORITY_NOTE


class TenderCard(PublishedTender):
    """The published view itself (what the tender_card widget renders), plus the
    provenance block and the days to the bid deadline."""

    provenance: Provenance
    days_remaining: int | None


class AskResult(AskAnswer):
    title: str
    provenance: Provenance


class FieldResult(BaseModel):
    tender_id: str
    title: str
    field: PublishedField
    provenance: Provenance
    reliability: Reliability | None
    authority_note: str = AUTHORITY_NOTE


class Highlight(BaseModel):
    quote: str
    char_start: int
    char_end: int
    bbox: list[float] | None
    score: float


class PageResult(BaseModel):
    document_id: str
    filename: str
    page_no: int
    page_count: int | None
    text: str
    has_text_layer: bool
    render_url: str
    # The stored render inline, so a widget makes no request of its own.
    image_data_url: str
    width: float
    height: float
    highlight: Highlight | None
    authority_note: str = AUTHORITY_NOTE


class MatchResult(BaseModel):
    result: Match | NoMatch
    query: str
    threshold: float
    note: str = "Matched against the library only; the document was not read."
    authority_note: str = AUTHORITY_NOTE


class ChangesResult(Changelog):
    """The changelog itself (what the changes_view widget renders), plus provenance."""

    provenance: Provenance
    reliability: Reliability | None
    authority_note: str = AUTHORITY_NOTE


class CompareResult(Comparison):
    """The comparison itself (what the comparison_table widget renders), plus the
    reliability block per tender type."""

    reliability: list[Reliability]


class ReliabilityReport(BaseModel):
    tenant_id: str
    by_type: list[Reliability]
    note: str
    # The completion plan's Block 7 b: the gold-set eval (in-sample), the evidence-location
    # rate on the unseen tenders and the question eval, with the only sentences a report may
    # use for accuracy (DECISIONS 2026-10-27), read from the result files.
    composite: Composite | None = None
    authority_note: str = AUTHORITY_NOTE


class ModelCard(ModelResult):
    """The model result itself (what the financial_model widget renders), plus the
    tender's title, provenance and reliability."""

    title: str
    provenance: Provenance
    reliability: Reliability | None
    authority_note: str = AUTHORITY_NOTE


class SavedAssumptions(BaseModel):
    tender_id: str
    model_type: str
    assumptions: dict[str, Any]
    saved_at: datetime
    authority_note: str = AUTHORITY_NOTE


class WatchlistResult(BaseModel):
    added: list[str]
    removed: list[str]
    tenders: list[WatchedTender]
    authority_note: str = AUTHORITY_NOTE


# -- tiers, limits, metering ---------------------------------------------------------------


def tier_of(ctx: ToolContext) -> str:
    """free: a free-plan tenant, or a token scoped to the public library only. Otherwise
    enterprise. Every key carries `read`; a token the OAuth server issued for the library
    alone carries `public:read` and nothing else beside it."""
    scopes = set(ctx.principal.scopes) - {"read"}
    if scopes == {"public:read"}:
        return "free"
    return "free" if library.is_free(ctx.session, ctx.principal.tenant_id) else "enterprise"


def _usage_since(ctx: ToolContext, since: datetime) -> int:
    """The calling tenant's calls since `since`, whatever key made them: the free
    allowance is the tenant's, not each key's."""
    return int(
        ctx.session.scalar(
            select(func.count())
            .select_from(UsageRecord)
            .where(
                UsageRecord.tenant_id == ctx.principal.tenant_id,
                UsageRecord.created_at >= since,
            )
        )
        or 0
    )


def library_only(principal: Principal) -> Principal:
    """A token scoped to `public:read` alone reads the library and nothing else, whatever
    tenant it belongs to."""
    if set(principal.scopes) - {"read"} == {"public:read"}:
        return replace(principal, read_tenants=("public",))
    return principal


def guard(ctx: ToolContext, tool: str) -> str:
    """The tier of the call, after the checks: a paid tool needs the enterprise tier; the
    free tier has its own rate limit and daily cap. Raises ToolRefused."""
    ctx.principal = library_only(ctx.principal)
    set_tenant(ctx.session, ctx.principal.tenant_id, ctx.principal.read_tenants)
    tier = tier_of(ctx)
    if tool in PAID_TOOLS and tier == "free":
        raise ToolRefused(
            "tier_required",
            f"{tool} is a paid-tier tool; the free tier reads the library",
            403,
        )
    scopes = set(ctx.principal.scopes)
    if tool in WRITE_TOOLS and not scopes & {"own:write", "write"}:
        raise ToolRefused("not_allowed", f"{tool} needs the write scope on this token", 403)
    if tool in MINT_TOOLS and not scopes & {"review:mint", "own:write"}:
        raise ToolRefused("not_allowed", f"{tool} needs the review:mint scope on this token", 403)
    if tier == "free":
        now = datetime.now(UTC)
        if _usage_since(ctx, now - timedelta(seconds=60)) >= ctx.settings.free_rate_limit_per_min:
            raise ToolRefused("rate_limited", "the free tier's calls per minute are used up", 429)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if _usage_since(ctx, midnight) >= ctx.settings.free_daily_cap:
            raise ToolRefused("daily_cap", "the free tier's calls for today are used up", 429)
    return tier


def meter(
    ctx: ToolContext, tool: str, tier: str, *, resource_tenant_id: str | None, status: int
) -> None:
    ctx.identity.record_usage(
        ctx.session,
        ctx.principal,
        f"mcp:{tool}",
        resource_tenant_id=resource_tenant_id,
        status=status,
        tier=tier,
    )


def run_tool(ctx: ToolContext, tool: str, call: Any) -> ToolResult:
    """Guard, call, meter: what every tool goes through. `call` takes the tier."""
    tier = "free"
    try:
        tier = guard(ctx, tool)
        result: ToolResult = call(tier)
    except ToolRefused as exc:
        meter(ctx, tool, tier, resource_tenant_id=None, status=exc.status)
        raise
    except (LibraryError, LookupError) as exc:
        meter(ctx, tool, tier, resource_tenant_id=None, status=422)
        raise ToolRefused("validation_failed", str(exc), 422) from exc
    meter(ctx, tool, tier, resource_tenant_id=result.resource_tenant_id, status=200)
    return result


# -- helpers -------------------------------------------------------------------------------


def _tender(ctx: ToolContext, ref: str) -> Tender:
    tender = ctx.session.scalar(
        select(Tender).where(
            (Tender.slug == ref) | (Tender.id == ref),
            Tender.tenant_id.in_(list(ctx.principal.read_tenants)),
            Tender.status != "superseded",
        )
    )
    if tender is None:
        raise ToolRefused("not_found", f"no tender {ref!r} in the library or your tenant", 404)
    return tender


def _provenance(view: PublishedTender) -> Provenance:
    return Provenance(
        reviewed_at=view.reviewed_at,
        reviewer_role=view.reviewer_role,
        reviewed_version=view.reviewed_version,
        current_version=view.current_version,
        publication_state=view.publication.state,
        banner=view.banner,
    )


def _field(view: PublishedTender, path: str) -> PublishedField | None:
    return next((f for s in view.sections for f in s.fields if f.path == path), None)


def _days_remaining(view: PublishedTender) -> int | None:
    deadline = _field(view, DEADLINE)
    if deadline is None or deadline.status == "not_reviewed" or not deadline.value:
        return None
    try:
        return (date.fromisoformat(str(deadline.value)[:10]) - date.today()).days
    except ValueError:
        return None


def _view(ctx: ToolContext, tender: Tender) -> PublishedTender:
    return published_tender(ctx.session, ctx.catalog, tender, results_root=ctx.results_root)


def _reliabilities(ctx: ToolContext, types: set[str]) -> list[Reliability]:
    out = []
    for tender_type in sorted(types):
        figures = reliability_of(ctx.principal.tenant_id, tender_type, ctx.results_root)
        if figures is None:
            figures = reliability_of("public", tender_type, ctx.results_root)
        if figures is not None:
            out.append(figures)
    return out


def _value_text(field: PublishedField) -> str:
    if field.status == "not_reviewed":
        gap = field.gap
        where = f", likely page {gap.likely_page}" if gap and gap.likely_page else ""
        return f"not reviewed ({gap.reason if gap else 'no decision'}{where})"
    if field.withdrawn:
        return f"withdrawn by version {field.version_no}"
    value = field.value
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if field.unit:
        text = f"{text} {field.unit}"
    pages = ", ".join(f"{e.filename or e.document_id} p.{e.page_no}" for e in field.evidence)
    mark = " (possibly superseded)" if field.status == "possibly_superseded" else ""
    return f"{text}{mark}" + (f" [{pages}]" if pages else "")


def _reliability_text(reliability: Reliability | None) -> str:
    if reliability is None:
        return "Reliability: no evaluation on file."
    acc = f"{reliability.value_accuracy:.0%}" if reliability.value_accuracy is not None else "–"
    return (
        f"Reliability ({reliability.tender_type}): value accuracy {acc} over "
        f"{reliability.n_fields} scored fields, as of {reliability.as_of or 'unknown'}."
    )


def _provenance_text(view: PublishedTender) -> str:
    reviewed = (
        f"reviewed {view.reviewed_at:%Y-%m-%d} by {view.reviewer_role or 'reviewer'} at version "
        f"{view.reviewed_version} of {view.current_version}"
        if view.reviewed_at
        else "not reviewed"
    )
    return f"Publication: {view.publication.state}; {reviewed}." + (
        f" {view.banner}" if view.banner else ""
    )


# -- free tier ---------------------------------------------------------------------------


def search_tenders(
    ctx: ToolContext,
    query: str | None = None,
    tender_type: str | None = None,
    agency: str | None = None,
    state: str | None = None,
) -> ToolResult:
    """Published and update-pending tenders the caller may read, by the words of their
    title, number and agency; suspended and unpublished tenders are left out."""
    hits = library.search_tenders(
        ctx.session,
        ctx.catalog,
        ctx.principal.read_tenants,
        query=query or "",
        tender_type=tender_type,
        agency=agency,
        state=state,
    ).hits
    result = SearchResult(
        query=query,
        tenders=hits,
        reliability=_reliabilities(ctx, {t.tender_type for t in hits}),
    )
    read = ",".join(sorted({t.tenant_id for t in hits})) or None
    lines = [f"{len(hits)} tender(s)" + (f" for {query!r}" if query else "") + ":"]
    for t in hits:
        lines.append(
            f"- {t.title} — {t.issuing_agency}, {t.tender_type}"
            + (f", {t.external_ref}" if t.external_ref else "")
            + f"; {t.publication.state}"
            + (f" — {t.banner}" if t.banner else "")
            + f" [{t.slug or t.tender_id}]"
        )
    lines += [_reliability_text(r) for r in result.reliability] + [AUTHORITY_NOTE]
    return ToolResult(result, "\n".join(lines), resource_tenant_id=read)


def get_tender(ctx: ToolContext, tender: str) -> ToolResult:
    """The published view of one tender: canonical facts with their pages, the publication
    state and its banner, the review's date and role, the reliability block."""
    row = _tender(ctx, tender)
    view = _view(ctx, row)
    result = TenderCard(
        **view.model_dump(), provenance=_provenance(view), days_remaining=_days_remaining(view)
    )
    lines = [f"{view.title} — {view.issuing_agency}, {view.tender_type}", _provenance_text(view)]
    if view.suspension:
        lines.append(
            f"Publication suspended by version {view.suspension.version_no} "
            f"({view.suspension.kind}); fields affected: {', '.join(view.suspension.fields)}. "
            "No values are shown while the amendment is unreviewed."
        )
    for section in view.sections:
        lines.append(f"\n{section.label}")
        for field in section.fields:
            lines.append(f"  {field.label}: {_value_text(field)}")
    lines += ["", _reliability_text(view.reliability), AUTHORITY_NOTE]
    return ToolResult(result, "\n".join(lines), resource_tenant_id=row.tenant_id)


def get_field(ctx: ToolContext, tender: str, field_path: str) -> ToolResult:
    """One field of a tender with its provenance; a field not reviewed is a typed gap with
    its reason and the page it is likely on."""
    row = _tender(ctx, tender)
    view = _view(ctx, row)
    if view.suspension:
        raise ToolRefused(
            "publication_suspended",
            f"publication of {view.title} is suspended by version {view.suspension.version_no}; "
            "no field value is served",
            409,
        )
    field = _field(view, field_path)
    if field is None:
        raise ToolRefused(
            "not_found", f"{view.tender_type} tenders have no field {field_path}", 404
        )
    result = FieldResult(
        tender_id=view.tender_id,
        title=view.title,
        field=field,
        provenance=_provenance(view),
        reliability=view.reliability,
    )
    text = (
        f"{view.title}\n{field.label} ({field.path}): {_value_text(field)}\n"
        + (
            f"Set by version {field.version_no} ({field.set_by}), reviewed "
            f"{field.reviewed_at:%Y-%m-%d} by {field.reviewer_role}.\n"
            if field.reviewed_at
            else ""
        )
        + "\n".join(
            f"  “{e.quote}” — {e.filename or e.document_id} p.{e.page_no}" for e in field.evidence
        )
        + f"\n{_reliability_text(view.reliability)}\n{AUTHORITY_NOTE}"
    )
    return ToolResult(result, text, resource_tenant_id=row.tenant_id)


def get_document_page(
    ctx: ToolContext, document_id: str, page_no: int, quote: str | None = None
) -> ToolResult:
    """A page of a tender document: its text, the URL of its image, and where a quote sits
    on it (located with the engine's own resolver)."""
    readable = list(ctx.principal.read_tenants)
    document = ctx.session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id.in_(readable))
    )
    if document is None:
        raise ToolRefused("not_found", f"no document {document_id} you may read", 404)
    page = ctx.session.scalar(
        select(Page).where(
            Page.document_id == document.id,
            Page.tenant_id == document.tenant_id,
            Page.page_no == page_no,
        )
    )
    if page is None:
        raise ToolRefused("not_found", f"{document.filename} has no page {page_no}", 404)
    highlight = None
    if quote:
        found = locate(
            quote,
            PageText(
                page_no=page_no,
                text=page.text,
                char_boxes=page.char_boxes,
                has_text_layer=page.has_text_layer,
            ),
            ctx.settings.evidence_match_threshold,
        )
        if found is not None:
            highlight = Highlight(
                quote=quote,
                char_start=found.char_start,
                char_end=found.char_end,
                bbox=found.bbox,
                score=found.score,
            )
    result = PageResult(
        document_id=document.id,
        filename=document.filename,
        page_no=page_no,
        page_count=document.page_count,
        text=page.text,
        has_text_layer=page.has_text_layer,
        render_url=f"{ctx.public_base_url}/files/{page.render_path}",
        image_data_url="data:image/png;base64,"
        + base64.standard_b64encode(ctx.storage.get(page.render_path)).decode(),
        width=page.width,
        height=page.height,
        highlight=highlight,
    )
    text = (
        f"{document.filename}, page {page_no} of {document.page_count or '?'}"
        + ("" if page.has_text_layer else " (scanned: no text layer)")
        + (
            f"\nQuote found at characters {highlight.char_start}–{highlight.char_end}."
            if highlight
            else ("\nQuote not found on this page." if quote else "")
        )
        + f"\nImage: {result.render_url}\n\n{page.text}\n\n{AUTHORITY_NOTE}"
    )
    return ToolResult(result, text, resource_tenant_id=document.tenant_id)


def find_matching(
    ctx: ToolContext,
    title_or_number: str,
    agency: str | None = None,
    capacity_mw: float | None = None,
) -> ToolResult:
    """The reviewed tender matching a document the user is holding, or no_match with up
    to three candidates. The document is never read or ingested."""
    found = library.find_matching_tender(
        ctx.session,
        ctx.catalog,
        ctx.settings,
        ctx.principal.read_tenants,
        title_or_number,
        agency=agency,
        capacity_mw=capacity_mw,
    )
    result = MatchResult(
        result=found, query=title_or_number, threshold=ctx.settings.match_threshold
    )
    read = found.tender.tenant_id if isinstance(found, Match) else None
    if isinstance(found, Match):
        t = found.tender
        text = (
            f"Match: {t.title} — {t.issuing_agency}, {t.tender_type} [{t.slug or t.tender_id}] "
            f"(score {found.score:.2f}). {result.note}"
        )
    else:
        text = (
            f"No match for {title_or_number!r}: {found.reason}. Nothing was matched silently; "
            "the candidates and what tells them apart:\n"
            + "\n".join(
                f"- {c.title} [{c.tender_id}] score {c.score:.2f}: {c.distinguishing}"
                for c in found.candidates
            )
        )
    return ToolResult(result, f"{text}\n{AUTHORITY_NOTE}", resource_tenant_id=read)


def list_changes(ctx: ToolContext, tender: str) -> ToolResult:
    """The changelog across versions: per version the facts it changed, old to new, each
    with its evidence; an unreviewed version lists the fields it may touch, by path."""
    row = _tender(ctx, tender)
    view = _view(ctx, row)
    log = changelog(ctx.session, ctx.catalog, row)
    if view.publication.state == "publication_suspended":
        for version in log.versions:
            version.changes = []
    result = ChangesResult(
        **log.model_dump(), provenance=_provenance(view), reliability=view.reliability
    )
    lines = [
        f"{view.title}: changes across {len(log.versions)} version(s)",
        _provenance_text(view),
    ]
    for version in log.versions:
        issued = f", issued {version.issued_on}" if version.issued_on else ""
        lines.append(
            f"\nVersion {version.version_no} · {version.kind}{issued} · "
            f"{'reviewed' if version.reviewed else 'not yet reviewed'}"
        )
        for change in version.changes:
            after = (
                "withdrawn" if change.withdrawn else json.dumps(change.after, ensure_ascii=False)
            )
            pages = ", ".join(
                f"{e.filename or e.document_id} p.{e.page_no}" for e in change.evidence
            )
            lines.append(
                f"  {change.label}: {json.dumps(change.before, ensure_ascii=False)} → {after}"
                + (f" [{pages}]" if pages else "")
            )
        if version.pending:
            lines.append("  pending review, may touch: " + ", ".join(version.pending))
    lines += ["", _reliability_text(view.reliability), AUTHORITY_NOTE]
    return ToolResult(result, "\n".join(lines), resource_tenant_id=row.tenant_id)


def compare(ctx: ToolContext, tenders: list[str]) -> ToolResult:
    """Tenders as columns, fields as rows, provenance on every cell; a not-reviewed cell is
    marked, a suspended tender is left out with the reason."""
    if not tenders:
        raise ToolRefused("validation_failed", "name at least one tender", 422)
    if len(tenders) > MAX_TENDERS:
        raise ToolRefused(
            "validation_failed", f"at most {MAX_TENDERS} tenders can be compared", 422
        )
    rows = [_tender(ctx, ref) for ref in tenders]
    comparison = compare_tenders(ctx.session, ctx.catalog, rows, results_root=ctx.results_root)
    result = CompareResult(
        **comparison.model_dump(),
        reliability=_reliabilities(ctx, {c.tender_type for c in comparison.columns}),
    )
    header = " | ".join(f"{c.title} [{c.slug or c.tender_id}]" for c in comparison.columns)
    lines = [f"Comparison of {len(comparison.columns)} tender(s): {header}"]
    for row in comparison.rows:
        cells = ["—" if cell is None else _value_text(cell) for cell in row.cells]
        lines.append(f"{row.label}: " + " | ".join(cells))
    for item in comparison.excluded:
        lines.append(f"Left out: {item.get('tender_id')} — {item.get('reason')}")
    lines += [_reliability_text(r) for r in result.reliability] + [AUTHORITY_NOTE]
    return ToolResult(
        result, "\n".join(lines), resource_tenant_id=",".join(sorted({t.tenant_id for t in rows}))
    )


def reliability_report(ctx: ToolContext, tender_type: str | None = None) -> ToolResult:
    """Accuracy per tender type from the latest evaluation of the gold set."""
    types = {tender_type} if tender_type else set(ctx.catalog.types)
    figures = _reliabilities(ctx, types)
    overall = composite(ctx.principal.tenant_id, ctx.results_root)
    if not overall.in_sample:
        overall = composite("public", ctx.results_root)
    result = ReliabilityReport(
        tenant_id=ctx.principal.tenant_id,
        by_type=figures,
        note=(
            "Value accuracy is the share of reviewed fields the engine read as the reviewer "
            "decided; evidence accuracy the share whose cited page the reviewer accepted. "
            "Both come from `make eval` over the gold records, on the tenders the engine was "
            "tuned on (in-sample). The unseen tenders were never reviewed: their figure is "
            "evidence location, not accuracy."
        ),
        composite=overall,
    )
    lines = [*overall.statements, overall.caveat]
    lines += [_reliability_text(r) for r in figures] or ["No evaluation on file."]
    return ToolResult(result, "\n".join([*lines, result.note, AUTHORITY_NOTE]))


# -- paid tier ---------------------------------------------------------------------------


def model_tender(
    ctx: ToolContext,
    tender: str,
    model_type: str = "power_project_finance",
    assumptions: dict[str, Any] | None = None,
) -> ToolResult:
    """The financial model: the tender's fixed parameters (with their pages), the user's
    assumptions (saved ones under the request's), the server engine's figures. Read-only."""
    row = _tender(ctx, tender)
    view = _view(ctx, row)
    if view.suspension:
        raise ToolRefused(
            "publication_suspended", f"publication of {view.title} is suspended; no model", 409
        )
    model = library.model_tender(
        ctx.session, ctx.catalog, ctx.principal, row, model_type, assumptions
    )
    result = ModelCard(
        **model.model_dump(),
        title=view.title,
        provenance=_provenance(view),
        reliability=view.reliability,
    )
    lines = [f"{view.title} — {model_type} ({model.label})", "Fixed by the tender:"]
    for p in model.fixed:
        pages = ", ".join(f"{e.filename or e.document_id} p.{e.page_no}" for e in p.evidence)
        lines.append(
            f"  {p.label}: "
            + (
                f"{p.value}{' ' + p.unit if p.unit else ''}" + (f" [{pages}]" if pages else "")
                if p.value is not None
                else f"not fixed ({p.gap_reason})"
            )
        )
    lines.append("Assumptions (assumed, not from the tender):")
    for name in ASSUMPTION_NAMES:
        lines.append(f"  {name}: {getattr(model.assumptions, name)}")
    outputs = model.outputs
    if outputs is None:
        lines.append(model.note)
    else:
        lines.append(
            f"Project IRR {outputs.project_irr_percent}% · equity IRR "
            f"{outputs.equity_irr_percent}% · levelised cost INR "
            f"{outputs.levelised_cost_inr_per_kwh}/kWh · payback {outputs.payback_years} years "
            f"· capex INR {outputs.capex_crore} crore. {model.note}."
        )
        lines.append(
            "Cashflows (INR crore): year · generation MWh · revenue · O&M · debt service · "
            "tax · project cash · equity cash"
        )
        for r in outputs.cashflows:
            lines.append(
                f"  {r.year} · {r.generation_mwh:,.0f} · {r.revenue_crore:.2f} · "
                f"{r.om_crore:.2f} · {r.debt_service_crore:.2f} · {r.tax_crore:.2f} · "
                f"{r.project_cash_crore:.2f} · {r.equity_cash_crore:.2f}"
            )
    lines += [_provenance_text(view), _reliability_text(view.reliability), AUTHORITY_NOTE]
    return ToolResult(result, "\n".join(lines), resource_tenant_id=row.tenant_id)


def save_model_assumptions(
    ctx: ToolContext,
    tender: str,
    assumptions: dict[str, Any],
    model_type: str = "power_project_finance",
) -> ToolResult:
    """Keep the user's assumptions for a tender; returns what was saved. Never a canonical
    fact, never in the published view."""
    row = _tender(ctx, tender)
    if not assumptions:
        raise ToolRefused("validation_failed", "nothing to save", 422)
    saved = library.upsert_assumptions(ctx.session, ctx.principal, row, model_type, assumptions)
    result = SavedAssumptions(
        tender_id=row.id,
        model_type=model_type,
        assumptions=dict(saved.assumptions),
        saved_at=datetime.now(UTC),
    )
    return ToolResult(
        result,
        f"Saved for {row.title}: "
        + ", ".join(f"{k}={v}" for k, v in saved.assumptions.items())
        + f"\n{AUTHORITY_NOTE}",
        resource_tenant_id=row.tenant_id,
    )


def my_watchlist(
    ctx: ToolContext,
    add: list[str] | None = None,
    remove: list[str] | None = None,
) -> ToolResult:
    """The tenders the user follows, with bid deadlines and days remaining; `add` and
    `remove` change the list first."""
    added = [
        library.watchlist_add(ctx.session, ctx.principal, _tender(ctx, ref)).tender_id
        for ref in add or []
    ]
    removed = [
        row.id
        for row in (_tender(ctx, ref) for ref in remove or [])
        if library.watchlist_remove(ctx.session, ctx.principal, row.id)
    ]
    tenders = library.watchlist(ctx.session, ctx.catalog, ctx.tenders, ctx.principal)
    result = WatchlistResult(added=added, removed=removed, tenders=tenders)
    lines = [f"Watching {len(tenders)} tender(s):"] + [
        f"- {t.title} [{t.tender_id}]"
        + (
            f": bid deadline {t.bid_deadline}"
            + (f" ({t.days_remaining} days)" if t.days_remaining is not None else "")
            if t.bid_deadline
            else ": no bid deadline reviewed"
        )
        for t in tenders
    ]
    lines.append(AUTHORITY_NOTE)
    return ToolResult(result, "\n".join(lines), resource_tenant_id=ctx.principal.tenant_id)


def ask_tender(ctx: ToolContext, tender: str, question: str) -> ToolResult:
    """One question about one tender (Stage 7, Block 5): the approved fact when the question
    names a field, otherwise an answer from retrieved pages with every quote located by the
    evidence resolver. The answer says its source and is never a fact."""
    row = _tender(ctx, tender)
    view = _view(ctx, row)
    if ctx.ask is None:
        raise ToolRefused("not_found", "the full-tender query is not configured here", 503)
    try:
        answer = ctx.ask.ask(ctx.session, row, question, created_by=ACTOR)
    except AskError as exc:
        raise ToolRefused("model_unavailable", str(exc), 502) from exc
    result = AskResult(**answer.model_dump(), title=view.title, provenance=_provenance(view))
    cited = "\n".join(
        f"  [{c.n}] {'located' if c.resolved else 'NOT LOCATED'}: “{c.quote}” — "
        f"{c.filename or c.document_id} p.{c.page_no}"
        + (f" clause {c.clause}" if c.clause else "")
        + (f" (version {c.version_no})" if c.version_no else "")
        for c in answer.citations
    )
    text = (
        f"{view.title}\nQ: {question}\nA ({answer.source}, {answer.mode}): {answer.answer}\n"
        + (f"{answer.amendment_note}\n" if answer.amendment_note else "")
        + (cited + "\n" if cited else "")
        + f"Citations located: {answer.citations_resolved} of {answer.citations_total}. "
        f"{AUTHORITY_NOTE}"
    )
    return ToolResult(result, text, resource_tenant_id=row.tenant_id)


# -- Block 6 c: status, changes, submissions, review links ---------------------------------


class StatusResult(TenderStatus):
    title: str


class SnapshotResult(TenderSnapshot):
    pass


class SubmitResult(BaseModel):
    tender_id: str
    slug: str | None
    version_no: int
    document_id: str
    created: bool
    status_hint: str


class ReviewLinkResult(BaseModel):
    tender_id: str
    reviewer_name: str
    url: str
    expires_at: datetime | None
    note: str


def _own_tender(ctx: ToolContext, ref: str) -> Tender:
    """A tender of the caller's own tenant (a submission or a review link never touches
    the library's)."""
    row = _tender(ctx, ref)
    if row.tenant_id != ctx.principal.tenant_id:
        raise ToolRefused("not_allowed", "this tender is the library's, not your tenant's", 403)
    return row


def get_status(ctx: ToolContext, tender: str) -> ToolResult:
    """Where a tender's reading stands (Block 6): per version its documents, runs and
    pending jobs; the review and publication state."""
    row = _tender(ctx, tender)
    status = tender_status(ctx.session, ctx.catalog, ctx.tenders, row)
    result = StatusResult(**status.model_dump(), title=row.title)
    lines = [
        f"{row.title}: {status.status}, type {status.tender_type} ({status.type_state}), "
        f"publication {status.publication}, extraction "
        f"{'done' if status.extraction_done else 'under way'}"
    ]
    for version in status.versions:
        docs = ", ".join(f"{d.filename} ({d.status})" for d in version.documents)
        pending = f"; pending: {', '.join(version.pending_jobs)}" if version.pending_jobs else ""
        lines.append(f"  v{version.version_no} {version.kind}: {version.stage}; {docs}{pending}")
    return ToolResult(result, "\n".join(lines), resource_tenant_id=row.tenant_id)


def get_changes(ctx: ToolContext, tender: str) -> ToolResult:
    """The changelog across a tender's versions with impacts (Block 6): the same answer as
    `list_changes`, under the name the plan gives it."""
    return list_changes(ctx, tender)


def submit_tender(
    ctx: ToolContext,
    source_url: str,
    tender_type: str | None = None,
    agency: str | None = None,
    title: str | None = None,
    external_ref: str | None = None,
) -> ToolResult:
    """A new tender from the official URL of its RfS (Block 6): fetched from the agency's
    own domain only, parsed, mapped, indexed and read; `get_status` says where it stands."""
    if ctx.submit is None:
        raise ToolRefused("not_found", "submissions are not configured here", 503)
    try:
        made = ctx.submit.submit_tender(
            ctx.session,
            source_url=source_url,
            tender_type=tender_type,
            agency=agency,
            title=title,
            external_ref=external_ref,
            created_by=ACTOR,
        )
    except SubmitError as exc:
        raise ToolRefused("validation_failed", str(exc), 422) from exc
    result = SubmitResult(
        tender_id=made.tender.id,
        slug=made.tender.slug,
        version_no=made.version.version_no,
        document_id=made.document.id,
        created=made.created,
        status_hint=f"get_status(tender='{made.tender.id}')",
    )
    text = (
        f"{'Submitted' if made.created else 'Already held'}: tender {made.tender.id} "
        f"({made.tender.title}), version {made.version.version_no}, document "
        f"{made.document.filename}. Ask get_status for progress. {AUTHORITY_NOTE}"
    )
    return ToolResult(result, text, resource_tenant_id=made.tender.tenant_id)


def submit_amendment(
    ctx: ToolContext,
    tender: str,
    source_url: str,
    kind: str,
    issued_on: str | None = None,
    force: bool = False,
) -> ToolResult:
    """A corrigendum, amendment or clarification from its official URL as the tender's
    next version (Block 6); a document that names another tender is refused unless forced."""
    if ctx.submit is None:
        raise ToolRefused("not_found", "submissions are not configured here", 503)
    row = _own_tender(ctx, tender)
    try:
        when = date.fromisoformat(issued_on) if issued_on else None
    except ValueError as exc:
        raise ToolRefused("validation_failed", f"issued_on: {exc}", 422) from exc
    try:
        made = ctx.submit.submit_amendment(
            ctx.session,
            row,
            kind=kind,
            source_url=source_url,
            issued_on=when,
            created_by=ACTOR,
            force=force,
        )
    except SubmitError as exc:
        raise ToolRefused("validation_failed", str(exc), 422) from exc
    result = SubmitResult(
        tender_id=row.id,
        slug=row.slug,
        version_no=made.version.version_no,
        document_id=made.document.id,
        created=made.created,
        status_hint=f"get_status(tender='{row.id}')",
    )
    text = (
        f"{'Filed' if made.created else 'Already held'}: version {made.version.version_no} "
        f"({kind}) of {row.title}, document {made.document.filename}. {AUTHORITY_NOTE}"
    )
    return ToolResult(result, text, resource_tenant_id=row.tenant_id)


def get_review_link(ctx: ToolContext, tender: str, reviewer_name: str) -> ToolResult:
    """A review link for a named reviewer (Block 6). The link is a credential for the
    reviewer alone: hand it over, store it nowhere."""
    if ctx.tokens is None:
        raise ToolRefused("not_found", "review links are not configured here", 503)
    row = _own_tender(ctx, tender)
    try:
        token = ctx.tokens.create_for(
            ctx.session, "tender", row.id, reviewer_name, created_by=ACTOR
        )
    except ValueError as exc:
        raise ToolRefused("validation_failed", str(exc), 422) from exc
    url = f"{ctx.public_base_url}/review/{token.token}"
    result = ReviewLinkResult(
        tender_id=row.id,
        reviewer_name=token.reviewer_name,
        url=url,
        expires_at=token.expires_at,
        note="A credential for the named reviewer: hand it over and store it nowhere else.",
    )
    text = (
        f"Review link for {token.reviewer_name} on {row.title}: {url} (expires "
        f"{token.expires_at:%Y-%m-%d}). {result.note}"
    )
    return ToolResult(result, text, resource_tenant_id=row.tenant_id)
