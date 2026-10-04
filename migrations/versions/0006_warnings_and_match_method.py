"""validation_result.severity (a failed rule may be a warning) and evidence_span.match_method

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "validation_result",
        sa.Column("severity", sa.String(length=10), server_default="error", nullable=False),
    )
    op.add_column("evidence_span", sa.Column("match_method", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence_span", "match_method")
    op.drop_column("validation_result", "severity")
