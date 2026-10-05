"""canonical_fact guard: the approval looked up when a fact is retired is the tenant's own

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

GUARD = """
        CREATE OR REPLACE FUNCTION canonical_fact_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'canonical_fact rows are immutable: delete refused';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NOT NEW.is_current OR NEW.superseded_at IS NOT NULL THEN
                    RAISE EXCEPTION 'canonical_fact insert refused: a new fact is current';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM approval a
                    WHERE a.id = NEW.approval_id
                      AND a.status = 'active'
                      AND a.decision IN ('approved', 'edited', 'not_in_document')
                      AND a.tenant_id = NEW.tenant_id
                      AND a.object_type = NEW.object_type
                      AND a.object_id = NEW.object_id
                      AND a.object_version = NEW.object_version
                      AND a.field_path = NEW.field_path
                ) THEN
                    RAISE EXCEPTION
                        'canonical_fact insert refused: no live approval % for this field',
                        NEW.approval_id;
                END IF;
                RETURN NEW;
            END IF;
            -- UPDATE: a fact is never changed. It can only be retired, once, after the
            -- approval it came from has been superseded.
            IF (to_jsonb(NEW) - 'is_current' - 'superseded_at')
               IS DISTINCT FROM (to_jsonb(OLD) - 'is_current' - 'superseded_at') THEN
                RAISE EXCEPTION 'canonical_fact rows are immutable: update refused';
            END IF;
            IF NOT OLD.is_current OR NEW.is_current OR NEW.superseded_at IS NULL THEN
                RAISE EXCEPTION
                    'canonical_fact rows are immutable: a current fact may only be retired';
            END IF;
            IF EXISTS (
                SELECT 1 FROM approval a
                WHERE a.id = OLD.approval_id
                  AND a.tenant_id = OLD.tenant_id
                  AND a.status = 'active'
            ) THEN
                RAISE EXCEPTION
                    'canonical_fact rows are immutable: the approval of this fact is still live';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
"""
TENANT = "\n                  AND a.tenant_id = OLD.tenant_id"


def upgrade() -> None:
    op.execute(GUARD)


def downgrade() -> None:
    op.execute(GUARD.replace(TENANT, ""))
