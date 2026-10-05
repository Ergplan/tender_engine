"""evidence_span.source: what an inherited passage was inherited from

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence_span", sa.Column("source", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence_span", "source")
