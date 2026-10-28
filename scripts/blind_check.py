"""Block 4 as an unreviewed check (the owner's decision of 2026-10-27): what the engine's
reading of the blind set shows without a reviewer. No accuracy is measured here, because
nobody has said what the right values are; the figures are the ones a reading carries on
its own.

  python -m scripts.blind_check --only recpdcl-bikaner-v-part-a,sjvn-wind-4-600mw
  python -m scripts.blind_check --only … --json out.json --md out.md

Per tender, from the live candidates of its versions (the latest valued version of each
field, as the extraction summary picks them):

- evidence location: fields with a value whose quote the resolver located on its page;
- the confidence distribution of the fields with a value, by the reviewer screen's bands
  (high at or above 0.8, medium at or above 0.5, low below), with the located share of
  each band: a high-confidence reading whose quote was not found is the thing to look at;
- rule validation: every deterministic rule run on the readings shown, passed and failed
  (errors send the field to review, warnings are only shown), and the rules that failed;
- type classification: the classifier's answer on the tender's main document (one model
  call, `classify_type/v1`) against the type the manifest gave, and its band;
- amendment linking: every document of a later version linked by `link_amendment` from its
  own first pages, against the tender it was ingested under (linked to it, asked, or linked
  elsewhere), with the method and the confidence;
- change classes: every change the amendments view registers, by class, per version.

Nothing is written. A tender with an unfinished run is reported as incomplete.
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import agent.models  # noqa: F401  (registers every table on Base.metadata)
from core.models import ExtractionRun
from core.services.review_state import FieldState
from evals.runner import RESULTS_ROOT, confidence_band
from scripts.ingest_tenders import Services, build_services
from tender.models import Tender
from tender.services.amendment_link import AmendmentLink, link_amendment
from tender.services.amendments import tender_amendments
from tender.services.packs import build_registry
from tender.services.tenders import OBJECT_TYPE

BANDS = ("high", "medium", "low")
ARTIFACTS = Path(__file__).resolve().parents[1] / "docs" / "reports" / "stage-7-artifacts"


@dataclass
class FieldReading:
    path: str
    section: str
    version_no: int
    confidence: float
    located: bool
    status: str
    rules: list[tuple[str, bool, str]] = field(default_factory=list)  # name, passed, severity


@dataclass
class LinkCheck:
    version_no: int
    kind: str | None
    filename: str
    role: str
    outcome: str  # linked_to_own | ask | linked_elsewhere | error
    method: str
    confidence: float
    references_found: int
    reason: str


@dataclass
class TenderCheck:
    slug: str
    manifest_type: str
    versions: int
    documents: int
    pages: int
    runs: int
    unfinished_runs: int
    cost_usd: Decimal
    fields: int
    readings: list[FieldReading] = field(default_factory=list)
    classification: dict[str, Any] | None = None
    links: list[LinkCheck] = field(default_factory=list)
    changes_by_version: list[dict[str, Any]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.unfinished_runs == 0 and self.runs > 0


# -- pure parts (tested) -------------------------------------------------------------------


def band_table(readings: list[FieldReading]) -> dict[str, dict[str, int]]:
    """Per band: fields with a value, and how many of them are located."""
    out = {band: {"answered": 0, "located": 0} for band in BANDS}
    for reading in readings:
        band = confidence_band(reading.confidence)
        if band not in out:
            out[band] = {"answered": 0, "located": 0}
        out[band]["answered"] += 1
        out[band]["located"] += int(reading.located)
    return out


def rule_table(readings: list[FieldReading]) -> dict[str, Any]:
    """Rules run over the readings shown: passed, failed (by severity), the failing rules
    with their counts, and the fields in `needs_review`."""
    rules_run = passed = errors = warnings = 0
    failing: Counter[str] = Counter()
    for reading in readings:
        for name, ok, severity in reading.rules:
            rules_run += 1
            if ok:
                passed += 1
                continue
            failing[f"{name} ({severity})"] += 1
            if severity == "error":
                errors += 1
            else:
                warnings += 1
    return {
        "rules_run": rules_run,
        "passed": passed,
        "failed_errors": errors,
        "failed_warnings": warnings,
        "failing_rules": dict(failing.most_common()),
        "fields_needs_review": sum(1 for r in readings if r.status == "needs_review"),
    }


def link_outcome(link: AmendmentLink, own_tender_id: str) -> str:
    if link.state == "linked":
        return "linked_to_own" if link.tender_id == own_tender_id else "linked_elsewhere"
    return "ask"


def classification_outcome(manifest_type: str, classification: dict[str, Any] | None) -> str:
    """`agree`, `agree_unsure`, `differ`, `differ_unsure`, `unknown` or `not_run`."""
    if not classification:
        return "not_run"
    state = classification.get("state")
    if state == "unknown":
        return "unknown"
    same = classification.get("tender_type") == manifest_type
    if state == "unsure":
        return "agree_unsure" if same else "differ_unsure"
    return "agree" if same else "differ"


def rate(part: int, whole: int) -> str:
    return "-" if whole == 0 else f"{100 * part / whole:.1f}%"


# -- collection ------------------------------------------------------------------------------


def _readings(
    services: Services, session: Session, tender: Tender
) -> tuple[list[FieldReading], int]:
    compiled = services.catalog.get(tender.tender_type)
    entries = services.tenders.versions(session, tender)
    chosen: dict[str, tuple[int, FieldState]] = {}
    for entry in entries:
        number = entry.version.version_no
        state = services.review.for_object(session, OBJECT_TYPE, tender.id, number)
        for item in state.fields:
            valued = item.candidate is not None and item.candidate.value is not None
            if valued or item.field_path not in chosen:
                chosen[item.field_path] = (number, item)
    derived = {section.name for section in compiled.sections if section.derived}
    readings: list[FieldReading] = []
    fields = 0
    for spec in compiled.fields:
        if spec.section in derived:
            continue
        fields += 1
        picked = chosen.get(spec.path)
        if picked is None:
            continue
        number, shown = picked
        candidate = shown.candidate
        if candidate is None or candidate.value is None:
            continue
        readings.append(
            FieldReading(
                path=spec.path,
                section=spec.section,
                version_no=number,
                confidence=candidate.confidence,
                located=any(span.char_start is not None for span in candidate.evidence),
                status=candidate.status,
                rules=[(v.rule_name, v.passed, v.severity) for v in candidate.validation],
            )
        )
    return readings, fields


def check_tender(services: Services, session: Session, tender: Tender) -> TenderCheck:
    entries = services.tenders.versions(session, tender)
    documents = {document.id: document for entry in entries for _, document in entry.documents}
    runs = list(
        session.scalars(
            select(ExtractionRun).where(
                ExtractionRun.tenant_id == tender.tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.object_id == tender.id,
            )
        )
    )
    readings, fields = _readings(services, session, tender)
    check = TenderCheck(
        slug=tender.slug or tender.id,
        manifest_type=tender.tender_type,
        versions=len(entries),
        documents=len(documents),
        pages=sum(document.page_count or 0 for document in documents.values()),
        runs=len(runs),
        unfinished_runs=sum(1 for run in runs if run.status != "validated"),
        cost_usd=sum((run.cost_usd for run in runs), Decimal(0)),
        fields=fields,
        readings=readings,
    )
    # Classification: the classified document of the first version, the RfS first.
    first = entries[0] if entries else None
    if first is not None:
        classified = [
            (link.role, document) for link, document in first.documents if document.classification
        ]
        classified.sort(key=lambda pair: (pair[0] != "rfs", -(pair[1].page_count or 0)))
        if classified:
            role, document = classified[0]
            found = dict(document.classification or {})
            check.classification = {
                "filename": document.filename,
                "role": role,
                "tender_type": found.get("tender_type"),
                "confidence": found.get("confidence"),
                "state": found.get("state"),
                "outcome": classification_outcome(tender.tender_type, found),
            }
    # Amendment linking: every document of a later version, from its own pages.
    for entry in entries[1:]:
        for link_row, document in entry.documents:
            try:
                link = link_amendment(session, tender.tenant_id, document.id)
                outcome = link_outcome(link, tender.id)
                method, confidence, refs, reason = (
                    link.method,
                    link.confidence,
                    len(link.references_found),
                    link.reason,
                )
            except (LookupError, ValueError) as exc:
                outcome, method, confidence, refs, reason = "error", "none", 0.0, 0, str(exc)
            check.links.append(
                LinkCheck(
                    version_no=entry.version.version_no,
                    kind=entry.version.kind,
                    filename=document.filename,
                    role=link_row.role,
                    outcome=outcome,
                    method=method,
                    confidence=confidence,
                    references_found=refs,
                    reason=reason,
                )
            )
    # Change classes from the amendments view.
    schemas, catalog = build_registry()
    try:
        view = tender_amendments(
            session, catalog, services.tenders, services.review, schemas, tender
        )
    except Exception as exc:  # the view needs every version read; say so instead
        check.changes_by_version.append({"error": f"{type(exc).__name__}: {exc}"})
    else:
        for version in view.versions:
            check.changes_by_version.append(
                {
                    "version_no": version.version_no,
                    "kind": version.kind,
                    "issued_on": version.issued_on.isoformat() if version.issued_on else None,
                    "changes": len(version.changes),
                    "by_class": dict(version.by_class),
                }
            )
    return check


# -- rendering -------------------------------------------------------------------------------


def as_json(checks: list[TenderCheck]) -> dict[str, Any]:
    out: dict[str, Any] = {"generated": datetime.now(UTC).isoformat(), "tenders": []}
    for check in checks:
        answered = len(check.readings)
        located = sum(1 for r in check.readings if r.located)
        out["tenders"].append(
            {
                "slug": check.slug,
                "manifest_type": check.manifest_type,
                "complete": check.complete,
                "versions": check.versions,
                "documents": check.documents,
                "pages": check.pages,
                "runs": check.runs,
                "unfinished_runs": check.unfinished_runs,
                "cost_usd": float(check.cost_usd),
                "fields": check.fields,
                "answered": answered,
                "located": located,
                "evidence_location_rate": (located / answered) if answered else None,
                "answer_rate": (answered / check.fields) if check.fields else None,
                "bands": band_table(check.readings),
                "rules": rule_table(check.readings),
                "unlocated_high": [
                    r.path
                    for r in check.readings
                    if confidence_band(r.confidence) == "high" and not r.located
                ],
                "classification": check.classification,
                "links": [vars(link) for link in check.links],
                "changes_by_version": check.changes_by_version,
            }
        )
    return out


def render(checks: list[TenderCheck]) -> str:
    lines = [
        "# Block 4 check: the blind set read without a reviewer",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by "
        "`python -m scripts.blind_check`. Candidates only; no value here has been reviewed, "
        "and no accuracy is claimed.",
        "",
        "## Readings",
        "",
        "| Tender | Type (manifest) | Complete | Versions | Docs | Pages | Fields | With a value "
        "| Located | Evidence-location rate | Answer rate | Cost USD |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    total_answered = total_located = total_fields = 0
    for c in checks:
        answered = len(c.readings)
        located = sum(1 for r in c.readings if r.located)
        total_answered += answered
        total_located += located
        total_fields += c.fields
        lines.append(
            f"| {c.slug} | {c.manifest_type} | {'yes' if c.complete else 'no'} | {c.versions} | "
            f"{c.documents} | {c.pages} | {c.fields} | {answered} | {located} | "
            f"{rate(located, answered)} | {rate(answered, c.fields)} | {c.cost_usd:.2f} |"
        )
    lines.append(
        f"| **all** | | | | | | {total_fields} | {total_answered} | {total_located} | "
        f"{rate(total_located, total_answered)} | {rate(total_answered, total_fields)} | "
        f"{sum((c.cost_usd for c in checks), Decimal(0)):.2f} |"
    )
    lines += [
        "",
        "## Confidence distribution (fields with a value; located share of each band)",
        "",
        "| Tender | High | Medium | Low | Unlocated at high confidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in checks:
        bands = band_table(c.readings)
        cells = [
            f"{bands[b]['answered']} ({rate(bands[b]['located'], bands[b]['answered'])} located)"
            for b in BANDS
        ]
        unlocated = [
            r.path for r in c.readings if confidence_band(r.confidence) == "high" and not r.located
        ]
        lines.append(
            f"| {c.slug} | {cells[0]} | {cells[1]} | {cells[2]} | "
            f"{', '.join(f'`{p}`' for p in unlocated) or 'none'} |"
        )
    lines += [
        "",
        "## Rule validation",
        "",
        "| Tender | Rules run | Passed | Pass rate | Failed (error) | Failed (warning) | "
        "Fields in needs_review | Failing rules |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in checks:
        rules = rule_table(c.readings)
        failing = ", ".join(f"{k} ×{v}" for k, v in rules["failing_rules"].items()) or "none"
        lines.append(
            f"| {c.slug} | {rules['rules_run']} | {rules['passed']} | "
            f"{rate(rules['passed'], rules['rules_run'])} | {rules['failed_errors']} | "
            f"{rules['failed_warnings']} | {rules['fields_needs_review']} | {failing} |"
        )
    lines += [
        "",
        "## Type classification (the main document, against the manifest)",
        "",
        "| Tender | Manifest | Classifier | Confidence | Band | Outcome | Document |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in checks:
        k = c.classification
        if not k:
            lines.append(f"| {c.slug} | {c.manifest_type} | - | - | - | not_run | - |")
            continue
        lines.append(
            f"| {c.slug} | {c.manifest_type} | {k['tender_type']} | {k['confidence']} | "
            f"{k['state']} | {k['outcome']} | {k['filename']} |"
        )
    lines += [
        "",
        "## Amendment linking (each later document from its own pages, against the tender it "
        "was ingested under)",
        "",
        "| Tender | Version | Kind | Document | Outcome | Method | Confidence | References found |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    outcomes: Counter[str] = Counter()
    for c in checks:
        for link in c.links:
            outcomes[link.outcome] += 1
            lines.append(
                f"| {c.slug} | v{link.version_no} | {link.kind or '-'} | {link.filename} | "
                f"{link.outcome} | {link.method} | {link.confidence:.2f} | "
                f"{link.references_found} |"
            )
    lines.append("")
    lines.append(
        "Linking outcomes: " + (", ".join(f"{k} {v}" for k, v in outcomes.items()) or "none")
    )
    lines += [
        "",
        "## Change classes (the amendments view, per later version)",
        "",
        "| Tender | Version | Kind | Issued | Changes | By class |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    totals: Counter[str] = Counter()
    for c in checks:
        for row in c.changes_by_version:
            if "error" in row:
                lines.append(f"| {c.slug} | - | - | - | - | {row['error']} |")
                continue
            if row["version_no"] == 1:
                continue
            classes = ", ".join(f"{k} {v}" for k, v in row["by_class"].items()) or "-"
            totals.update(row["by_class"])
            lines.append(
                f"| {c.slug} | v{row['version_no']} | {row['kind'] or '-'} | "
                f"{row['issued_on'] or '-'} | {row['changes']} | {classes} |"
            )
    lines.append("")
    lines.append(
        "Changes by class over the set: "
        + (", ".join(f"{k} {v}" for k, v in totals.items()) or "none")
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="comma-separated tender slugs")
    parser.add_argument("--json", type=Path, default=ARTIFACTS / "block-4-check.json")
    parser.add_argument("--md", type=Path, default=ARTIFACTS / "block-4-check.md")
    # Block 7 b: the same JSON under evals/results/ as <stamp>-blind-check.json, where
    # evals.reliability (and so the MCP tool reliability_report) reads the latest one.
    parser.add_argument("--results-root", type=Path, default=RESULTS_ROOT)
    args = parser.parse_args(argv)
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    services = build_services()
    checks: list[TenderCheck] = []
    with services.session_factory() as session:
        for tender in services.tenders.all(session):
            if only and tender.slug not in only:
                continue
            services.tenders.refresh_status(session, tender)
            checks.append(check_tender(services, session, tender))
    text = render(checks)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.md.write_text(text, encoding="utf-8")
    payload = json.dumps(as_json(checks), indent=1, default=str)
    args.json.write_text(payload, encoding="utf-8")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    args.results_root.mkdir(parents=True, exist_ok=True)
    results_copy = args.results_root / f"{stamp}-blind-check.json"
    results_copy.write_text(payload, encoding="utf-8")
    print(text)
    print(f"written: {args.md}, {args.json}, {results_copy}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
