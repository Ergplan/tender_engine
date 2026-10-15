"""Freshness of the corpus: each tender's source page is read again, the files it lists
are compared with the documents held, and new or changed files are reported.

Report only. Nothing is ingested: a new amendment must be reviewed before it changes a
canonical value, so the check tells the owner what to fetch and never fetches it into the
corpus. A file is "new" when the page lists a document whose content is not held under any
name; "changed" when it is listed under a filename the tender holds but with other content;
"unchanged" when its content is held, whatever it is called now. The comparison is by
sha256 of the file as served, so a re-posted file with the same bytes is not a change.

The check runs weekly as a job (`JOB_KIND`), which queues the next one when it is done,
and on demand from the management command or `POST /api/v1/admin/freshness`. Each
tender's comparison is recorded in the audit log (`ACTION`), which the dashboard route
and the report read.
"""

import hashlib
import io
import logging
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx2
import yaml
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import AuditLog, Document, Job
from core.services import audit, jobs
from tender.models import Tender, TenderVersion, TenderVersionDocument

log = logging.getLogger("tender.freshness")
ACTOR = "freshness"
ACTION = "source_freshness"
JOB_KIND = "source_freshness"
DOCUMENT_SUFFIXES = (".pdf", ".xlsx", ".xls", ".docx", ".doc", ".zip", ".rar")
# Pages captured by hand (role nit) are the corpus's own files, never listed by the agency.
OWN_ROLES = ("nit",)
MAX_FILE_BYTES = 50_000_000
TIMEOUT_SECONDS = 60.0
# Some agency sites answer a bare client with an error page.
USER_AGENT = "Mozilla/5.0 (compatible; tender-engine freshness check)"
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


class Listed(BaseModel):
    """One document the source page lists, or one a held document's own URL points at."""

    url: str
    filename: str
    sha256: str | None = None
    size: int | None = None
    # When the content is held under another filename: that name.
    held_as: str | None = None
    # The URL is a held document's own (`document.source_url`), not a link on the page.
    own_url: bool = False
    # A zip: how many files it holds and how many of them the corpus holds already.
    members: int | None = None
    members_held: int | None = None
    error: str | None = None


class SourceCheck(BaseModel):
    """One tender's page against the documents held."""

    tender_id: str
    slug: str | None
    page_url: str | None
    checked_at: datetime
    reachable: bool
    error: str | None = None
    listed: int = 0
    held: int = 0
    new: list[Listed] = []
    changed: list[Listed] = []
    unreadable: list[Listed] = []
    # Listed on the pages of two or more tenders in the same check: the agency's furniture
    # (a brochure, an integrity pact, a query format), not this tender's document.
    site_wide: list[Listed] = []
    unchanged: int = 0
    # Held filenames the page no longer lists (and whose content it lists under no name).
    not_listed: list[str] = []

    @property
    def stale(self) -> bool:
        return bool(self.new or self.changed)


class Held(BaseModel):
    sha256: str
    source_url: str | None = None


def source_pages(root: Path) -> dict[str, str]:
    """Per tender slug, the agency page its manifest names (`notice_url`, else a `source`
    that is a URL). Read from the tender folders, which the containers mount read-only."""
    pages: dict[str, str] = {}
    for path in sorted(root.glob("*/*/manifest.yaml")):
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        source = str(raw.get("source") or "")
        url = raw.get("notice_url") or (source if source.startswith("http") else None)
        if raw.get("slug") and url:
            pages[str(raw["slug"])] = str(url)
    return pages


