"""foundation: tenant (seeded with ergplan) and llm_call_log

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    tenant = op.create_table(
        "tenant",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
    )
    op.bulk_insert(tenant, [{"tenant_id": "ergplan", "name": "Ergplan", "created_by": "migration"}])

    op.create_table(
        "llm_call_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.tenant_id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("prompt_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("output_schema", sa.String(200), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stop_reason", sa.String(40), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("tokens_in", sa.Integer, nullable=False),
        sa.Column("tokens_out", sa.Integer, nullable=False),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("is_fixture", sa.Boolean, nullable=False),
    )
    op.create_index("ix_llm_call_log_tenant_id", "llm_call_log", ["tenant_id"])
    op.create_index("ix_llm_call_log_input_hash", "llm_call_log", ["input_hash"])


def downgrade() -> None:
    op.drop_table("llm_call_log")
    op.drop_table("tenant")
