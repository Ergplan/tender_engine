"""Stage 7, Block 6 b: webhook endpoints and deliveries, under the tenant policies.

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

OWN = (
    "current_setting('app.tenant_id', true) = '*' "
    "OR tenant_id = current_setting('app.tenant_id', true)"
)
READ = f"{OWN} OR tenant_id = ANY(string_to_array(current_setting('app.read_tenants', true), ','))"
TABLES = ("webhook_endpoint", "webhook_delivery")


def _audit_columns() -> list[sa.Column[sa.types.TypeEngine[object]]]:
    return [
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.tenant_id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "webhook_endpoint",
        sa.Column("id", sa.String(32), primary_key=True),
        *_audit_columns(),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret", sa.String(200), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_webhook_endpoint_tenant_id", "webhook_endpoint", ["tenant_id"])
    op.create_table(
        "webhook_delivery",
        sa.Column("id", sa.String(32), primary_key=True),
        *_audit_columns(),
        sa.Column(
            "endpoint_id", sa.String(32), sa.ForeignKey("webhook_endpoint.id"), nullable=False
        ),
        sa.Column("event", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_webhook_delivery_tenant_id", "webhook_delivery", ["tenant_id"])
    op.create_index("ix_webhook_delivery_endpoint_id", "webhook_delivery", ["endpoint_id"])
    op.create_index("ix_webhook_delivery_status", "webhook_delivery", ["status"])
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_select ON {table} FOR SELECT USING ({READ})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({OWN})")
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE USING ({OWN}) WITH CHECK ({OWN})"
        )
        op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({OWN})")


def downgrade() -> None:
    op.drop_table("webhook_delivery")
    op.drop_table("webhook_endpoint")
