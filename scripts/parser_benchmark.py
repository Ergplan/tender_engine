"""Parser benchmark (Stage 7, Block 2 b): pdfplumber, Docling and (with a key) LlamaParse on
the hard set, `evals/parser_bench/hard_set.yaml`: evidence-location rate per layer, time
per page, and what each layer produced. No model call; nothing is written to the database.

  python -m scripts.parser_benchmark                      # pdfplumber and Docling
  python -m scripts.parser_benchmark --layers pdfplumber  # the baseline alone
  python -m scripts.parser_benchmark --json out.json

A quote is located when the evidence resolver finds it on the page text the layer
produced (the same call that locates a reviewer's or the model's quote). pdfplumber's
page is the one stored; Docling and LlamaParse read the page fresh from the stored PDF.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

import agent.models  # noqa: F401
from core.config import Settings
from core.db import make_engine, make_session_factory
from core.evidence.resolver import Match, PageText, resolve
from core.models import Document, Page
from core.parsing.docling import DoclingClient, DoclingUnavailable
from core.parsing.layers import LayerPage
from core.services.parse import _sub_pdf
from core.storage import make_storage

HARD_SET = Path(__file__).resolve().parents[1] / "evals" / "parser_bench" / "hard_set.yaml"


def layer_pdfplumber(session: Any, document: Document, page_no: int, tenant: str) -> dict:
    row = session.execute(
        select(Page.text, Page.char_boxes, Page.has_text_layer, Page.parser_layer).where(
            Page.document_id == document.id, Page.tenant_id == tenant, Page.page_no == page_no
        )
    ).one()
    text, boxes, has_layer, layer = row
    if layer != "pdfplumber":  # the stored page was re-read by another layer; recompute
        import io

        import pdfplumber

        from core.services.parse import _text_and_boxes

        data = make_storage(Settings()).get(document.storage_path)
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text, boxes = _text_and_boxes(pdf.pages[page_no - 1])
        has_layer = sum(1 for c in text if not c.isspace()) >= 50
    return {
        "page": PageText(page_no, text, boxes, True),
        "chars": len(text.strip()),
        "seconds": 0.0,
        "note": "stored" if has_layer else "stored (no text layer)",
    }


def layer_docling(client: DoclingClient, pdf: bytes, page_no: int, force_ocr: bool) -> dict:
    sub = _sub_pdf(pdf, [page_no])
    started = time.monotonic()
    try:
        result = client.convert(sub, filename=f"bench-{page_no}.pdf", force_ocr=force_ocr)
    except DoclingUnavailable as exc:
        return {
            "page": None,
            "chars": 0,
            "seconds": round(time.monotonic() - started, 1),
            "note": str(exc)[:120],
        }
    read: LayerPage | None = result.pages.get(1)
    if read is None or not read.items:
        return {"page": None, "chars": 0, "seconds": result.seconds, "note": "no text found"}
    text, boxes = read.text_and_boxes()
    return {
        "page": PageText(page_no, text, boxes, True),
        "chars": len(text.strip()),
        "seconds": result.seconds,
        "note": f"{sum(read.detail.get('items', {}).values())} items",
        "items": read.detail.get("items", {}),
    }


def located(page: PageText | None, quote: str) -> tuple[bool, float]:
    if page is None:
        return False, 0.0
    found = resolve(quote, page)
    if isinstance(found, Match):
        return True, found.score
    return False, found.best_score


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layers", default="pdfplumber,docling")
    parser.add_argument("--json", default="")
    parser.add_argument("--docling-url", default="")
    args = parser.parse_args(argv)
    layers = [x.strip() for x in args.layers.split(",") if x.strip()]
    settings = Settings()
    docling = None
    if "docling" in layers:
        url = args.docling_url or settings.docling_url
        if not url:
            print("docling: no DOCLING_URL; skipped", file=sys.stderr)
            layers.remove("docling")
        else:
            docling = DoclingClient(url, timeout_seconds=settings.docling_timeout_seconds)
    storage = make_storage(settings)
    hard = yaml.safe_load(HARD_SET.read_text(encoding="utf-8"))
    session_factory = make_session_factory(make_engine(settings), settings.tenant_id)
    rows: list[dict[str, Any]] = []
    with session_factory() as session:
        for group in ("scanned", "divider_pages", "tables"):
            for entry in hard.get(group) or []:
                document = session.scalar(
                    select(Document).where(
                        Document.sha256.like(entry["sha256_prefix"] + "%"),
                        Document.tenant_id == settings.tenant_id,
                    )
                )
                if document is None:
                    print(f"missing: {entry['document']}", file=sys.stderr)
                    continue
                pdf = storage.get(document.storage_path)
                for page in entry["pages"]:
                    page_no = page["page_no"]
                    per_layer: dict[str, dict[str, Any]] = {}
                    if "pdfplumber" in layers:
                        per_layer["pdfplumber"] = layer_pdfplumber(
                            session, document, page_no, settings.tenant_id
                        )
                    if docling is not None:
                        per_layer["docling"] = layer_docling(
                            docling, pdf, page_no, force_ocr=(group == "scanned")
                        )
                    for quote in page["quotes"]:
                        row = {
                            "group": group,
                            "document": entry["document"],
                            "page": page_no,
                            "quote": quote,
                        }
                        for name, result in per_layer.items():
                            ok, score = located(result["page"], quote)
                            row[name] = ok
                            row[f"{name}_score"] = round(score, 1)
                            row[f"{name}_seconds"] = result["seconds"]
                            row[f"{name}_chars"] = result["chars"]
                            row[f"{name}_note"] = result["note"]
                        rows.append(row)
                        print(
                            f"{group:13s} {entry['document'][:28]:28s} p{page_no:<4d} "
                            + " ".join(
                                f"{n}={'Y' if row[n] else 'n'}({row[n + '_score']:.0f})"
                                for n in per_layer
                            )
                            + f"  {quote[:60]!r}"
                        )
    print()
    for name in layers:
        for group in ("scanned", "divider_pages", "tables"):
            subset = [r for r in rows if r["group"] == group and name in r]
            if not subset:
                continue
            hits = sum(1 for r in subset if r[name])
            pages = {(r["document"], r["page"]) for r in subset}
            seconds = sum(
                {(r["document"], r["page"]): r[f"{name}_seconds"] for r in subset}.values()
            )
            print(
                f"{name:10s} {group:13s} located {hits}/{len(subset)} "
                f"({hits / len(subset) * 100:.0f}%) on {len(pages)} pages, "
                f"{seconds:.1f} s total, {seconds / max(len(pages), 1):.1f} s/page"
            )
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
