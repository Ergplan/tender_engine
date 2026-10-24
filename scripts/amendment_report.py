"""Every change the corpus's real amendments register, by class (Stage 7, Block 3 c), and
the review round each later version opened. No model call, nothing written.

  python -m scripts.amendment_report
  python -m scripts.amendment_report --json out.json
"""

import argparse
import json
import sys
from collections import Counter
from typing import Any

from sqlalchemy import select

import agent.models  # noqa: F401
from scripts.ingest_tenders import build_services
from tender.models import ReviewToken, Tender
from tender.services.amendments import tender_amendments
from tender.services.packs import build_registry


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)
    services = build_services()
    schemas, catalog = build_registry()
    rows: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    with services.session_factory() as session:
        tenders = session.scalars(
            select(Tender).where(Tender.status != "superseded").order_by(Tender.slug)
        ).all()
        for tender in tenders:
            try:
                view = tender_amendments(
                    session, catalog, services.tenders, services.review, schemas, tender
                )
            except Exception as exc:  # a tender without a readable review is reported
                print(f"{tender.slug}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            rounds = session.scalars(
                select(ReviewToken).where(
                    ReviewToken.object_type == "tender",
                    ReviewToken.object_id == tender.id,
                    ReviewToken.from_version.is_not(None),
                )
            ).all()
            opened = {t.from_version: t for t in rounds}
            for version in view.versions:
                token = opened.get(version.version_no)
                row = {
                    "tender": tender.slug,
                    "version_no": version.version_no,
                    "kind": version.kind,
                    "issued_on": version.issued_on.isoformat() if version.issued_on else None,
                    "documents": [d.filename for d in version.documents],
                    "changes": len(version.changes),
                    "by_class": version.by_class,
                    "decided": version.decided,
                    "undecided": version.undecided,
                    "changes_decided": sum(1 for c in version.changes if c.changes_decided),
                    "with_impacts": sum(1 for c in version.changes if c.impacts),
                    "round": None
                    if token is None
                    else {
                        "opened": token.created_at.isoformat(),
                        "completed": token.completed_at.isoformat() if token.completed_at else None,
                        "revoked": token.revoked_at is not None,
                    },
                }
                rows.append(row)
                totals.update(version.by_class)
    print(
        "| Tender | Version | Kind | Issued | Changes | By class | Decided | "
        "Replaces decided | Impacts | Round |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        classes = ", ".join(f"{k} {v}" for k, v in r["by_class"].items()) or "-"
        rnd = "-" if r["round"] is None else ("completed" if r["round"]["completed"] else "open")
        print(
            f"| {r['tender']} | v{r['version_no']} | {r['kind']} | {r['issued_on'] or '-'} | "
            f"{r['changes']} | {classes} | {r['decided']} | {r['changes_decided']} | "
            f"{r['with_impacts']} | {rnd} |"
        )
    print()
    print(f"later versions: {len(rows)}; changes by class: {dict(totals)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as out:
            json.dump(rows, out, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
