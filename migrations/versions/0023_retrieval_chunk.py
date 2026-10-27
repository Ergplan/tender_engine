"""Stage 7, Block 5: the retrieval chunk table (pgvector) under row-level security.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

TABLE = "retrieval_chunk"
OWN = (
    "current_setting('app.tenant_id', true) = '*' "
    "OR tenant_id = current_setting('app.tenant_id', true)"
)
READ = f"{OWN} OR tenant_id = ANY(string_to_array(current_setting('app.read_tenants', true), ','))"


def upgrade() -> None:
    # The extension lives in `public`, said so: without SCHEMA it would land in the first
    # schema of the search path, the test harness's own, and go when that schema is dropped.
    # A connection scoped to another schema sees it because `public` follows the schema on
    # the search path (core.db.make_engine does the same for the app's connections).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
    op.execute(
        "SELECT set_config('search_path', current_setting('search_path') || ', public', false)"
    )
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(128), primary_key=True),
        # 384: BAAI/bge-small-en-v1.5, the local model (core.retrieval.store.EMBEDDING_DIMENSION).
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("blob_data", sa.LargeBinary(), nullable=True),
        sa.Column("blob_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("blob_mime_type", sa.String(255), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenant.tenant_id"),
            nullable=False,
            server_default=sa.text("current_setting('app.tenant_id', true)"),
        ),
    )
    # Haystack's keyword index, under the name its store looks for, so it creates nothing.
    op.execute(
        f"CREATE INDEX haystack_keyword_index ON {TABLE} "
        "USING GIN (to_tsvector('english', content))"
    )
    op.execute(f"CREATE INDEX ix_{TABLE}_document ON {TABLE} ((meta ->> 'document_id'))")
    op.execute(f"CREATE INDEX ix_{TABLE}_tender ON {TABLE} ((meta ->> 'tender_id'))")
    op.create_index(f"ix_{TABLE}_tenant_id", TABLE, ["tenant_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_select ON {TABLE} FOR SELECT USING ({READ})")
    op.execute(f"CREATE POLICY tenant_insert ON {TABLE} FOR INSERT WITH CHECK ({OWN})")
    op.execute(
        f"CREATE POLICY tenant_update ON {TABLE} FOR UPDATE USING ({OWN}) WITH CHECK ({OWN})"
    )
    op.execute(f"CREATE POLICY tenant_delete ON {TABLE} FOR DELETE USING ({OWN})")


def downgrade() -> None:
    op.drop_table(TABLE)
