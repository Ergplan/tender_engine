"""Window coverage of the corpus (Stage 7, Block 2 e): for every tender's current version,
which pages of each document the field groups' windows cover, which pages no group reads,
and which section-map sections no window touches. No model call, nothing written.

  python -m scripts.window_coverage               every tender (not superseded)
  python -m scripts.window_coverage --min-pages 300
  python -m scripts.window_coverage --json out.json

A page outside every window is still seen by nobody: the engine only reads what a group
asked for. Front matter (cover, table of contents) and standard formats are expected
there; a substantive section is not.
"""

import argparse
import json
import sys
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import agent.models  # noqa: F401  (registers the agent pass tables on Base.metadata)
from core.models import Section
from core.services.section_map import normalise_kind
from scripts.ingest_tenders import build_services
from tender.models import Tender
from tender.services.packs import build_registry, schema_name
from tender.services.versioning import groups_for_role

# Sections of these kinds carry no field of their own; a window not touching them is fine.
FRONT_MATTER = {"cover_and_notice", "table_of_contents", "formats_and_annexures", "other"}


def coverage(session: Session, services: Any, tender: Tender) -> list[dict[str, Any]]:
    schemas, catalog = build_registry()
    compiled = catalog.get(tender.tender_type)
    schema = schemas.get(schema_name(tender.tender_type), compiled.schema.version)
    group_names = [g.name for g in schema.groups if not (g.derived or g.imported)]
    entries = services.tenders.versions(session, tender)
    current = max(entries, key=lambda e: e.version.version_no) if entries else None
    if current is None:
        return []
    rows: list[dict[str, Any]] = []
    for link, document in current.documents:
        if document.status != "parsed" or not document.page_count:
            continue
        groups_for_doc = [
            name for name in groups_for_role(compiled, link.role) if name in group_names
        ] or group_names
        windows, shared = services.extract.plan_windows(session, document, schema, groups_for_doc)
        covered: set[int] = set()
        for pages in windows.values():
            covered.update(pages)
        all_pages = set(range(1, document.page_count + 1))
        uncovered = sorted(all_pages - covered)
        sections = session.execute(
            select(Section.start_page, Section.end_page, Section.heading, Section.kind)
            .where(Section.document_id == document.id, Section.tenant_id == tender.tenant_id)
            .order_by(Section.start_page)
        ).all()
        untouched = [
            {"heading": heading, "kind": kind, "pages": f"{start}-{end}"}
            for start, end, heading, kind in sections
            if not any(start <= p <= end for p in covered)
        ]
        substantive = [s for s in untouched if s["kind"] not in FRONT_MATTER]
        # A section is a real miss only when some group of this document's role routes to
        # its kind: the engine reads fields, not the whole document, and a technical
        # specification chapter no field comes from is left unread on purpose.
        routed_kinds = {
            normalise_kind(kind)
            for g in schema.groups
            if g.name in groups_for_doc
            for kind in g.routing.section_kinds
        }
        routed_untouched = [s for s in substantive if normalise_kind(s["kind"]) in routed_kinds]
        rows.append(
            {
                "tender": tender.slug or tender.id,
                "type": tender.tender_type,
                "document": document.filename,
                "role": link.role,
                "pages": document.page_count,
                "groups": len(groups_for_doc),
                "covered": len(covered),
                "coverage": round(len(covered) / document.page_count, 4),
                "uncovered_pages": uncovered,
                "windows_sent": len(shared),
                "pages_sent": sum(len(w.pages) for w in shared),
                "sections": len(sections),
                "sections_untouched": untouched,
                "substantive_untouched": len(substantive),
                "routed_untouched": routed_untouched,
            }
        )
    return rows


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-pages", type=int, default=0)
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)
    services = build_services()
    rows: list[dict[str, Any]] = []
    with services.session_factory() as session:
        tenders = session.scalars(
            select(Tender).where(Tender.status != "superseded").order_by(Tender.slug)
        ).all()
        for tender in tenders:
            rows.extend(
                r for r in coverage(session, services, tender) if r["pages"] >= args.min_pages
            )
    print(
        "| Tender | Document | Role | Pages | Groups | Covered | Sent | "
        "Untouched substantive sections |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        covered = f"{r['covered']} ({r['coverage'] * 100:.0f}%)"
        sent = f"{r['pages_sent']} in {r['windows_sent']}"
        print(
            f"| {r['tender']} | {r['document'][:40]} | {r['role']} | {r['pages']} | "
            f"{r['groups']} | {covered} | {sent} | {r['substantive_untouched']} |"
        )
    kinds = Counter(s["kind"] for r in rows for s in r["sections_untouched"])
    total_pages = sum(r["pages"] for r in rows)
    total_covered = sum(r["covered"] for r in rows)
    print()
    print(
        f"documents: {len(rows)}; pages: {total_pages}; covered: {total_covered} "
        f"({(total_covered / total_pages * 100) if total_pages else 0:.1f}%)"
    )
    print(f"untouched sections by kind: {dict(kinds.most_common())}")
    routed = [(r["tender"], r["document"], s) for r in rows for s in r["routed_untouched"]]
    print(f"untouched sections of a kind some group routes to: {len(routed)}")
    for tender, document, section in routed:
        where = f"{tender} {document[:30]} p{section['pages']}"
        print(f"  {where} {section['kind']} {section['heading'][:60]}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as out:
            json.dump(rows, out, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
