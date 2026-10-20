"""Import of award results from the RE-tender-results dataset (Stage 6).

Nothing from the dataset reaches the application unreviewed. Each source publication (a result
sheet, a CERC adoption order, an allocation) becomes one `award` object with its PDF ingested
through the normal path, one extraction run in mode `import` (no model, no `llm_call_log`), and
candidates holding the dataset's values with their quotes resolved by core's evidence resolver
on the page the dataset cites. Validation runs as for any candidate. A reviewer approves
against the PDF; only approved rows become canonical.

The importer enforces the source admissibility rule (DECISIONS.md, 2026-10-07): a source host
that is not on `infra/source-domains.yaml` stops the import before anything is written. It
checks that our sha256 of every file equals the dataset's before anything is written, and stops
at the first mismatch with nothing imported. It is safe to repeat: a publication already
imported from the same sha256 is skipped. The HTML registers are left out and counted, never
converted.
"""

import hashlib
import json
import re
import subprocess
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Candidate, EvidenceSpan, ExtractionRun, Page
from core.models.extraction import IMPORT_MODE
from core.services import audit
from core.services.extract import ExtractService
from core.services.ingest import IngestService
from core.services.parse import ParseService
from core.services.validate import ValidationService
from tender.models import Award, Tender
from tender.services.awards import AWARD_TYPE, FIELDS, OBJECT_TYPE
from tender.services.packs import Catalog
from tender.services.source_domains import SourceAllowlist, host_of

ACTOR = "results_import"
PROMPT_NAME = "import/re-tender-results"
PROMPT_VERSION = "v1"
DATASET_NAME = "RE-tender-results"
# The dataset's confidence is its verification tier; the cap in the extract service makes
# sure no imported row ranks above a located, validated reading.
CONFIDENCE = 0.8

PRICE_UNITS: dict[str, str | None] = {
    "": None,
    "INR/kWh": "inr_per_kwh",
    "INR/kg": "inr_per_kg",
    "INR/kg (average incentive)": "inr_per_kg",
    "months (PPA term)": "months_ppa_term",
    "INR/MW/month": "inr_per_mw_month",
    "INR/MW VGF": "inr_per_mw_vgf",
    "INR/MW/annum (total storage cost)": "inr_per_mw_annum",
    "INR (contract award value)": "inr_contract_value",
    "INR (2-year total charges)": "inr_two_year_charges",
}
CAPACITY_UNITS: dict[str, str | None] = {
    "": None,
    "MW": "mw",
    "kW": "kw",
    "MW/year": "mw_per_year",
    "MT/year": "mt_per_year",
    "MT (project quantity)": "mt",
    "MW manufacturing": "mw_manufacturing",
}
STATUSES: dict[str, str] = {
    "Awarded": "awarded",
    "Tariff adopted": "tariff_adopted",
    "L1 ranked; award not confirmed": "l1_ranked_award_not_confirmed",
    "Tariff adoption recorded": "tariff_adoption_recorded",
    "Empanelled": "empanelled",
    "Company register disclosure": "company_register_disclosure",
    "Partially adopted": "partially_adopted",
    "Historical award; not adopted in this order": "historical_award_not_adopted",
    "Published allocation": "published_allocation",
    "Award reported; not adopted in this order": "award_reported_not_adopted",
    "Selected": "selected",
    "Award in LoA; adoption quantity ambiguous": "adoption_quantity_ambiguous",
}
ALLOCATIONS: dict[str, str] = {
    "Published result": "published_result",
    "Base": "base",
    "Greenshoe": "greenshoe",
}
KINDS: dict[str, str] = {
    "Auction / LoA date": "auction_result",
    "CERC order date": "cerc_adoption_order",
    "Publication / order date": "allocation",
}
REGISTER_STATUS = "company_register_disclosure"
# How the publications name the procurer, longest first; the acronym is the fallback.
PROCURER_NAMES: dict[str, tuple[str, ...]] = {
    "SECI": ("Solar Energy Corporation of India", "SECI"),
    "NTPC": ("NTPC Limited", "NTPC"),
    "NHPC": ("NHPC Limited", "NHPC"),
    "SJVN": ("SJVN Limited", "SJVN"),
    "IREDA": ("Indian Renewable Energy Development Agency", "IREDA"),
}
# Words on the page that show what kind of publication it is, tried in order.
KIND_PHRASES: dict[str, tuple[str, ...]] = {
    "auction_result": (
        r"e-?\s?reverse auction",
        r"e-?RA\b",
        r"reverse auction",
        r"successful bidders?",
        r"list of (?:selected|successful)",
        r"\bresults?\b",
    ),
    "cerc_adoption_order": (
        r"adoption of (?:the )?tariff",
        r"petition no\.?",
        r"central electricity regulatory commission",
        r"\border\b",
    ),
    "allocation": (r"allocat\w+", r"empanel\w+", r"letter of award", r"\bLoA\b", r"\baward\w*"),
    "register": (r"register",),
}
MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_DATE_IN_TEXT = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})")
_SPACE = re.compile(r"\s+")
MIN_REFERENCE_CHARS = 6


