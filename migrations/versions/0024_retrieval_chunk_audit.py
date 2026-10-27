"""Stage 7, Block 5: the audit columns on `retrieval_chunk` (every table carries
tenant_id, created_at and created_by; Haystack's insert names only its own columns, so
both have database defaults and the indexer writes the actor afterwards).

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

TABLE = "retrieval_chunk"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "created_by", sa.String(100), nullable=False, server_default=sa.text("'retrieval'")
        ),
    )


def downgrade() -> None:
    op.drop_column(TABLE, "created_by")
    op.drop_column(TABLE, "created_at")
