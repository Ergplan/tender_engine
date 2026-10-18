"""identity (Stage 5C): app_user, login_session, api_key, usage_record; tenant.plan; the
reserved `public` tenant

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.tenant_id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("plan", sa.String(20), nullable=False, server_default="enterprise"),
    )
    op.execute(
        "INSERT INTO tenant (tenant_id, name, created_by, plan) "
        "VALUES ('public', 'Public library', 'migration', 'public') "
        "ON CONFLICT (tenant_id) DO NOTHING"
    )

    op.create_table(
        "app_user",
        *_audit_columns(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("oidc_subject", sa.String(200), nullable=True, unique=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "email", name="uq_app_user_tenant_email"),
    )
    op.create_index("ix_app_user_tenant_id", "app_user", ["tenant_id"])

    op.create_table(
        "login_session",
        *_audit_columns(),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_login_session_tenant_id", "login_session", ["tenant_id"])
    op.create_index("ix_login_session_user_id", "login_session", ["user_id"])

    op.create_table(
        "api_key",
        *_audit_columns(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("rate_limit_per_min", sa.Integer(), nullable=False),
        sa.Column("daily_cap", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_key_tenant_id", "api_key", ["tenant_id"])
    op.create_index("ix_api_key_prefix", "api_key", ["prefix"])

    op.create_table(
        "usage_record",
        *_audit_columns(),
        sa.Column("resource_tenant_id", sa.String(64), nullable=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("api_key_id", sa.String(32), sa.ForeignKey("api_key.id"), nullable=True),
        sa.Column("tool", sa.String(100), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("detail", sa.Text(), nullable=True),
    )
    op.create_index("ix_usage_record_tenant_id", "usage_record", ["tenant_id"])
    op.create_index("ix_usage_record_api_key_id", "usage_record", ["api_key_id"])
    op.create_index("ix_usage_record_tool", "usage_record", ["tool"])


def downgrade() -> None:
    for table in ("usage_record", "api_key", "login_session", "app_user"):
        op.drop_table(table)
    op.execute("DELETE FROM tenant WHERE tenant_id = 'public'")
    op.drop_column("tenant", "plan")
