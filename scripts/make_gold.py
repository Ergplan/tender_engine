"""Management command: turn a completed review into a gold record.

  python -m scripts.make_gold --tender <slug>      (make gold TENDER=<slug>)

Run after the owner confirms the review is trustworthy; not automatic on completion. Writes
evals/gold/<type>/<slug>.yaml, then regenerates the reliability report and the review log.
"""

import argparse
import sys

from sqlalchemy import select

from core.config import Settings
from core.db import make_engine, make_session_factory
from evals import report
from evals.gold import NoCompletedReview, build_gold, write_gold
from tender.models import Tender
from tender.services.packs import load_catalog


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tender", required=True, help="tender slug (or id)")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args(argv[1:])
    settings = Settings()
    catalog = load_catalog()
    with make_session_factory(make_engine(settings))() as session:
        tender = session.scalar(
            select(Tender).where(
                (Tender.slug == args.tender) | (Tender.id == args.tender),
                Tender.tenant_id == settings.tenant_id,
            )
        )
        if tender is None:
            raise SystemExit(f"no tender with slug {args.tender!r}")
        try:
            record = build_gold(session, catalog, tender)
        except NoCompletedReview as exc:
            raise SystemExit(str(exc)) from exc
    path = write_gold(record)
    decided = sum(1 for f in record.fields if f.decision)
    print(
        f"wrote {path}: {decided} decided field(s) of {len(record.fields)}, "
        f"version {record.reviewed_version}"
    )
    if not args.no_report:
        return report.main(["report"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
