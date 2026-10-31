"""Password sign-in (2026-10-31): `app_user.password_hash`, an scrypt hash with its salt
and parameters, null for a user who signs in with the identity provider only.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("password_hash", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("app_user", "password_hash")