def listed_documents(page_url: str, body: str) -> list[tuple[str, str]]:
    """(url, filename) of every document link on the page, each once, in page order."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href in HREF.findall(body):
        url = urljoin(page_url, href.strip())
        path = urlsplit(url).path
        filename = unquote(path.rsplit("/", 1)[-1])
        if not filename.lower().endswith(DOCUMENT_SUFFIXES) or url in seen:
            continue
        seen.add(url)
        found.append((url, filename))
    return found


class FreshnessChecker:
    def __init__(
        self,
        tenant_id: str,
        *,
        tenders_root: Path,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._root = tenders_root
        self._transport = transport

    def _client(self) -> httpx2.Client:
        return httpx2.Client(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            transport=self._transport,
        )

    # --- what is held --------------------------------------------------------------------

    def held_documents(self, session: Session, tender: Tender) -> dict[str, Held]:
        """filename -> (sha256, own URL) of the documents of every version of the tender,
        the corpus's own captures left out."""
        rows = session.execute(
            select(Document.filename, Document.sha256, Document.source_url)
            .join(TenderVersionDocument, TenderVersionDocument.document_id == Document.id)
            .join(TenderVersion, TenderVersion.id == TenderVersionDocument.tender_version_id)
            .where(
                TenderVersion.tender_id == tender.id,
                TenderVersion.tenant_id == self._tenant_id,
                TenderVersionDocument.tenant_id == self._tenant_id,
                Document.tenant_id == self._tenant_id,
                TenderVersionDocument.role.not_in(OWN_ROLES),
            )
        )
        return {filename: Held(sha256=sha, source_url=url) for filename, sha, url in rows}

    # --- one tender ----------------------------------------------------------------------

    def check(self, session: Session, tender: Tender, page_url: str | None) -> SourceCheck:
        """The page's document links, and the own URL of every held document that has one
        (a file's URL rather than the page's), each fetched and hashed."""
        now = datetime.now(UTC)
        held = self.held_documents(session, tender)
        result = SourceCheck(
            tender_id=tender.id,
            slug=tender.slug,
            page_url=page_url,
            checked_at=now,
            reachable=False,
            held=len(held),
        )
        by_sha = {doc.sha256: name for name, doc in held.items()}
        listed: list[tuple[str, str, bool]] = []
        with self._client() as client:
            if page_url is None:
                result.error = "no source page in the tender's manifest"
            else:
                try:
                    response = client.get(page_url)
                    response.raise_for_status()
                    result.reachable = True
                    listed = [
                        (url, name, False)
                        for url, name in listed_documents(page_url, response.text)
                    ]
                except httpx2.HTTPError as exc:
                    result.error = f"{type(exc).__name__}: {exc}"
            on_page = {url for url, _, _ in listed}
            for name, doc in held.items():
                url = doc.source_url or ""
                if url.lower().endswith(DOCUMENT_SUFFIXES) and url not in on_page:
                    listed.append((url, name, True))
                    on_page.add(url)
            result.listed = len(listed)
            seen_shas: set[str] = set()
            for url, filename, own in listed:
                item = Listed(url=url, filename=filename, own_url=own)
                try:
                    item.sha256, item.size, members = self._hash(client, url, filename)
                except httpx2.HTTPError as exc:
                    item.error = f"{type(exc).__name__}: {exc}"
                    result.unreadable.append(item)
                    continue
                except ValueError as exc:
                    item.error = str(exc)
                    result.unreadable.append(item)
                    continue
                seen_shas.add(item.sha256)
                if members is not None:
                    item.members = len(members)
                    item.members_held = sum(1 for sha in members if sha in by_sha)
                    seen_shas.update(members)
                if item.sha256 in by_sha or (members and item.members_held == item.members):
                    result.unchanged += 1
                elif filename in held:
                    item.held_as = filename
                    result.changed.append(item)
                else:
                    result.new.append(item)
        # Only a page that was read can fail to list a file; without one, a held document
        # is simply unverified (its own URL, if any, was tried above).
        if result.reachable:
            result.not_listed = sorted(
                name for name, doc in held.items() if doc.sha256 not in seen_shas
            )
        return result

    @staticmethod
    def _hash(client: httpx2.Client, url: str, filename: str) -> tuple[str, int, list[str] | None]:
        """sha256 and size of the file as served; for a zip, the sha256 of each member too
        (an agency posts an amendment with its revised annexures as one archive)."""
        digest = hashlib.sha256()
        size = 0
        archive = filename.lower().endswith(".zip")
        body = bytearray()
        with client.stream("GET", url) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise ValueError(f"larger than {MAX_FILE_BYTES} bytes; not hashed")
                digest.update(chunk)
                if archive:
                    body.extend(chunk)
        members: list[str] | None = None
        if archive:
            try:
                with zipfile.ZipFile(io.BytesIO(body)) as zipped:
                    members = [
                        hashlib.sha256(zipped.read(info)).hexdigest()
                        for info in zipped.infolist()
                        if not info.is_dir()
                    ]
            except zipfile.BadZipFile:
                members = None
        return digest.hexdigest(), size, members

    # --- every tender, recorded ----------------------------------------------------------

    def check_all(self, session: Session, *, created_by: str = ACTOR) -> list[SourceCheck]:
        """Check every tender of the tenant and record each comparison in the audit log. A
        new file listed on the pages of two or more tenders is the agency's furniture, set
        apart as `site_wide`."""
        pages = source_pages(self._root)
        results = [
            self.check(session, tender, pages.get(tender.slug or ""))
            for tender in session.scalars(
                select(Tender)
                .where(Tender.tenant_id == self._tenant_id, Tender.status != "superseded")
                .order_by(Tender.slug)
            )
        ]
        listed_by: dict[str, set[str]] = {}
        for result in results:
            for item in result.new:
                if item.sha256:
                    listed_by.setdefault(item.sha256, set()).add(result.tender_id)
        for result in results:
            furniture = [i for i in result.new if i.sha256 and len(listed_by[i.sha256]) > 1]
            if furniture:
                result.site_wide = furniture
                result.new = [i for i in result.new if i not in furniture]
            audit.record(
                session,
                tenant_id=self._tenant_id,
                actor=created_by,
                action=ACTION,
                table_name="tender",
                row_id=result.tender_id,
                after=result.model_dump(mode="json"),
            )
            session.commit()
            if result.stale:
                log.warning(
                    "%s: %s new, %s changed on %s",
                    result.slug,
                    len(result.new),
                    len(result.changed),
                    result.page_url,
                )
        return results