class ResultsImportError(ValueError):
    """The import cannot go on: an inadmissible host, a hash mismatch, a value the
    mappings do not know. Nothing is worked around."""


@dataclass(frozen=True)
class Source:
    id: str
    url: str
    file: str
    name: str
    sha256: str
    kind: str
    checked: date
    text: str | None = None

    @property
    def is_pdf(self) -> bool:
        return self.kind.upper() == "PDF"


class Dataset:
    """The dataset as the importer reads it: the viewer's data.json (records and sources),
    the archived files, and the SECI research records that keep the RfS numbers."""

    def __init__(self, root: Path, *, commit: str | None = None) -> None:
        self.root = root
        viewer = root / "tender-results-viewer" / "public"
        data = json.loads((viewer / "data.json").read_text(encoding="utf-8"))
        self.as_of: str = str(data.get("asOf", ""))
        self.sources: list[Source] = [
            Source(
                id=str(item["id"]),
                url=str(item["url"]),
                file=str(item["file"]),
                name=str(item["name"]),
                sha256=str(item["sha256"]).lower(),
                kind=str(item["kind"]),
                checked=date.fromisoformat(str(item["checked"])),
                text=item.get("text"),
            )
            for item in data["sources"]
        ]
        self.records: list[dict[str, Any]] = list(data["records"])
        self.by_source: dict[str, list[dict[str, Any]]] = {}
        for record in self.records:
            self.by_source.setdefault(str(record["source"]), []).append(record)
        seci_path = root / "seci-data" / "records.json"
        seci = json.loads(seci_path.read_text(encoding="utf-8")) if seci_path.is_file() else []
        self.rfs_by_seci_id: dict[str, str] = {}
        for item in seci:
            reference = str(item.get("tender_reference") or "").strip()
            if reference:
                self.rfs_by_seci_id.setdefault(str(item["tender_id"]), reference)
        self.commit = commit or _commit_of(root)
        self._viewer = viewer

    @property
    def label(self) -> str:
        return f"{DATASET_NAME}@{self.commit}"

    def file_bytes(self, source: Source) -> bytes:
        return (self._viewer / source.file).read_bytes()

    def records_of(self, source: Source) -> list[dict[str, Any]]:
        return self.by_source.get(source.id, [])


def _commit_of(root: Path) -> str:
    """The short commit of the dataset clone: from git, or from the clone's own files
    where no git binary is at hand (the app containers)."""
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        pass
    git = root / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head[len("ref: ") :]
            ref_file = git / ref
            if ref_file.is_file():
                return ref_file.read_text(encoding="utf-8").strip()[:7]
            for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
                if line.endswith(f" {ref}"):
                    return line.split()[0][:7]
            raise ResultsImportError(f"{root}: ref {ref} not found")
        return head[:7]
    except OSError as exc:
        raise ResultsImportError(f"{root}: the dataset commit cannot be read: {exc}") from exc


@dataclass
class SourceOutcome:
    source_id: str
    name: str
    host: str
    # imported, already_imported, left_out_html, rejected_host
    action: str
    rows: int = 0
    rows_located: int = 0
    document_id: str | None = None
    award_id: str | None = None
    run_id: str | None = None
    tender_slug: str | None = None
    link_basis: str | None = None
    link_page: int | None = None
    # field name -> located (True), unlocated (False) or no value (None)
    fields: dict[str, bool | None] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)
    note: str = ""


