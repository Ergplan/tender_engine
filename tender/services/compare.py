"""Tenders side by side (Stage 5C): fields as rows, tenders as columns, provenance on
every cell, a gap marked as such. A suspended tender is left out with a note; its stale
values are not for comparing."""

from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.orm import Session

from tender.models import Tender
from tender.services.packs import Catalog
from tender.services.published import PublishedField, PublishedTender, published_tender

MAX_TENDERS = 6


class CompareColumn(BaseModel):
    tender_id: str
    slug: str | None
    title: str
    issuing_agency: str
    tender_type: str
    publication_state: str
    reviewed_version: int | None
    banner: str | None


class CompareRow(BaseModel):
    path: str
    label: str
    section: str
    value_type: str
    unit: str | None
    # One cell per column, in column order; None where the type has no such field.
    cells: list[PublishedField | None]


class Comparison(BaseModel):
    columns: list[CompareColumn]
    rows: list[CompareRow]
    # Tenders asked for and left out, with why.
    excluded: list[dict[str, str]]
    authority_note: str


def compare_tenders(
    session: Session,
    catalog: Catalog,
    tenders: list[Tender],
    *,
    results_root: Path | None = None,
) -> Comparison:
    if len(tenders) > MAX_TENDERS:
        raise ValueError(f"at most {MAX_TENDERS} tenders can be compared at once")
    published: list[PublishedTender] = []
    excluded: list[dict[str, str]] = []
    for tender in tenders:
        view = published_tender(session, catalog, tender, results_root=results_root)
        if view.publication.state == "publication_suspended":
            excluded.append(
                {
                    "tender_id": tender.id,
                    "reason": view.banner or "publication suspended",
                }
            )
            continue
        published.append(view)
    # Rows: the union of the types' fields, in each type's review order, first type first.
    order: list[tuple[str, str, str, str, str | None]] = []
    seen: set[str] = set()
    for view in published:
        for field in catalog.get(view.tender_type).fields:
            if field.path in seen:
                continue
            seen.add(field.path)
            order.append((field.path, field.label, field.section, field.value_type, field.unit))
    cells_by_tender = [
        {field.path: field for section in view.sections for field in section.fields}
        for view in published
    ]
    rows = [
        CompareRow(
            path=path,
            label=label,
            section=section,
            value_type=value_type,
            unit=unit,
            cells=[cells.get(path) for cells in cells_by_tender],
        )
        for path, label, section, value_type, unit in order
        if any(path in cells for cells in cells_by_tender)
    ]
    return Comparison(
        columns=[
            CompareColumn(
                tender_id=view.tender_id,
                slug=view.slug,
                title=view.title,
                issuing_agency=view.issuing_agency,
                tender_type=view.tender_type,
                publication_state=view.publication.state,
                reviewed_version=view.reviewed_version,
                banner=view.banner,
            )
            for view in published
        ],
        rows=rows,
        excluded=excluded,
        authority_note=published[0].authority_note if published else "",
    )
