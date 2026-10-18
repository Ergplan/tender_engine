"""row-level security on every tenant table (Stage 5C), and the application role

Each table with a tenant_id gets policies keyed on the session's `app.tenant_id` (set by
core.db at the start of every transaction): a session reads its own tenant's rows and
those of the tenants in `app.read_tenants` (the public library, Stage 5D), and writes its
own tenant's rows only. The scope "*" is for the identity steps that look across tenants.
FORCE makes the table owner subject to the policies too, so the connection the app uses
today is bound by them; `tender_app` is the role without ownership for production (the
operator gives it LOGIN and a password and points DATABASE_URL at it).

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

TABLES = (
    "agent_finding",
    "agent_run",
    "api_key",
    "app_user",
    "approval",
    "audit_log",
    "candidate",
    "canonical_fact",
    "document",
    "evidence_span",
    "extraction_run",
    "feedback",
    "job",
    "llm_batch",
    "llm_call_log",
    "login_session",
    "page",
    "review_token",
    "section",
    "tender",
    "tender_field_def",
    "tender_review_snapshot",
    "tender_version",
    "tender_version_document",
    "usage_record",
    "validation_result",
)
OWN = "current_setting('app.tenant_id', true) = '*' OR tenant_id = current_setting('app.tenant_id', true)"
READ = f"{OWN} OR tenant_id = ANY(string_to_array(current_setting('app.read_tenants', true), ','))"


def upgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(sa.text("SELECT current_schema()")).scalar()
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_select ON {table} FOR SELECT USING ({READ})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({OWN})")
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE USING ({OWN}) WITH CHECK ({OWN})"
        )
        op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({OWN})")
    # The tenant registry: a tenant sees its own row and the public library's; rows are
    # made and changed only in the system scope (sign-up, the operator).
    op.execute("ALTER TABLE tenant ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_select ON tenant FOR SELECT USING ("
        "current_setting('app.tenant_id', true) = '*' "
        "OR tenant_id = current_setting('app.tenant_id', true) "
        "OR tenant_id = ANY(string_to_array(current_setting('app.read_tenants', true), ',')))"
    )
    op.execute(
        "CREATE POLICY tenant_write ON tenant FOR ALL USING ("
        "current_setting('app.tenant_id', true) = '*') "
        "WITH CHECK (current_setting('app.tenant_id', true) = '*')"
    )
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tender_app') "
        "THEN CREATE ROLE tender_app NOLOGIN; END IF; END $$"
    )
    op.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO tender_app')
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO tender_app'
    )
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO tender_app')
    op.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT, INSERT, UPDATE, DELETE '
        "ON TABLES TO tender_app"
    )


def downgrade() -> None:
    for policy in ("tenant_select", "tenant_write"):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON tenant")
    op.execute("ALTER TABLE tenant NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant DISABLE ROW LEVEL SECURITY")
    for table in TABLES:
        for policy in ("tenant_select", "tenant_insert", "tenant_update", "tenant_delete"):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