@dataclass
class ImportReport:
    dataset: str
    as_of: str
    hosts: dict[str, bool]
    outcomes: list[SourceOutcome] = field(default_factory=list)

    def count(self, action: str) -> int:
        return sum(1 for o in self.outcomes if o.action == action)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "as_of": self.as_of,
            "hosts": self.hosts,
            "outcomes": [asdict(o) for o in self.outcomes],
        }

    def lines(self) -> list[str]:
        imported = [o for o in self.outcomes if o.action == "imported"]
        lines = [
            f"{self.dataset} (as of {self.as_of})",
            "hosts: "
            + ", ".join(
                f"{h} ({'ok' if ok else 'NOT ADMISSIBLE'})" for h, ok in self.hosts.items()
            ),
            f"imported {len(imported)}, already imported {self.count('already_imported')}, "
            f"HTML registers left out {self.count('left_out_html')} "
            f"({sum(o.rows for o in self.outcomes if o.action == 'left_out_html')} rows), "
            f"rejected hosts {self.count('rejected_host')}",
            f"rows imported {sum(o.rows for o in imported)}, "
            f"of which located on their page {sum(o.rows_located for o in imported)}",
            "linked to tenders: "
            + (
                ", ".join(
                    f"{o.tender_slug} ({o.link_basis}"
                    + (f", p.{o.link_page}" if o.link_page else "")
                    + f") <- {o.name}"
                    for o in imported
                    if o.tender_slug
                )
                or "none"
            ),
        ]
        for name in ("procurer", "reference", "result_kind", "result_date", "winners"):
            states = Counter(str(o.fields.get(name)) for o in imported)
            lines.append(
                f"{name}: located {states['True']}, unlocated {states['False']}, "
                f"no value {states['None']}"
            )
        statuses = Counter(status for o in imported for status in o.statuses.values())
        lines.append(
            "candidate statuses: " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items()))
        )
        return lines


