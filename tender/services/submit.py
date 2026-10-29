"""Submission for any caller (Stage 7, Block 6 a): a tender from one document, as a file or
as the official URL it is published at, and an amendment to a tender the engine holds. The
chain after it is the one the worker always runs (parse, section map, index); the
`tender_extract` job then waits until the version's documents are parsed (and, when the
caller named no type, until the classifier has answered) and starts the reading;
`GET /tenders/{id}/status` says where it stands.

A URL is fetched only from a domain on infra/source-domains.yaml (DECISIONS 2026-10-07):
the agency's own site, never a mirror. Nothing here writes a fact."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import unquote, urlparse

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Document, Job
from core.services import jobs
from core.services.ingest import IngestError, IngestService
from tender.models import Tender, TenderVersion, TenderVersionDocument
from tender.models.tender import TENDER_TYPES, VERSION_KINDS
from tender.services.amendment_link import link_amendment
from tender.services.source_domains import SourceAllowlist
from tender.services.tenders import TenderError, TenderService

log = logging.getLogger("submit")
ACTOR = "submit"
JOB_KIND = "tender_extract"
FETCH_TIMEOUT_S = 60.0
MAX_BYTES = 200 * 1024 * 1024
MAX_REDIRECTS = 5
USER_AGENT = "tender-engine/1.0 (+official sources only)"
# The generic procurement schema: read with the core groups while the type is unknown.
GENERIC_TYPE = "ipp"
WAIT_S = 30.0
MAX_WAITS = 240  # two hours of parsing at most


class SubmitError(Exception):
    pass


@dataclass(frozen=True)
class Fetched:
    filename: str
    data: bytes
    source_url: str
    retrieved_on: date


class Fetcher:
    """An official document by its URL: the host must be on the allowlist, and so must the
    host the request ends at after redirects."""

    def __init__(
        self,
        allowlist: SourceAllowlist | None = None,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._allowlist = allowlist or SourceAllowlist.load()
        self._transport = transport

    def fetch(self, url: str) -> Fetched:
        if not self._allowlist.admissible(url):
            raise SubmitError(
                f"{url}: the host is not an official source (infra/source-domains.yaml)"
            )
        current = url
        try:
            with httpx2.Client(
                timeout=FETCH_TIMEOUT_S,
                follow_redirects=False,
                headers={"User-Agent": USER_AGENT},
                transport=self._transport,
            ) as client:
                # Redirects by hand: every hop must be on the allowlist before it is
                # requested, not only the last one, so a listed site cannot bounce the
                # request into the deployment's own network.
                for _ in range(MAX_REDIRECTS + 1):
                    with client.stream("GET", current) as response:
                        if response.is_redirect:
                            target = str(response.url.join(response.headers["location"]))
                            if not self._allowlist.admissible(target):
                                raise SubmitError(
                                    f"{url}: redirected off the official source to {target}"
                                )
                            current = target
                            continue
                        if response.status_code != 200:
                            raise SubmitError(f"{url}: HTTP {response.status_code}")
                        data = _read_capped(response, url)
                        final = str(response.url)
                        break
                else:
                    raise SubmitError(f"{url}: more than {MAX_REDIRECTS} redirects")
        except httpx2.HTTPError as exc:
            raise SubmitError(f"{url}: {type(exc).__name__}: {exc}") from exc
        name = unquote(urlparse(final).path.rsplit("/", 1)[-1]) or "document.pdf"
        return Fetched(name, data, url, datetime.now(UTC).date())


def _read_capped(response: httpx2.Response, url: str) -> bytes:
    """The body, refused as soon as it passes MAX_BYTES (never held whole beyond it)."""
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise SubmitError(f"{url}: {declared} bytes is more than the {MAX_BYTES} allowed")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_BYTES:
            raise SubmitError(f"{url}: more than the {MAX_BYTES} bytes allowed")
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class Submission:
    tender: Tender
    version: TenderVersion
    document: Document
    created: bool


class SubmitService:
    def __init__(
        self,
        tenders: TenderService,
        ingest: IngestService,
        tenant_id: str,
        *,
        fetcher: Fetcher | None = None,
        run_mode: str = "batch",
    ) -> None:
        self._tenders = tenders
        self._ingest = ingest
        self._tenant_id = tenant_id
        self._fetcher = fetcher or Fetcher()
        self._run_mode = run_mode

    # -- a tender ------------------------------------------------------------------------

    def submit_tender(
        self,
        session: Session,
        *,
        filename: str | None = None,
        data: bytes | None = None,
        source_url: str | None = None,
        tender_type: str | None = None,
        agency: str | None = None,
        title: str | None = None,
        external_ref: str | None = None,
        issued_on: date | None = None,
        created_by: str,
        priority: bool = False,
    ) -> Submission:
        """A new tender from its first document. Without `tender_type` the classifier names
        it (one text call over the first pages) and the reading waits for its answer. A
        document the engine already holds under a tender returns that tender and starts
        nothing twice."""
        if tender_type is not None and tender_type not in TENDER_TYPES:
            raise SubmitError(f"unknown tender type {tender_type!r}; one of {list(TENDER_TYPES)}")
        document, _ = self._document(session, filename, data, source_url, created_by)
        held = self.tender_of(session, document)
        if held is not None:
            tender, version = held
            return Submission(tender, version, document, False)
        try:
            tender = self._tenders.create(
                session,
                tender_type=tender_type or GENERIC_TYPE,
                issuing_agency=agency or "(to be read)",
                external_ref=external_ref,
                title=title or document.filename,
                created_by=created_by,
                type_source="caller" if tender_type else "model",
                type_state="set" if tender_type else "unknown",
            )
            version = self._tenders.add_version(
                session, tender, document, "original", issued_on, created_by=created_by
            )
        except TenderError as exc:
            raise SubmitError(str(exc)) from exc
        if tender_type is None:
            jobs.enqueue(
                session,
                tenant_id=self._tenant_id,
                kind="classify_type",
                payload={
                    "document_id": document.id,
                    "tender_id": tender.id,
                    "created_by": created_by,
                },
                created_by=created_by,
            )
        self._queue_extract(
            session, tender, 1, created_by, priority, wait_for_type=tender_type is None
        )
        session.commit()
        return Submission(tender, version, document, True)

    # -- an amendment --------------------------------------------------------------------

    def submit_amendment(
        self,
        session: Session,
        tender: Tender,
        *,
        kind: str,
        filename: str | None = None,
        data: bytes | None = None,
        source_url: str | None = None,
        issued_on: date | None = None,
        summary_of_change: str | None = None,
        created_by: str,
        force: bool = False,
        priority: bool = False,
    ) -> Submission:
        """A corrigendum, amendment or clarification as the tender's next version. The
        document is parsed later, so its link check (does it name this tender?) runs in the
        `tender_extract` job once its pages exist; a document that names another tender is
        not read unless `force` says so."""
        if kind not in VERSION_KINDS or kind == "original":
            raise SubmitError("kind must be corrigendum, amendment or clarification")
        document, _ = self._document(session, filename, data, source_url, created_by)
        held = self.tender_of(session, document)
        if held is not None:
            if held[0].id != tender.id:
                raise SubmitError(
                    f"{document.filename} is already a document of tender {held[0].id}"
                )
            return Submission(tender, held[1], document, False)
        try:
            version = self._tenders.add_version(
                session,
                tender,
                document,
                kind,
                issued_on,
                created_by=created_by,
                summary_of_change=summary_of_change,
            )
        except TenderError as exc:
            raise SubmitError(str(exc)) from exc
        self._queue_extract(
            session, tender, version.version_no, created_by, priority, link_check=not force
        )
        session.commit()
        return Submission(tender, version, document, True)

    # -- helpers ---------------------------------------------------------------------------

    def tender_of(
        self, session: Session, document: Document
    ) -> tuple[Tender, TenderVersion] | None:
        row = session.execute(
            select(Tender, TenderVersion)
            .join(TenderVersion, TenderVersion.tender_id == Tender.id)
            .join(
                TenderVersionDocument, TenderVersionDocument.tender_version_id == TenderVersion.id
            )
            .where(
                TenderVersionDocument.document_id == document.id,
                Tender.tenant_id == self._tenant_id,
                Tender.status != "superseded",
            )
            .order_by(TenderVersion.version_no)
            .limit(1)
        ).first()
        return (row[0], row[1]) if row else None

    def _document(
        self,
        session: Session,
        filename: str | None,
        data: bytes | None,
        source_url: str | None,
        created_by: str,
    ) -> tuple[Document, bool]:
        if (data is None) == (source_url is None):
            raise SubmitError("send exactly one of a file and a source_url")
        retrieved_on: date | None = None
        if source_url is not None:
            fetched = self._fetcher.fetch(source_url)
            filename, data, retrieved_on = fetched.filename, fetched.data, fetched.retrieved_on
        assert data is not None
        try:
            return self._ingest.upload(
                session,
                filename=filename or "document.pdf",
                data=data,
                created_by=created_by,
                source_url=source_url,
                retrieved_on=retrieved_on,
            )
        except IngestError as exc:
            raise SubmitError(str(exc)) from exc

    def _queue_extract(
        self,
        session: Session,
        tender: Tender,
        version_no: int,
        created_by: str,
        priority: bool,
        *,
        wait_for_type: bool = False,
        link_check: bool = False,
    ) -> Job:
        return jobs.enqueue(
            session,
            tenant_id=self._tenant_id,
            kind=JOB_KIND,
            payload={
                "tender_id": tender.id,
                "version_no": version_no,
                "created_by": created_by,
                "mode": "sync" if priority else self._run_mode,
                "wait_for_type": wait_for_type,
                "link_check": link_check,
            },
            created_by=created_by,
            delay_seconds=WAIT_S,
        )


# -- the job -------------------------------------------------------------------------------


def job_handlers(
    tenders: TenderService, tenant_id: str
) -> dict[str, Callable[[Session, dict[str, Any]], None]]:
    """`tender_extract` {tender_id, version_no, created_by, mode, wait_for_type,
    link_check}: start the reading once the version's documents are parsed; until then,
    the job queues itself again WAIT_S later (a plain delay, not the failure backoff)."""

    def tender_extract(session: Session, payload: dict[str, Any]) -> None:
        tender = session.scalar(
            select(Tender).where(Tender.id == payload["tender_id"], Tender.tenant_id == tenant_id)
        )
        if tender is None:
            raise LookupError(f"tender {payload['tender_id']} not found")
        version_no = int(payload["version_no"])
        entry = next(
            (e for e in tenders.versions(session, tender) if e.version.version_no == version_no),
            None,
        )
        if entry is None:
            raise LookupError(f"tender {tender.id} has no version {version_no}")
        failed = [d.filename for _, d in entry.documents if d.status == "failed"]
        if failed:
            raise LookupError(f"document(s) failed to parse: {failed}")
        parsed = all(d.status == "parsed" for _, d in entry.documents)
        typed = not payload.get("wait_for_type") or not _classifying(session, tenant_id, entry)
        if not (parsed and typed):
            waited = int(payload.get("waited", 0)) + 1
            if waited > MAX_WAITS:
                raise LookupError("the documents were not parsed within two hours")
            jobs.enqueue(
                session,
                tenant_id=tenant_id,
                kind=JOB_KIND,
                payload={**payload, "waited": waited},
                created_by=str(payload.get("created_by") or ACTOR),
                delay_seconds=WAIT_S,
            )
            session.commit()
            return
        if payload.get("link_check") and version_no > 1:
            for _, document in entry.documents:
                link = link_amendment(session, tenant_id, document.id)
                if link.state == "linked" and link.tender_id != tender.id:
                    raise LookupError(
                        f"{document.filename} names tender {link.tender_id}, not {tender.id}; "
                        "submit it again with force=true to read it here"
                    )
        try:
            tenders.start_extraction(
                session,
                tender,
                version_no=version_no,
                created_by=str(payload.get("created_by") or ACTOR),
                mode=str(payload.get("mode") or "batch"),
            )
        except TenderError as exc:
            raise LookupError(str(exc)) from exc
        session.commit()

    return {JOB_KIND: tender_extract}


def _classifying(session: Session, tenant_id: str, entry: Any) -> bool:
    """A classification of the version's documents is still queued or running."""
    pending = session.scalar(
        select(Job.id).where(
            Job.tenant_id == tenant_id,
            Job.kind == "classify_type",
            Job.status.in_(("queued", "running")),
            Job.payload["document_id"].astext.in_([d.id for _, d in entry.documents]),
        )
    )
    return pending is not None
