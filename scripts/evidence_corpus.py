"""Management command: the evidence resolver's corpus.

  python -m scripts.evidence_corpus run     [--dir tests/core/evidence_corpus] [--failures]
  python -m scripts.evidence_corpus export  [--dir tests/core/evidence_corpus]

`run` scores the resolver against the corpus and prints the pass rate, overall and per
category; this is the number every stage report gives. `export` adds real cases from the
app database: every quote that was not located at extraction, every near miss (located
with a score under 100) and every quote the exact matcher does not find, each with the
text and character boxes of its page. Existing cases and pages are kept.
"""

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

from core.evidence import PageText, resolve
from core.evidence.corpus import run_corpus, summarise

DEFAULT_DIR = Path("tests/core/evidence_corpus")


def export(directory: Path) -> int:
    # Imported here: `run` must work without a database.
    from sqlalchemy import select

    from core.config import Settings
    from core.db import make_engine, make_session_factory
    from core.models import Candidate, Document, EvidenceSpan, Page

    (directory / "pages").mkdir(parents=True, exist_ok=True)
    cases_path = directory / "real_cases.json"
    cases: list[dict[str, Any]] = (
        json.loads(cases_path.read_text(encoding="utf-8")) if cases_path.is_file() else []
    )
    seen = {(case["page"], case["quote"]) for case in cases}
    added = 0
    session_factory = make_session_factory(make_engine(Settings()))
    with session_factory() as session:
        rows = session.execute(
            select(EvidenceSpan, Candidate.field_path, Document.sha256, Document.filename)
            .join(Candidate, Candidate.id == EvidenceSpan.candidate_id)
            .join(Document, Document.id == EvidenceSpan.document_id)
            .order_by(Document.filename, EvidenceSpan.page_no, EvidenceSpan.id)
        ).all()
        pages: dict[tuple[str, int], PageText | None] = {}
        for span, field_path, sha256, filename in rows:
            key = (span.document_id, span.page_no)
            if key not in pages:
                row = session.execute(
                    select(Page.text, Page.char_boxes, Page.has_text_layer).where(
                        Page.document_id == span.document_id, Page.page_no == span.page_no
                    )
                ).one_or_none()
                pages[key] = PageText(span.page_no, row[0], row[1], row[2]) if row else None
            page = pages[key]
            if page is None:
                continue
            if span.char_start is None:
                category = "real_unlocated_at_extraction"
            elif span.match_score is not None and span.match_score < 100:
                category = "real_near_miss"
            elif getattr(resolve(span.quote, page), "method", None) != "exact":
                category = "real_not_exact"
            else:
                continue
            page_id = f"{sha256[:10]}-p{span.page_no}"
            if (page_id, span.quote) in seen:
                continue
            seen.add((page_id, span.quote))
            page_path = directory / "pages" / f"{page_id}.json.gz"
            if not page_path.exists():
                boxes = [
                    None if box is None else [round(float(value), 1) for value in box]
                    for box in page.char_boxes
                ]
                with gzip.open(page_path, "wt", encoding="utf-8") as handle:
                    json.dump({"text": page.text, "char_boxes": boxes}, handle)
            cases.append(
                {
                    "id": f"real-{len(cases) + 1:04d}",
                    "category": category,
                    "source": {"document": filename, "page_no": span.page_no, "field": field_path},
                    "page": page_id,
                    "page_no": span.page_no,
                    "quote": span.quote,
                    "expect": {"located": True},
                }
            )
            added += 1
    cases_path.write_text(json.dumps(cases, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"added {added} case(s); {len(cases)} real case(s) in {cases_path}")
    return 0


def run(directory: Path, show_failures: bool) -> int:
    results = run_corpus(directory)
    print(summarise(results))
    if show_failures:
        for result in results:
            if not result.passed:
                print(f"FAIL {result.case_id} [{result.category}] {result.detail}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="evidence_corpus", description=__doc__)
    parser.add_argument("command", choices=("run", "export"))
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--failures", action="store_true", help="list the failing cases")
    args = parser.parse_args(argv[1:])
    return export(args.dir) if args.command == "export" else run(args.dir, args.failures)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