class ResultsImporter:
    def __init__(
        self,
        *,
        ingest: IngestService,
        parse: ParseService,
        extract: ExtractService,
        validate: ValidationService,
        catalog: Catalog,
        allowlist: SourceAllowlist,
        tenant_id: str,
    ) -> None:
        self._ingest = ingest
        self._parse = parse
        self._extract = extract
        self._validate = validate
        self._catalog = catalog
        self._allowlist = allowlist
        self._tenant_id = tenant_id

    def run(
        self,
        session: Session,
        dataset: Dataset,
        *,
        created_by: str = ACTOR,
        only: Iterable[str] | None = None,
    ) -> ImportReport:
        """Import every PDF source of the dataset (or the ids in `only`). Stops before
        writing anything when a source host is not admissible; stops at the first file
        whose sha256 differs from the dataset's."""
        wanted = set(only) if only is not None else None
        sources = [s for s in dataset.sources if wanted is None or s.id in wanted]
        hosts = self._allowlist.hosts([s.url for s in sources])
        report = ImportReport(dataset=dataset.label, as_of=dataset.as_of, hosts=hosts)
        refused = sorted(host for host, ok in hosts.items() if not ok)
        if refused:
            for source in sources:
                if not hosts.get(host_of(source.url), False):
                    report.outcomes.append(
                        SourceOutcome(
                            source.id,
                            source.name,
                            host_of(source.url),
                            "rejected_host",
                            rows=len(dataset.records_of(source)),
                        )
                    )
            raise ResultsImportError(
                f"source host(s) not on the allowlist: {refused}. Nothing was imported; add "
                "the domain to infra/source-domains.yaml if it is the agency's own, or leave "
                "the source out."
            )
        # Every file's hash is checked before anything is written, so a mismatch anywhere
        # in the run leaves the database as it was.
        for source in sources:
            if not source.is_pdf:
                continue
            digest = hashlib.sha256(dataset.file_bytes(source)).hexdigest()
            if digest != source.sha256:
                raise ResultsImportError(
                    f"{source.name}: our sha256 {digest[:12]}… differs from the dataset's "
                    f"{source.sha256[:12]}…; nothing was imported"
                )
        tenders = self._tenders(session)
        for source in sources:
            records = dataset.records_of(source)
            outcome = SourceOutcome(
                source.id, source.name, host_of(source.url), "", rows=len(records)
            )
            report.outcomes.append(outcome)
            if not source.is_pdf:
                outcome.action = "left_out_html"
                outcome.note = "an HTML register page; not converted"
                continue
            existing = session.scalar(
                select(Award).where(
                    Award.tenant_id == self._tenant_id, Award.source_sha256 == source.sha256
                )
            )
            if existing is not None:
                outcome.action = "already_imported"
                outcome.award_id = existing.id
                outcome.document_id = existing.document_id
                continue
            self._import_source(session, dataset, source, records, tenders, outcome, created_by)
        return report

    def _tenders(self, session: Session) -> list[Tender]:
        return [
            tender
            for tender in session.scalars(
                select(Tender).where(
                    Tender.tenant_id == self._tenant_id,
                    Tender.external_ref.is_not(None),
                    Tender.status != "superseded",
                )
            )
            if tender.external_ref and len(tender.external_ref.strip()) >= MIN_REFERENCE_CHARS
        ]

    def _import_source(
        self,
        session: Session,
        dataset: Dataset,
        source: Source,
        records: list[dict[str, Any]],
        tenders: list[Tender],
        outcome: SourceOutcome,
        created_by: str,
    ) -> None:
        if not records:
            raise ResultsImportError(f"{source.name}: the dataset has no record for this source")
        document, _ = self._ingest.upload(
            session,
            filename=source.name,
            data=dataset.file_bytes(source),
            created_by=created_by,
            source_url=source.url,
            retrieved_on=source.checked,
        )
        if document.status != "parsed":
            # Parsed here, synchronously: the evidence is resolved against the pages now.
            # No section map: nothing reads this document with a model.
            self._parse.parse(session, document.id, map_sections=False)
        pages = {
            page_no: text
            for page_no, text in session.execute(
                select(Page.page_no, Page.text).where(
                    Page.document_id == document.id, Page.tenant_id == self._tenant_id
                )
            )
        }
        agency = str(records[0]["agency"])
        kind = _kind_of(records)
        reference = _reference_of(dataset, records)
        award = Award(
            tenant_id=self._tenant_id,
            created_by=created_by,
            document_id=document.id,
            source_id=source.id,
            source_sha256=source.sha256,
            source_url=source.url,
            source_name=source.name,
            dataset=dataset.label,
            procurer=agency,
            reference=reference,
            result_kind=kind,
            verification="; ".join(sorted({str(r["verification"]) for r in records})),
            row_count=len(records),
            status="imported",
        )
        session.add(award)
        session.flush()
        audit.record(
            session,
            tenant_id=self._tenant_id,
            actor=created_by,
            action="insert",
            table_name="award",
            row_id=award.id,
            after={
                "document_id": document.id,
                "source_id": source.id,
                "source_sha256": source.sha256,
                "dataset": dataset.label,
                "rows": len(records),
            },
        )
        compiled = self._catalog.get(AWARD_TYPE)
        now = datetime.now(UTC)
        run = ExtractionRun(
            tenant_id=self._tenant_id,
            created_by=created_by,
            document_id=document.id,
            object_type=OBJECT_TYPE,
            object_id=award.id,
            object_version=1,
            schema_name=compiled.schema.name,
            schema_version=compiled.schema.version,
            prompt_version=PROMPT_VERSION,
            groups=None,
            model=dataset.label,
            status="extracted",
            started_at=now,
            finished_at=now,
            mode=IMPORT_MODE,
        )
        session.add(run)
        session.flush()
        audit.record(
            session,
            tenant_id=self._tenant_id,
            actor=created_by,
            action="insert",
            table_name="extraction_run",
            row_id=run.id,
            after={"object_type": OBJECT_TYPE, "object_id": award.id, "mode": IMPORT_MODE},
        )
        cited = _cited_pages(records)
        prefer = [1, *[p for p in cited if p != 1]]
        prompt = (PROMPT_NAME, PROMPT_VERSION)
        verification = award.verification
        provenance = (
            f"From {dataset.label}, source {source.id} ({source.name}), checked "
            f"{source.checked:%d.%m.%Y}. {verification}."
        )

        def add(
            name: str, value: Any, quotes: list[tuple[int, str, int | None]], why: str
        ) -> Candidate:
            candidate = self._extract.import_candidate(
                session,
                run,
                FIELDS[name],
                value=value,
                confidence=CONFIDENCE,
                rationale=f"{why} {provenance}",
                quotes=quotes,
                prompt=prompt,
            )
            outcome.fields[name] = (
                None
                if value is None
                else any(span.char_start is not None for span in _spans(session, candidate))
            )
            return candidate

        # Procurer: the agency's name as the page prints it, else its acronym (unlocated).
        page_no, printed = _find_printed(
            pages, [re.escape(n) for n in PROCURER_NAMES.get(agency, (agency,))], prefer
        ) or (prefer[0], agency)
        add("procurer", agency, [(page_no, printed, None)], "The agency that published the result.")
        # Reference: the RfS number or the petition number, located where it is printed.
        found = _find_printed(pages, [re.escape(reference)], prefer)
        add(
            "reference",
            reference,
            [(*found, None) if found else (prefer[0], reference, None)],
            "The tender's RfS number (SECI research records) or the order's petition number.",
        )
        # Kind: the words that show it.
        found = _find_printed(pages, list(KIND_PHRASES[kind]), prefer)
        add(
            "result_kind",
            kind,
            [(*found, None) if found else (prefer[0], kind.replace("_", " "), None)],
            f"Classified from the dataset's date type ({records[0]['dateType']}) and statuses.",
        )
        # Date: the one most rows carry, as printed on the page.
        chosen, others = _date_of(records)
        if chosen is None:
            add(
                "result_date",
                None,
                [(prefer[0], "", None)],
                "The dataset gives no date for this publication.",
            )
        else:
            found = _find_printed(pages, _date_patterns(chosen), prefer)
            why = f"The {records[0]['dateType'].lower()} the dataset gives."
            if others:
                why += " Other dates in the dataset's rows: " + ", ".join(others) + "."
            add(
                "result_date",
                f"{chosen:%d.%m.%Y}",
                [(*found, None) if found else (prefer[0], f"{chosen:%d.%m.%Y}", None)],
                why,
            )
        # Winners: one row per record, each quoted by its bidder and its price (or capacity).
        rows: list[dict[str, Any]] = []
        quotes: list[tuple[int, str, int | None]] = []
        for index, record in enumerate(records, start=1):
            row, row_pages = _row_of(record)
            rows.append(row)
            cited_pages = row_pages or prefer[:1]
            bidder = str(record["bidder"]).strip()
            quotes.append((*_row_quote(pages, cited_pages, bidder, _printed_name), index))
            number = (
                record.get("price") if record.get("price") is not None else record.get("capacity")
            )
            if number is not None:
                quotes.append(
                    (*_row_quote(pages, cited_pages, float(number), _printed_number), index)
                )
        notes = [str(r.get("notes") or "").strip() for r in records]
        why = (
            f"{len(rows)} row(s) from the dataset's records for this publication; each row is "
            "quoted by its bidder and its price (its capacity where no price is given) on the "
            "page the dataset cites."
        )
        if any(notes):
            why += " Row notes: " + " | ".join(
                f"{i}: {n}" for i, n in enumerate(notes, start=1) if n
            )
        winners = add("winners", rows, quotes, why)
        # A row is located when every quote of it is (its bidder, and its number).
        row_located: dict[int, bool] = {}
        for span in _spans(session, winners):
            if span.ordinal is not None:
                row_located[span.ordinal] = (
                    row_located.get(span.ordinal, True) and span.char_start is not None
                )
        outcome.rows_located = sum(1 for ok in row_located.values() if ok)
        session.commit()
        self._validate.validate(session, run.id)
        outcome.statuses = {
            candidate.field_path.rsplit(".", 1)[1]: candidate.status
            for candidate in session.scalars(
                select(Candidate).where(
                    Candidate.extraction_run_id == run.id, Candidate.tenant_id == self._tenant_id
                )
            )
        }
        link = _link(dataset, records, pages, tenders)
        if link is not None:
            tender, basis, page_no_found = link
            award.tender_id = tender.id
            award.tender_link_basis = basis
            award.tender_link_page = page_no_found
            audit.record(
                session,
                tenant_id=self._tenant_id,
                actor=created_by,
                action="link_tender",
                table_name="award",
                row_id=award.id,
                after={"tender_id": tender.id, "basis": basis, "page": page_no_found},
            )
            outcome.tender_slug = tender.slug or tender.id
            outcome.link_basis = basis
            outcome.link_page = page_no_found
        session.commit()
        outcome.action = "imported"
        outcome.document_id = document.id
        outcome.award_id = award.id
        outcome.run_id = run.id


