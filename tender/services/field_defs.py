"""tender_field_def: the compiled schemas written to a table for introspection.

Regenerated from the domain packs when the API starts; rows are replaced only when the
compiled schemas differ from what the table holds."""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tender.models import TenderFieldDef
from tender.services.packs import Catalog

COLUMNS = (
    "tender_type",
    "field_path",
    "namespace",
    "domain",
    "subdomain",
    "section",
    "label",
    "value_type",
    "required",
    "help_text",
    "review_order",
)


def sync_field_defs(session: Session, catalog: Catalog, tenant_id: str) -> bool:
    """Make the table match the catalog. Returns whether anything was written."""
    wanted: list[dict[str, Any]] = [
        {
            "tender_type": compiled.tender_type,
            "field_path": field.path,
            "namespace": field.namespace,
            "domain": field.domain,
            "subdomain": field.subdomain,
            "section": field.section,
            "label": field.label,
            "value_type": field.value_type,
            "required": field.required,
            "help_text": field.help_text,
            "review_order": field.review_order,
        }
        for compiled in catalog.types.values()
        for field in compiled.fields
    ]
    existing: list[dict[str, Any]] = [
        {column: getattr(row, column) for column in COLUMNS}
        for row in session.scalars(
            select(TenderFieldDef).where(TenderFieldDef.tenant_id == tenant_id)
        )
    ]

    def keyed(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
        return {(row["tender_type"], row["field_path"]): row for row in rows}

    if keyed(existing) == keyed(wanted):
        session.rollback()
        return False
    session.execute(delete(TenderFieldDef).where(TenderFieldDef.tenant_id == tenant_id))
    session.add_all(
        TenderFieldDef(tenant_id=tenant_id, created_by="startup", **row) for row in wanted
    )
    session.commit()
    return True
