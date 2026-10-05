"""prompt cache and batch API: llm_call_log (mode, cache_write_tokens, batch_id, cost_usd),
extraction_run (mode, token_cached), llm_batch

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_call_log",
        sa.Column("cache_write_tokens", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "llm_call_log",
        sa.Column("mode", sa.String(length=10), server_default="sync", nullable=False),
    )
    op.add_column("llm_call_log", sa.Column("batch_id", sa.String(length=100), nullable=True))
    op.add_column(
        "llm_call_log",
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
    )
    # Calls made before this migration: no cache writes, no batch, full prices.
    op.execute(
        "UPDATE llm_call_log SET cost_usd = round("
        "(tokens_in * 10.0 + cache_read_tokens * 0.25 + tokens_out * 50.0) / 1000000.0, 6)"
    )
    op.add_column(
        "extraction_run",
        sa.Column("mode", sa.String(length=10), server_default="sync", nullable=False),
    )
    op.add_column(
        "extraction_run",
        sa.Column("token_cached", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "llm_batch",
        sa.Column("extraction_run_id", sa.String(length=32), nullable=True),
        sa.Column("provider_batch_id", sa.String(length=100), nullable=False),
        sa.Column("wave", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requests", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["extraction_run.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_llm_batch_extraction_run_id"), "llm_batch", ["extraction_run_id"], unique=False
    )
    op.create_index(op.f("ix_llm_batch_tenant_id"), "llm_batch", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_batch_tenant_id"), table_name="llm_batch")
    op.drop_index(op.f("ix_llm_batch_extraction_run_id"), table_name="llm_batch")
    op.drop_table("llm_batch")
    op.drop_column("extraction_run", "token_cached")
    op.drop_column("extraction_run", "mode")
    op.drop_column("llm_call_log", "cost_usd")
    op.drop_column("llm_call_log", "batch_id")
    op.drop_column("llm_call_log", "mode")
    op.drop_column("llm_call_log", "cache_write_tokens")