def _spans(session: Session, candidate: Candidate) -> list[EvidenceSpan]:
    return list(
        session.scalars(
            select(EvidenceSpan).where(
                EvidenceSpan.candidate_id == candidate.id,
                EvidenceSpan.tenant_id == candidate.tenant_id,
            )
        )
    )


def _kind_of(records: list[dict[str, Any]]) -> str:
    statuses = {str(r["status"]) for r in records}
    if statuses == {"Company register disclosure"}:
        return "register"
    date_types = {str(r["dateType"]) for r in records}
    kinds = {KINDS.get(d) for d in date_types}
    if None in kinds or len(kinds) != 1:
        raise ResultsImportError(f"unknown or mixed date type(s) {sorted(date_types)}")
    return str(next(iter(kinds)))


def _reference_of(dataset: Dataset, records: list[dict[str, Any]]) -> str:
    references = {str(r["reference"]).strip() for r in records}
    if len(references) != 1:
        raise ResultsImportError(f"one publication with several references: {sorted(references)}")
    reference = next(iter(references))
    return dataset.rfs_by_seci_id.get(reference, reference)


def _cited_pages(records: list[dict[str, Any]]) -> list[int]:
    pages: list[int] = []
    for record in records:
        for page_no in _pages_of(record.get("page")):
            if page_no not in pages:
                pages.append(page_no)
    return pages


