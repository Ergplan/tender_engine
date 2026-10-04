"""one active approval and one current canonical fact per field of an object version

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

COLUMNS = ["tenant_id", "object_type", "object_id", "object_version", "field_path"]


def upgrade() -> None:
    op.create_index(
        "uq_approval_one_active_per_field",
        "approval",
        COLUMNS,
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_canonical_fact_one_current_per_field",
        "canonical_fact",
        COLUMNS,
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_index("uq_canonical_fact_one_current_per_field", table_name="canonical_fact")
    op.drop_index("uq_approval_one_active_per_field", table_name="approval")
