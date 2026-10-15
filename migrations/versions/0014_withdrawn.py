"""candidate.withdrawn and canonical_fact.withdrawn: a provision withdrawn by a later version

A reading that the document removes the provision (value null, the evidence the removing
words), told apart from a value the pages do not state and from a plain null; the fact
approved from it drops the earlier value in the current view and says which version
withdrew it.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("candidate", "canonical_fact"):
        op.add_column(
            table,
            sa.Column("withdrawn", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    for table in ("candidate", "canonical_fact"):
        op.drop_column(table, "withdrawn")