def _pages_of(raw: Any) -> list[int]:
    """A page citation: an integer, or a range written 13–14 / 13-14."""
    if isinstance(raw, int):
        return [raw]
    if isinstance(raw, str):
        found = re.fullmatch(r"\s*(\d+)\s*[–\-]\s*(\d+)\s*", raw)
        if found:
            first, last = int(found.group(1)), int(found.group(2))
            return list(range(first, last + 1)) if last >= first else [first]
        if raw.strip().isdigit():
            return [int(raw.strip())]
    return []


def _mapped(table: dict[str, Any], raw: Any, what: str) -> Any:
    key = str(raw if raw is not None else "").strip()
    if key not in table:
        raise ResultsImportError(f"unknown {what} {key!r}; add it to the mapping")
    return table[key]


def _row_of(record: dict[str, Any]) -> tuple[dict[str, Any], list[int]]:
    row = {
        "bidder": str(record["bidder"]).strip(),
        "allocation": _mapped(ALLOCATIONS, record.get("allocation"), "allocation"),
        "capacity": _number(record.get("capacity")),
        "capacity_unit": _mapped(CAPACITY_UNITS, record.get("capacityUnit"), "capacity unit"),
        "price": _number(record.get("price")),
        "price_unit": _mapped(PRICE_UNITS, record.get("priceUnit"), "price unit"),
        "adopted_capacity": _number(record.get("adopted")),
        "adopted_price": _number(record.get("adoptedPrice")),
        "status": _mapped(STATUSES, record.get("status"), "status"),
        "notes": (str(record.get("notes") or "").strip() or None),
    }
    return row, _pages_of(record.get("page"))


