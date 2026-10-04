"""Management command: fetch the published tender notice (NIT) of tenders whose RfS defers
its dates to it.

  python -m scripts.fetch_notices [--root /work/tenders] [--only slug,slug]

For every manifest with a `notice_url`, the agency's tender page is fetched, its
label and value pairs (publication date, pre-bid meeting, bid submission end, bid opening,
fees) are written, in page order, into a small PDF beside the page's HTML, and the PDF is
added to the manifest with role `nit`, attached to the tender's latest version: the page
shows the dates as they stand on the day it was fetched, after every extension.
Nothing on the page is interpreted here; the PDF is the page's own text, so the dates
are extracted from it, with evidence, like any other document.
"""

import argparse
import html
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

import pymupdf
import yaml

DEFAULT_ROOT = Path("/work/tenders")
USER_AGENT = "Mozilla/5.0 (tender-engine notice fetch)"
_TAG = re.compile(r"<[^>]+>")
_NOISE = re.compile(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", re.S)
# An innermost row: the tables on these pages are nested.
_ROW = re.compile(r"<tr\b(?:(?!<tr\b).)*?</tr>", re.S)
_CELL = re.compile(r"<td\b([^>]*)>(.*?)</td>", re.S)


def _clean(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).split())


def pairs_from_table_rows(page: str) -> list[tuple[str, str]]:
    """Label and value pairs from rows whose label cells are bold (`class="fw-bold"`), the
    layout of the SECI tender page. A row may hold two pairs."""
    pairs = []
    for row in _ROW.findall(_NOISE.sub("", page)):
        cells = _CELL.findall(row)
        for index, (attrs, body) in enumerate(cells[:-1]):
            if "fw-bold" in attrs:
                label, value = _clean(body), _clean(cells[index + 1][1])
                if label and value and "fw-bold" not in cells[index + 1][0]:
                    pairs.append((label, value))
    return pairs


def pairs_from_colon_labels(page: str) -> list[tuple[str, str]]:
    """Label and value pairs from text where a label ends with a colon and its value is the
    next piece of text, the layout of the NTPC NIT details page."""
    pieces = [
        " ".join(html.unescape(piece).split())
        for piece in _TAG.split(_NOISE.sub("", page))
        if piece.strip()
    ]
    pairs = []
    for label, value in zip(pieces, pieces[1:], strict=False):
        if label.endswith(":") and len(label) < 60 and value and not value.endswith(":"):
            pairs.append((label.rstrip(": "), value))
    return pairs


def notice_lines(agency: str, title: str, url: str, fetched_on: date, page: str) -> list[str]:
    pairs = pairs_from_table_rows(page) or pairs_from_colon_labels(page)
    if not pairs:
        raise ValueError(f"no label and value pairs found on {url}")
    lines = [
        f"{agency}: tender notice as published on the agency's tender page",
        f"Tender: {title}",
        f"Source: {url}",
        f"Retrieved on {fetched_on.isoformat()}. Dates are day-first (dd/mm/yyyy).",
        "",
    ]
    lines += [f"{label}: {value}" for label, value in pairs]
    return lines


def write_pdf(lines: list[str], path: Path) -> int:
    """The lines as a plain text PDF, wrapped at 95 characters. Returns the page count."""
    wrapped: list[str] = []
    for line in lines:
        while len(line) > 95:
            cut = line.rfind(" ", 0, 95)
            cut = cut if cut > 0 else 95
            wrapped.append(line[:cut])
            line = "    " + line[cut:].lstrip()
        wrapped.append(line)
    document: Any = pymupdf.open()
    per_page = 48
    for start in range(0, len(wrapped), per_page):
        page = document.new_page(width=595, height=842)
        for index, line in enumerate(wrapped[start : start + per_page]):
            page.insert_text((50, 60 + index * 15), line, fontsize=10)
    count = int(document.page_count)
    document.save(path)
    document.close()
    return count


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        data: bytes = response.read()
    return data.decode("utf-8", errors="replace")


def add_notice(manifest_path: Path, fetched_on: date, page: str | None = None) -> str | None:
    """Fetch and file the notice of one tender. Returns the PDF's name, or None when the
    manifest names no notice or already holds it."""
    manifest: dict[str, Any] = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    url = manifest.get("notice_url")
    name = f"Tender_notice_page_{manifest['slug']}.pdf"
    if not url or any(item["file"] == name for item in manifest["files"]):
        return None
    page = page if page is not None else fetch(url)
    folder = manifest_path.parent
    (folder / name.replace(".pdf", ".html")).write_text(page, encoding="utf-8")
    lines = notice_lines(manifest["agency"], manifest["title"], url, fetched_on, page)
    pages = write_pdf(lines, folder / name)
    manifest["files"].append(
        {
            "file": name,
            "role": "nit",
            "issued_on": None,
            "pages": pages,
            "attach_to": "latest",
            "source": url,
            "retrieved_on": fetched_on.isoformat(),
        }
    )
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=1000), encoding="utf-8"
    )
    return name


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="fetch_notices", description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--only", default="", help="comma-separated tender slugs")
    args = parser.parse_args(argv[1:])
    only = {slug.strip() for slug in args.only.split(",") if slug.strip()}
    for path in sorted(args.root.glob("*/*/manifest.yaml")):
        if only and path.parent.name not in only:
            continue
        try:
            name = add_notice(path, date.today())
        except Exception as exc:
            print(f"{path.parent.name}: failed, {exc}")
            continue
        if name:
            print(f"{path.parent.name}: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
