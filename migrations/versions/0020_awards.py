"""Stage 6: award results as a reviewed object type.

`award`: one row per result publication imported from the RE-tender-results dataset, under
the row-level security policies of migration 0018. `review_token` widened from a tender to
an object: `object_type` (tender, award) and `object_id`; `tender_id` stays for a tender's
token and becomes nullable.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

OWN = "current_setting('app.tenant_id', true) = '*' OR tenant_id = current_setting('app.tenant_id', true)"
READ = f"{OWN} OR tenant_id = ANY(string_to_array(current_setting('app.read_tenants', true), ','))"


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
        "award",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.tenant_id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("document_id", sa.String(32), sa.ForeignKey("document.id"), nullable=False),
        sa.Column("source_id", sa.String(32), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("source_name", sa.String(300), nullable=False),
        sa.Column("dataset", sa.String(100), nullable=False),
        sa.Column("procurer", sa.String(100), nullable=False),
        sa.Column("reference", sa.String(200), nullable=False),
        sa.Column("result_kind", sa.String(40), nullable=False),
        sa.Column("verification", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.String(32), sa.ForeignKey("tender.id"), nullable=True),
        sa.Column("tender_link_basis", sa.String(20), nullable=True),
        sa.Column("tender_link_page", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("tenant_id", "source_sha256", name="uq_award_tenant_source"),
    )
    op.create_index("ix_award_document_id", "award", ["document_id"])
    op.create_index("ix_award_tender_id", "award", ["tender_id"])
    _secure("award")

    op.add_column(
        "review_token",
        sa.Column("object_type", sa.String(20), nullable=False, server_default="tender"),
    )
    op.add_column("review_token", sa.Column("object_id", sa.String(32), nullable=True))
    op.execute("UPDATE review_token SET object_id = tender_id")
    op.alter_column("review_token", "object_id", nullable=False)
    op.create_index("ix_review_token_object_id", "review_token", ["object_id"])
    op.alter_column("review_token", "tender_id", existing_type=sa.String(32), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM review_token WHERE object_type <> 'tender'")
    op.alter_column("review_token", "tender_id", existing_type=sa.String(32), nullable=False)
    op.drop_index("ix_review_token_object_id", table_name="review_token")
    op.drop_column("review_token", "object_id")
    op.drop_column("review_token", "object_type")
    op.drop_index("ix_award_tender_id", table_name="award")
    op.drop_index("ix_award_document_id", table_name="award")
    op.drop_index("ix_award_tenant_id", table_name="award")
    op.drop_table("award")
