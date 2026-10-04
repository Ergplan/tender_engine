"""Invariant: every table has tenant_id, created_at, created_by."""

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from core.models import Base, Tenant


def test_every_table_carries_tenant_and_audit_columns() -> None:
    assert Base.metadata.tables, "no tables registered"
    for name, table in Base.metadata.tables.items():
        missing = {"tenant_id", "created_at", "created_by"} - set(table.columns.keys())
        assert not missing, f"{name} is missing {sorted(missing)}"


def test_migrated_schema_matches_the_models(db: Session) -> None:
    inspector = inspect(db.get_bind())
    for name, table in Base.metadata.tables.items():
        migrated = {column["name"] for column in inspector.get_columns(name)}
        assert migrated == set(table.columns.keys()), name


def test_ergplan_tenant_is_seeded_by_the_migration(db: Session) -> None:
    tenant = db.get(Tenant, "ergplan")
    assert tenant is not None and tenant.name == "Ergplan" and tenant.created_by == "migration"
