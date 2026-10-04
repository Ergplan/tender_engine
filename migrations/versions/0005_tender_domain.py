"""tender domain: tender, tender_version, tender_version_document, tender_field_def;
extraction_run.groups (a run may cover a subset of the schema's field groups)

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('tender',
    sa.Column('tender_type', sa.String(length=20), nullable=False),
    sa.Column('issuing_agency', sa.String(length=200), nullable=False),
    sa.Column('external_ref', sa.String(length=200), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('current_version_id', sa.String(length=32), nullable=True),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.tenant_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'slug', name='uq_tender_tenant_slug')
    )
    op.create_index(op.f('ix_tender_tenant_id'), 'tender', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_tender_tender_type'), 'tender', ['tender_type'], unique=False)
    op.create_table('tender_field_def',
    sa.Column('tender_type', sa.String(length=20), nullable=False),
    sa.Column('field_path', sa.String(length=200), nullable=False),
    sa.Column('namespace', sa.String(length=20), nullable=False),
    sa.Column('domain', sa.String(length=50), nullable=True),
    sa.Column('subdomain', sa.String(length=50), nullable=True),
    sa.Column('section', sa.String(length=100), nullable=False),
    sa.Column('label', sa.String(length=300), nullable=False),
    sa.Column('value_type', sa.String(length=50), nullable=False),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('help_text', sa.Text(), nullable=False),
    sa.Column('review_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.tenant_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'tender_type', 'field_path', name='uq_tender_field_def_type_path')
    )
    op.create_index(op.f('ix_tender_field_def_tenant_id'), 'tender_field_def', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_tender_field_def_tender_type'), 'tender_field_def', ['tender_type'], unique=False)
    op.create_table('tender_version',
    sa.Column('tender_id', sa.String(length=32), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('issued_on', sa.Date(), nullable=True),
    sa.Column('summary_of_change', sa.Text(), nullable=True),
    sa.Column('supersedes_version_id', sa.String(length=32), nullable=True),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['supersedes_version_id'], ['tender_version.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.tenant_id'], ),
    sa.ForeignKeyConstraint(['tender_id'], ['tender.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tender_id', 'version_no', name='uq_tender_version_tender_no')
    )
    op.create_index(op.f('ix_tender_version_tenant_id'), 'tender_version', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_tender_version_tender_id'), 'tender_version', ['tender_id'], unique=False)
    op.create_table('tender_version_document',
    sa.Column('tender_version_id', sa.String(length=32), nullable=False),
    sa.Column('document_id', sa.String(length=32), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.tenant_id'], ),
    sa.ForeignKeyConstraint(['tender_version_id'], ['tender_version.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tender_version_id', 'document_id', name='uq_tender_version_document_once')
    )
    op.create_index(op.f('ix_tender_version_document_document_id'), 'tender_version_document', ['document_id'], unique=False)
    op.create_index(op.f('ix_tender_version_document_tenant_id'), 'tender_version_document', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_tender_version_document_tender_version_id'), 'tender_version_document', ['tender_version_id'], unique=False)
    op.create_foreign_key('fk_tender_current_version', 'tender', 'tender_version', ['current_version_id'], ['id'])
    op.add_column('extraction_run', sa.Column('groups', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('extraction_run', 'groups')
    op.drop_constraint('fk_tender_current_version', 'tender', type_='foreignkey')
    op.drop_index(op.f('ix_tender_version_document_tender_version_id'), table_name='tender_version_document')
    op.drop_index(op.f('ix_tender_version_document_tenant_id'), table_name='tender_version_document')
    op.drop_index(op.f('ix_tender_version_document_document_id'), table_name='tender_version_document')
    op.drop_table('tender_version_document')
    op.drop_index(op.f('ix_tender_version_tender_id'), table_name='tender_version')
    op.drop_index(op.f('ix_tender_version_tenant_id'), table_name='tender_version')
    op.drop_table('tender_version')
    op.drop_index(op.f('ix_tender_field_def_tender_type'), table_name='tender_field_def')
    op.drop_index(op.f('ix_tender_field_def_tenant_id'), table_name='tender_field_def')
    op.drop_table('tender_field_def')
    op.drop_index(op.f('ix_tender_tender_type'), table_name='tender')
    op.drop_index(op.f('ix_tender_tenant_id'), table_name='tender')
    op.drop_table('tender')
