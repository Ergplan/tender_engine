"""evidence_span.ordinal: the quote's place in the model's evidence list

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence_span", sa.Column("ordinal", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence_span", "ordinal")