def _number(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    return float(raw)


def _date_of(records: list[dict[str, Any]]) -> tuple[date | None, list[str]]:
    """The date most rows carry (the first date of a multi-date string), and the other
    date strings the rows give, for the note."""
    found: list[date] = []
    raw_strings: list[str] = []
    for record in records:
        raw = str(record.get("date") or "").strip()
        if not raw:
            continue
        raw_strings.append(raw)
        match = _DATE_IN_TEXT.search(raw)
        if match is None:
            continue
        day, month, year = (int(part) for part in match.groups())
        try:
            found.append(date(year, month, day))
        except ValueError:
            continue
    if not found:
        return None, sorted(set(raw_strings))
    chosen = Counter(found).most_common(1)[0][0]
    others = sorted({raw for raw in raw_strings if raw != f"{chosen:%d.%m.%Y}"})
    return chosen, others


def _date_patterns(day: date) -> list[str]:
    month = MONTHS[day.month - 1]
    short = month[:3]
    d, m, y = day.day, day.month, day.year
    return [
        rf"\b0?{d}[.\-/]0?{m}[.\-/]{y}\b",
        rf"\b0?{d}(?:st|nd|rd|th)?\s+(?:of\s+)?{month}\.?,?\s+{y}\b",
        rf"\b0?{d}(?:st|nd|rd|th)?\s+(?:of\s+)?{short}\.?,?\s+{y}\b",
        rf"\b{month}\s+0?{d}(?:st|nd|rd|th)?,?\s+{y}\b",
        rf"\b{short}\.?\s+0?{d}(?:st|nd|rd|th)?,?\s+{y}\b",
    ]


def _find_printed(
    pages: dict[int, str], patterns: list[str], prefer: list[int]
) -> tuple[int, str] | None:
    """The first pattern printed on a page, on the preferred pages first: the page and the
    text as printed, so the resolver finds it where it stands."""
    order = [*prefer, *sorted(p for p in pages if p not in prefer)]
    for pattern in patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        for page_no in order:
            text = pages.get(page_no)
            if not text:
                continue
            match = compiled.search(_SPACE.sub(" ", text))
            if match:
                return page_no, match.group(0)
    return None


def _row_quote(
    pages: dict[int, str], cited: list[int], wanted: Any, printed: Any
) -> tuple[int, str]:
    """The page among the cited ones (a range is several) where the bidder or the number
    is printed, with the text as printed; the first cited page and the plain form when
    none prints it, for the resolver to report."""
    for page_no in cited:
        text = pages.get(page_no, "")
        form = printed(text, wanted)
        plain = wanted if isinstance(wanted, str) else _plain(wanted)
        if form != plain or _printed_plain(text, plain):
            return page_no, form
    return cited[0], printed(pages.get(cited[0], ""), wanted)


def _printed_plain(text: str, plain: str) -> bool:
    return re.search(re.escape(plain), _SPACE.sub(" ", text), re.IGNORECASE) is not None


def _printed_name(text: str, name: str) -> str:
    """The bidder's name as the page prints it when a case-insensitive, space-tolerant
    match exists; else the dataset's spelling, for the resolver's fuzzy matchers."""
    pattern = r"\s*".join(re.escape(part) for part in name.split())
    match = re.search(pattern, _SPACE.sub(" ", text), re.IGNORECASE)
    return match.group(0) if match else name


def _printed_number(text: str, number: float) -> str:
    """The number in the form the page prints (2.41, 2.410, 380, 1,200.00 ...), else the
    plain form."""
    flat = _SPACE.sub(" ", text)
    forms: list[str] = []
    if float(number).is_integer():
        whole = int(number)
        forms += [f"{whole:,}", str(whole), f"{whole}.0", f"{whole}.00", f"{whole:,}.00"]
        forms.append(_indian(whole))
    forms += [_plain(number), f"{number:.2f}", f"{number:.3f}", f"{number:.4f}", f"{number:.1f}"]
    printed = [
        form
        for form in dict.fromkeys(forms)
        # Only a form that is the same number: a rounded print (2.4 for 2.41) is another value.
        if float(form.replace(",", "")) == float(number)
        and re.search(rf"(?<![\d.]){re.escape(form)}(?![\d.])", flat)
    ]
    # The longest print wins (380.0 over 380 when the page writes 380.0). Nothing printed:
    # the number itself, without loss, for the resolver to report as not located.
    return max(printed, key=len) if printed else _plain(number)


def _plain(number: float) -> str:
    """The number written without loss: 380 for a whole number, else its full repr."""
    return str(int(number)) if float(number).is_integer() else repr(float(number))


def _indian(whole: int) -> str:
    text = str(whole)
    if len(text) <= 3:
        return text
    head, tail = text[:-3], text[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def _link(
    dataset: Dataset,
    records: list[dict[str, Any]],
    pages: dict[int, str],
    tenders: list[Tender],
) -> tuple[Tender, str, int | None] | None:
    """The tender this publication belongs to: an exact match of the RfS number against
    tender.external_ref, else the tender number found verbatim in the page text (with its
    page). Never fuzzy."""
    reference = _reference_of(dataset, records)
    for tender in tenders:
        if tender.external_ref and tender.external_ref.strip() == reference:
            return tender, "rfs_number", None
    flat = {page_no: _SPACE.sub(" ", text) for page_no, text in pages.items()}
    for tender in tenders:
        wanted = _SPACE.sub(" ", str(tender.external_ref).strip())
        for page_no in sorted(flat):
            if wanted in flat[page_no]:
                return tender, "page_text", page_no
    return None
