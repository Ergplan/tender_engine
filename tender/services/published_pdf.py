"""The published view as a PDF (Stage 5C): a cover, the facts by section with a reference
number each, the changelog, and an appendix of page references ([n] -> document, page,
quote). The same view gives the same document; only the file identifier the library
writes differs between two saves."""

import json
from typing import Any

import pymupdf

from tender.services.changelog import Changelog
from tender.services.published import PublishedField, PublishedTender

PAGE_W, PAGE_H = 595.0, 842.0  # A4 in points
MARGIN = 48.0
LINE = 13.0
FONT = "helv"
BOLD = "hebo"


class _Writer:
    def __init__(self) -> None:
        self.doc = pymupdf.open()  # type: ignore[no-untyped-call]
        self.page: Any = None
        self.y = PAGE_H
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = MARGIN

    def line(self, text: str, *, size: float = 10.0, bold: bool = False, indent: float = 0) -> None:
        width = PAGE_W - 2 * MARGIN - indent
        lines = _wrap(text, width, size)
        for piece in lines:
            if self.y + size * 1.3 > PAGE_H - MARGIN:
                self._new_page()
            self.page.insert_text(
                (MARGIN + indent, self.y + size),
                piece,
                fontsize=size,
                fontname=BOLD if bold else FONT,
            )
            self.y += size * 1.35

    def gap(self, points: float = LINE) -> None:
        self.y += points

    def bytes(self) -> bytes:
        self.doc.set_metadata(
            {
                "title": "Published tender view",
                "author": "Tender Intelligence Engine",
                "creator": "tender.services.published_pdf",
                "producer": "tender.services.published_pdf",
                "creationDate": "",
                "modDate": "",
            }
        )
        out: bytes = self.doc.tobytes(garbage=3, deflate=True)  # type: ignore[no-untyped-call]
        self.doc.close()  # type: ignore[no-untyped-call]
        return out


def _wrap(text: str, width: float, size: float) -> list[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if pymupdf.get_text_length(trial, fontname=FONT, fontsize=size) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    lines.append(current)
    return lines


def _value_text(field: PublishedField) -> str:
    if field.withdrawn:
        return f"withdrawn by version {field.version_no}"
    if field.status == "not_reviewed":
        where = (
            f" (likely page {field.gap.likely_page})" if field.gap and field.gap.likely_page else ""
        )
        return f"not reviewed{where}"
    if field.value is None:
        return "the document does not state it"
    text = (
        field.value if isinstance(field.value, str) else json.dumps(field.value, ensure_ascii=False)
    )
    return (
        f"{text} {field.unit}" if field.unit and not isinstance(field.value, dict | list) else text
    )


def render_pdf(published: PublishedTender, changelog: Changelog | None = None) -> bytes:
    writer = _Writer()
    writer.line(published.title, size=16, bold=True)
    writer.line(f"{published.issuing_agency} · {published.tender_type}", size=11)
    if published.external_ref:
        writer.line(published.external_ref, size=10)
    writer.gap()
    writer.line(f"Publication: {published.publication.state}", size=10, bold=True)
    if published.banner:
        writer.line(published.banner, size=10)
    reviewed = (
        published.reviewed_at.strftime("%Y-%m-%d %H:%M UTC") if published.reviewed_at else "—"
    )
    writer.line(
        f"Reviewed {reviewed} by {published.reviewer_role or '—'}, at version "
        f"{published.reviewed_version or '—'} of {published.current_version or '—'}",
        size=10,
    )
    if published.reliability and published.reliability.value_accuracy is not None:
        r = published.reliability
        writer.line(
            f"Reliability ({r.tender_type}): value accuracy {r.value_accuracy:.0%} on "
            f"{r.n_fields} fields, as of {r.as_of}",
            size=10,
        )
    writer.gap()
    writer.line(published.authority_note, size=9)

    references: list[tuple[int, str, int, str]] = []
    if published.suspension:
        writer.gap(2 * LINE)
        writer.line("Publication suspended", size=13, bold=True)
        writer.line(
            f"Version {published.suspension.version_no} ({published.suspension.kind}) is not yet "
            f"reviewed and touches: {', '.join(published.suspension.fields)}.",
            size=10,
        )
    for section in published.sections:
        writer.gap(2 * LINE)
        writer.line(section.label, size=13, bold=True)
        for field in section.fields:
            marks = []
            for item in field.evidence:
                references.append(
                    (
                        len(references) + 1,
                        item.filename or item.document_id,
                        item.page_no,
                        item.quote,
                    )
                )
                marks.append(f"[{len(references)}]")
            status = "" if field.status == "reviewed" else f" ({field.status.replace('_', ' ')})"
            writer.line(f"{field.label}{status}", size=10, bold=True)
            writer.line(f"{_value_text(field)} {' '.join(marks)}".strip(), size=10, indent=12)
            if field.version_no and field.set_by:
                writer.line(
                    f"set by version {field.version_no} ({field.set_by})"
                    + (
                        f", reviewed {str(field.reviewed_at)[:10]} by {field.reviewer_role}"
                        if field.reviewer_role
                        else ""
                    ),
                    size=8,
                    indent=12,
                )

    # A suspended tender publishes no values: the changelog's old and new values stay out too.
    if changelog is not None and published.suspension is None:
        writer.gap(2 * LINE)
        writer.line("Changelog across versions", size=13, bold=True)
        for version in changelog.versions:
            issued = f", issued {version.issued_on.isoformat()}" if version.issued_on else ""
            state = "reviewed" if version.reviewed else "not yet reviewed"
            writer.line(
                f"Version {version.version_no} · {version.kind}{issued} · {state}",
                size=10,
                bold=True,
            )
            for change in version.changes:
                after = (
                    "withdrawn"
                    if change.withdrawn
                    else json.dumps(change.after, ensure_ascii=False)
                )
                before = json.dumps(change.before, ensure_ascii=False)
                writer.line(f"{change.label}: {before} → {after}", size=9, indent=12)
            if version.pending:
                writer.line(
                    "Pending review, may touch: " + ", ".join(version.pending), size=9, indent=12
                )

    writer.gap(2 * LINE)
    writer.line("Appendix: page references", size=13, bold=True)
    if not references:
        writer.line("No evidence pages: nothing is published for this tender.", size=9)
    for number, filename, page_no, quote in references:
        writer.line(f"[{number}] {filename}, page {page_no}", size=9, bold=True)
        writer.line(f"“{quote}”", size=9, indent=12)
    return writer.bytes()
