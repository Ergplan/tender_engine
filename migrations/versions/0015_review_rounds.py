"""review_token.round_no and review_token.from_version: a review round opened by a version

A round is a review link scoped to the fields a later version touched: the reviewer is
asked about those, the earlier decisions carry forward with their provenance. The first
link of a tender is round 1 over the whole tender (from_version null).

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_token",
        sa.Column("round_no", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("review_token", sa.Column("from_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("review_token", "from_version")
    op.drop_column("review_token", "round_no")
