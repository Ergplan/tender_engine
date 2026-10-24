"""Stage 7, Block 2 d: the type classifier's answer on the document.

`document.classification`: tender_type, state (set, unsure, unknown), confidence, reasons,
alternatives, prompt_version; null until the `classify_type` job has run. Its own revision
because 0021 was applied to the live database before this column was added to it.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column("classification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document", "classification")
