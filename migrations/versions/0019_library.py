"""the public library tier (Stage 5D): model_assumption, watchlist_entry, correction_case,
publication_hold, oauth_client, oauth_code — each under the row-level security policies of
migration 0018

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

OWN = "current_setting('app.tenant_id', true) = '*' OR tenant_id = current_setting('app.tenant_id', true)"
READ = f"{OWN} OR tenant_id = ANY(string_to_array(current_setting('app.read_tenants', true), ','))"
TABLES = (
    "model_assumption",
    "watchlist_entry",
    "correction_case",
    "publication_hold",
    "oauth_client",
    "oauth_code",
)


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.tenant_id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
    ]


def _secure(table: str) -> None:
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_select ON {table} FOR SELECT USING ({READ})")
    op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({OWN})")
    op.execute(
        f"CREATE POLICY tenant_update ON {table} FOR UPDATE USING ({OWN}) WITH CHECK ({OWN})"
    )
    op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({OWN})")


def upgrade() -> None:
    op.create_table(
        "model_assumption",
        *_audit_columns(),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("tender_id", sa.String(32), nullable=False),
        sa.Column("tender_tenant_id", sa.String(64), nullable=False),
        sa.Column("model_type", sa.String(50), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "tender_id", "model_type", name="uq_model_assumption_owner"
        ),
    )
    op.create_index("ix_model_assumption_tender_id", "model_assumption", ["tender_id"])

    op.create_table(
        "watchlist_entry",
        *_audit_columns(),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("tender_id", sa.String(32), nullable=False),
        sa.Column("tender_tenant_id", sa.String(64), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", "tender_id", name="uq_watchlist_owner_tender"),
    )
    op.create_index("ix_watchlist_entry_tender_id", "watchlist_entry", ["tender_id"])

    op.create_table(
        "correction_case",
        *_audit_columns(),
        sa.Column("tender_id", sa.String(32), nullable=False),
        sa.Column("field_path", sa.String(200), nullable=False),
        sa.Column("claimed_error", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("claimant_tenant_id", sa.String(64), nullable=True),
        sa.Column("claimant_user_id", sa.String(32), nullable=True),
        sa.Column("claimant_email", sa.String(320), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(200), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_correction_case_tender_id", "correction_case", ["tender_id"])

    op.create_table(
        "publication_hold",
        *_audit_columns(),
        sa.Column("tender_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifted_by", sa.String(200), nullable=True),
    )
    op.create_index("ix_publication_hold_tender_id", "publication_hold", ["tender_id"])

    op.create_table(
        "oauth_client",
        *_audit_columns(),
        sa.Column("client_id", sa.String(64), nullable=False, unique=True),
        sa.Column("client_name", sa.String(200), nullable=False),
        sa.Column("redirect_uris", postgresql.JSONB(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "oauth_code",
        *_audit_columns(),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("redirect_uri", sa.String(1000), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("code_challenge", sa.String(200), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )

    for table in TABLES:
        _secure(table)
    bind = op.get_bind()
    schema = bind.execute(sa.text("SELECT current_schema()")).scalar()
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO tender_app'
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
