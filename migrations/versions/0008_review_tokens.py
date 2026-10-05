"""review_token and tender_review_snapshot; the canonical_fact guard names the decisions
that may carry a fact (a flag, added in Stage 3, may not)

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


GUARD = """
        CREATE OR REPLACE FUNCTION canonical_fact_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'canonical_fact rows are immutable: delete refused';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NOT NEW.is_current OR NEW.superseded_at IS NOT NULL THEN
                    RAISE EXCEPTION 'canonical_fact insert refused: a new fact is current';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM approval a
                    WHERE a.id = NEW.approval_id
                      AND a.status = 'active'
                      AND a.decision <> 'rejected'
                      AND a.tenant_id = NEW.tenant_id
                      AND a.object_type = NEW.object_type
                      AND a.object_id = NEW.object_id
                      AND a.object_version = NEW.object_version
                      AND a.field_path = NEW.field_path
                ) THEN
                    RAISE EXCEPTION
                        'canonical_fact insert refused: no live approval % for this field',
                        NEW.approval_id;
                END IF;
                RETURN NEW;
            END IF;
            -- UPDATE: a fact is never changed. It can only be retired, once, after the
            -- approval it came from has been superseded.
            IF (to_jsonb(NEW) - 'is_current' - 'superseded_at')
               IS DISTINCT FROM (to_jsonb(OLD) - 'is_current' - 'superseded_at') THEN
                RAISE EXCEPTION 'canonical_fact rows are immutable: update refused';
            END IF;
            IF NOT OLD.is_current OR NEW.is_current OR NEW.superseded_at IS NULL THEN
                RAISE EXCEPTION
                    'canonical_fact rows are immutable: a current fact may only be retired';
            END IF;
            IF EXISTS (
                SELECT 1 FROM approval a WHERE a.id = OLD.approval_id AND a.status = 'active'
            ) THEN
                RAISE EXCEPTION
                    'canonical_fact rows are immutable: the approval of this fact is still live';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
"""
FACT_DECISIONS = "a.decision IN ('approved', 'edited', 'not_in_document')"
NOT_REJECTED = "a.decision <> 'rejected'"


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by", sa.String(length=200), nullable=False),
    ]


def upgrade() -> None:
    op.execute(GUARD.replace(NOT_REJECTED, FACT_DECISIONS))
    op.create_table(
        "review_token",
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("tender_id", sa.String(length=32), nullable=False),
        sa.Column("reviewer_name", sa.String(length=200), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),
        sa.ForeignKeyConstraint(["tender_id"], ["tender.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(op.f("ix_review_token_tenant_id"), "review_token", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_review_token_tender_id"), "review_token", ["tender_id"], unique=False)
    op.create_table(
        "tender_review_snapshot",
        sa.Column("tender_id", sa.String(length=32), nullable=False),
        sa.Column("review_token_id", sa.String(length=32), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["review_token_id"], ["review_token.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),
        sa.ForeignKeyConstraint(["tender_id"], ["tender.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tender_review_snapshot_tenant_id"),
        "tender_review_snapshot",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tender_review_snapshot_tender_id"),
        "tender_review_snapshot",
        ["tender_id"],
        unique=False,
    )


def downgrade() -> None:
    op.execute(GUARD)
    op.drop_index(op.f("ix_tender_review_snapshot_tender_id"), table_name="tender_review_snapshot")
    op.drop_index(op.f("ix_tender_review_snapshot_tenant_id"), table_name="tender_review_snapshot")
    op.drop_table("tender_review_snapshot")
    op.drop_index(op.f("ix_review_token_tender_id"), table_name="review_token")
    op.drop_index(op.f("ix_review_token_tenant_id"), table_name="review_token")
    op.drop_table("review_token")
