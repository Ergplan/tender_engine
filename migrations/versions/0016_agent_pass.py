"""agent_run and agent_finding: the independent agent pass (Stage 5A)

The agent's findings are kept apart from candidates and canonical facts. llm_call_log
gains agent_run_id so that the agent's model calls are logged like every other call and
the run's tokens and cost are the sum of its rows.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_run",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.tenant_id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("object_type", sa.String(50), nullable=False),
        sa.Column("object_id", sa.String(32), nullable=False),
        sa.Column("object_version", sa.Integer(), nullable=False),
        sa.Column("schema_name", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("prompt_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_cached", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "pages_offered", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("pages_read", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("documents", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("is_fixture", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_agent_run_tenant_id", "agent_run", ["tenant_id"])
    op.create_index("ix_agent_run_object_id", "agent_run", ["object_id"])

    op.create_table(
        "agent_finding",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.tenant_id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("agent_run_id", sa.String(32), sa.ForeignKey("agent_run.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("field_path", sa.String(200), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("value_type", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.create_index("ix_agent_finding_tenant_id", "agent_finding", ["tenant_id"])
    op.create_index("ix_agent_finding_agent_run_id", "agent_finding", ["agent_run_id"])
    op.create_index("ix_agent_finding_field_path", "agent_finding", ["field_path"])

    op.add_column(
        "llm_call_log",
        sa.Column("agent_run_id", sa.String(32), sa.ForeignKey("agent_run.id"), nullable=True),
    )
    op.create_index("ix_llm_call_log_agent_run_id", "llm_call_log", ["agent_run_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_log_agent_run_id", table_name="llm_call_log")
    op.drop_column("llm_call_log", "agent_run_id")
    op.drop_index("ix_agent_finding_field_path", table_name="agent_finding")
    op.drop_index("ix_agent_finding_agent_run_id", table_name="agent_finding")
    op.drop_index("ix_agent_finding_tenant_id", table_name="agent_finding")
    op.drop_table("agent_finding")
    op.drop_index("ix_agent_run_object_id", table_name="agent_run")
    op.drop_index("ix_agent_run_tenant_id", table_name="agent_run")
    op.drop_table("agent_run")
