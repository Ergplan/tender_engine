"""document.source_url and document.retrieved_on: where a document came from and when

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document", sa.Column("source_url", sa.String(length=1000), nullable=True))
    op.add_column("document", sa.Column("retrieved_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("document", "retrieved_on")
    op.drop_column("document", "source_url")
