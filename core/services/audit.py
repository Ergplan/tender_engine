"""Append one audit_log row per write to a truth table. The table is append-only."""

from typing import Any

from sqlalchemy.orm import Session

from core.models import AuditLog


def record(
    session: Session,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    table_name: str,
    row_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    row = AuditLog(
        tenant_id=tenant_id,
        created_by=actor,
        actor=actor,
        action=action,
        table_name=table_name,
        row_id=row_id,
        before=before,
        after=after,
    )
    session.add(row)
    return row