def latest(session: Session, tenant_id: str) -> list[SourceCheck]:
    """The last recorded check of every tender, by slug."""
    rows = session.scalars(
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant_id, AuditLog.action == ACTION)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    found: dict[str, SourceCheck] = {}
    for row in rows:
        if row.row_id not in found and row.after:
            found[row.row_id] = SourceCheck.model_validate(row.after)
    return sorted(found.values(), key=lambda check: check.slug or "")


# --- the weekly job --------------------------------------------------------------------------


def ensure_scheduled(session: Session, tenant_id: str, *, created_by: str = ACTOR) -> bool:
    """Queue a check, due now, unless one is queued or running. Called when the worker
    starts. Returns whether one was queued."""
    pending = session.scalar(
        select(Job.id)
        .where(
            Job.tenant_id == tenant_id,
            Job.kind == JOB_KIND,
            Job.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    if pending is not None:
        return False
    jobs.enqueue(session, tenant_id=tenant_id, kind=JOB_KIND, payload={}, created_by=created_by)
    session.commit()
    return True


def job_handlers(checker: FreshnessChecker, tenant_id: str, interval_days: float) -> dict[str, Any]:
    """The `source_freshness` job: check every tender, then queue the next check
    `interval_days` later (none when the interval is 0, or when the job was queued on
    demand with `repeat: false`)."""

    def source_freshness(session: Session, payload: dict[str, Any]) -> None:
        checker.check_all(session, created_by=str(payload.get("created_by") or ACTOR))
        if interval_days > 0 and payload.get("repeat", True):
            jobs.enqueue(
                session,
                tenant_id=tenant_id,
                kind=JOB_KIND,
                payload={},
                created_by=ACTOR,
                delay_seconds=interval_days * 86400,
            )
            session.commit()

    return {JOB_KIND: source_freshness}


# --- the report ------------------------------------------------------------------------------


def report_text(checks: list[SourceCheck], generated_at: datetime) -> str:
    stale = [c for c in checks if c.stale]
    lines = [
        "# Freshness report",
        "",
        f"Generated {generated_at:%Y-%m-%d %H:%M} UTC from the last `source_freshness` check "
        "of each tender (`tender/services/freshness.py`): the agency's page read again, every "
        "document it lists hashed and compared with the documents held. Report only; nothing "
        "listed here has been ingested.",
        "",
        f"Tenders checked: {len(checks)}; with new or changed files: {len(stale)}; "
        f"unreachable: {sum(1 for c in checks if not c.reachable)}.",
        "",
        "| Tender | Checked | Page | Listed | Held | New | Changed | Unchanged | "
        "No longer listed |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in checks:
        page = "unreachable" if not c.reachable else "ok"
        if c.error and not c.reachable:
            page = c.error if c.page_url is None else "unreachable"
        lines.append(
            f"| {c.slug or c.tender_id} | {c.checked_at:%Y-%m-%d %H:%M} | {page} | {c.listed} | "
            f"{c.held} | {len(c.new)} | {len(c.changed)} | {c.unchanged} | {len(c.not_listed)} |"
        )
    for c in checks:
        if not (c.new or c.changed or c.unreadable or c.not_listed or c.site_wide):
            continue
        lines += ["", f"## {c.slug or c.tender_id}", ""]
        if c.page_url:
            lines.append(f"Page: {c.page_url}")
            lines.append("")
        for title, items in (
            ("New", c.new),
            ("Changed", c.changed),
            ("Unreadable", c.unreadable),
            ("Listed on other tenders' pages as well (the agency's own files)", c.site_wide),
        ):
            if not items:
                continue
            lines.append(f"**{title}**")
            lines.append("")
            for item in items:
                detail = f"sha256 {item.sha256[:12]}…, {item.size} bytes" if item.sha256 else ""
                if item.members is not None:
                    detail += f"; zip of {item.members} file(s), {item.members_held} held"
                if item.held_as:
                    detail += f"; held as {item.held_as} with other content"
                if item.own_url:
                    detail += "; the document's own URL, not a link on the page"
                if item.error:
                    detail += item.error.splitlines()[0]
                lines.append(f"- [{item.filename}]({item.url}) — {detail}")
            lines.append("")
        if c.not_listed:
            lines.append("**Held, no longer listed on the page**")
            lines.append("")
            lines += [f"- {name}" for name in c.not_listed]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report(checks: list[SourceCheck], path: Path) -> str:
    text = report_text(checks, datetime.now(UTC))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text
