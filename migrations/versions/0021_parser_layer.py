"""Stage 7, Block 2: parsing layers and tender type provenance.

`page.parser_layer` (pdfplumber, docling, llamaparse; every existing page is pdfplumber's)
and `page.layer_detail` (what the layer reported, for the benchmark and the page view).
`tender.type_source`, `tender.type_confidence`, `tender.type_state` (how the type was set
and how sure; every existing tender's type came from its manifest and is set) and
`tender.parser_llamaparse` (whether this tender's documents may leave the VM for
LlamaParse; off everywhere).

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "page",
        sa.Column("parser_layer", sa.String(20), nullable=False, server_default="pdfplumber"),
    )
    op.add_column(
        "page", sa.Column("layer_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "tender",
        sa.Column("type_source", sa.String(20), nullable=False, server_default="manifest"),
    )
    op.add_column("tender", sa.Column("type_confidence", sa.Float(), nullable=True))
    op.add_column(
        "tender", sa.Column("type_state", sa.String(20), nullable=False, server_default="set")
    )
    op.add_column(
        "tender",
        sa.Column("parser_llamaparse", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("tender", "parser_llamaparse")
    op.drop_column("tender", "type_state")
    op.drop_column("tender", "type_confidence")
    op.drop_column("tender", "type_source")
    op.drop_column("page", "layer_detail")
    op.drop_column("page", "parser_layer")
