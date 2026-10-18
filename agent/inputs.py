"""What the agent is given, and nothing else: the tender type, the field schema, and the
documents of the tender with the pages the section map names for each.

The page selection is the engine's own (`core.services.extract.select_pages` on the
document's section map and routing hints, group by group), so the agent starts where the
engine starts; `search_text` reaches every page beyond that. No candidate, gold value or
decision enters here."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from core.models import Document, Page, Section
from core.schemas import ExtractionSchema, FieldDef, KeyDef
from core.services.extract import select_pages
from tender.models import Tender, TenderVersion
from tender.services.packs import CompiledType
from tender.services.summary import SUMMARY_FIELD
from tender.services.tenders import TenderService


@dataclass(frozen=True)
class OfferedDocument:
    """One document of the pass, numbered from 1 in version order."""

    number: int
    document_id: str
    filename: str
    version_no: int
    version_kind: str
    role: str
    page_count: int
    # The pages the section map names for the schema's groups, in order.
    pages: tuple[int, ...]
    # (start_page, end_page, heading) of the document's sections.
    sections: tuple[tuple[int, int, str], ...]


@dataclass(frozen=True)
class OfferedGroup:
    name: str
    label: str
    guidance: str
    fields: tuple[FieldDef, ...]


@dataclass(frozen=True)
class PassInputs:
    tender_type: str
    schema: ExtractionSchema
    documents: tuple[OfferedDocument, ...]
    groups: tuple[OfferedGroup, ...]

    def document(self, number: int) -> OfferedDocument | None:
        return next((d for d in self.documents if d.number == number), None)

    def field(self, path: str) -> FieldDef | None:
        return next((f for g in self.groups for f in g.fields if f.path == path), None)

    @property
    def field_paths(self) -> list[str]:
        return [f.path for g in self.groups for f in g.fields]


class InputsError(ValueError):
    """The pass cannot be run on this tender as it stands."""


def build_inputs(
    session: Session,
    tenders: TenderService,
    compiled: CompiledType,
    settings: Settings,
    tender: Tender,
    version_no: int,
) -> PassInputs:
    """The documents of every version up to `version_no`, each with the pages the section
    map names, and the fields the agent is asked for: every group read from pages, less
    the summary (written from the record, not read)."""
    entries = [e for e in tenders.versions(session, tender) if e.version.version_no <= version_no]
    if not entries or entries[-1].version.version_no != version_no:
        raise InputsError(f"tender {tender.id} has no version {version_no}")
    schema = compiled.schema
    documents: list[OfferedDocument] = []
    for entry in entries:
        for link, document in entry.documents:
            if document.status != "parsed":
                raise InputsError(
                    f"document {document.filename!r} is {document.status}, not parsed"
                )
            documents.append(
                _offered(
                    session,
                    settings,
                    schema,
                    document,
                    entry.version,
                    link.role,
                    len(documents) + 1,
                )
            )
    if not documents:
        raise InputsError("the tender has no document")
    return PassInputs(
        tender_type=tender.tender_type,
        schema=schema,
        documents=tuple(documents),
        groups=asked_groups(compiled),
    )


def asked_groups(compiled: CompiledType) -> tuple[OfferedGroup, ...]:
    """The fields the agent is asked for, by group: every group read from pages, less the
    summary (written from the record, not read). The API's `unsubmitted` list and the pass
    use this one rule."""
    schema = compiled.schema
    groups = tuple(
        OfferedGroup(
            name=group.name,
            label=compiled.section(group.name).label,
            guidance=group.guidance,
            fields=tuple(f for f in schema.fields_in(group.name) if f.path != SUMMARY_FIELD),
        )
        for group in schema.groups
        if not group.derived
    )
    return tuple(g for g in groups if g.fields)


def asked_fields(compiled: CompiledType) -> list[str]:
    return [f.path for g in asked_groups(compiled) for f in g.fields]


def _offered(
    session: Session,
    settings: Settings,
    schema: ExtractionSchema,
    document: Document,
    version: TenderVersion,
    role: str,
    number: int,
) -> OfferedDocument:
    sections = list(
        session.execute(
            select(Section.start_page, Section.end_page, Section.heading, Section.kind)
            .where(Section.document_id == document.id, Section.tenant_id == document.tenant_id)
            .order_by(Section.start_page, Section.end_page)
        )
    )
    if not sections:
        raise InputsError(f"document {document.filename!r} has no section map yet")
    page_texts = {
        page_no: text
        for page_no, text in session.execute(
            select(Page.page_no, Page.text).where(
                Page.document_id == document.id, Page.tenant_id == document.tenant_id
            )
        )
    }
    named: set[int] = set()
    for group in schema.groups:
        if group.derived:
            continue
        named.update(
            select_pages(
                group.routing,
                [(s, e, h, k) for s, e, h, k in sections],
                page_texts,
                max_pages=min(
                    group.max_pages or settings.extract_max_pages_per_group,
                    settings.extract_max_pages_per_group,
                ),
                fallback_pages=settings.extract_max_pages_per_call,
                keyword_pages=settings.extract_keyword_pages,
            )
        )
    return OfferedDocument(
        number=number,
        document_id=document.id,
        filename=document.filename,
        version_no=version.version_no,
        version_kind=version.kind,
        role=role,
        page_count=document.page_count or len(page_texts),
        pages=tuple(sorted(named)),
        sections=tuple((s, e, h) for s, e, h, _ in sections),
    )


def describe(inputs: PassInputs) -> str:
    """The brief the agent receives after its instructions: documents, pages, fields."""
    lines = [f"Tender type: {inputs.tender_type}", "", "Documents:"]
    for d in inputs.documents:
        pages = ", ".join(_ranges(d.pages)) if d.pages else "none named"
        lines.append(
            f"- Document {d.number}: {d.filename} — version {d.version_no} ({d.version_kind}, "
            f"role {d.role}), {d.page_count} pages. Pages the section map names: {pages}."
        )
        for start, end, heading in d.sections:
            span = f"p{start}" if start == end else f"p{start}-{end}"
            lines.append(f"    {span}: {heading}")
    lines += ["", "Fields, by section (path (type[, unit][, required]): label — help):"]
    for group in inputs.groups:
        lines.append(f"\n## {group.label} ({group.name})")
        if group.guidance.strip():
            lines.append(f"Guidance: {group.guidance.strip()}")
        for field in group.fields:
            lines.append(f"- {_field_line(field)}")
    return "\n".join(lines)


def _field_line(field: FieldDef) -> str:
    spec = [field.value_type]
    if field.unit:
        spec.append(f"unit {field.unit}")
    if field.required:
        spec.append("required")
    line = f"{field.path} ({', '.join(spec)}): {field.label}"
    if field.help_text.strip():
        line += f" — {field.help_text.strip()}"
    if field.enum_values:
        line += f" One of: {', '.join(field.enum_values)}."
    if field.keys:
        keys = "; ".join(_key_line(k) for k in field.keys)
        line += f" Object with keys: {keys}."
    elif field.item_keys:
        line += f" List of objects with keys: {', '.join(field.item_keys)}."
    return line


def _key_line(key: KeyDef) -> str:
    out = f"{key.name} ({key.value_type}{', unit ' + key.unit if key.unit else ''})"
    if key.enum_values:
        out += f" one of {'/'.join(key.enum_values)}"
    if key.keys:
        out += " — list of objects with keys " + ", ".join(_key_line(k) for k in key.keys)
    return out


def _ranges(pages: tuple[int, ...]) -> list[str]:
    out: list[str] = []
    start = prev = pages[0]
    for page in pages[1:]:
        if page == prev + 1:
            prev = page
            continue
        out.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = page
    out.append(f"{start}" if start == prev else f"{start}-{prev}")
    return out
