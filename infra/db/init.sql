-- Runs once when the Postgres volume is first created.
-- tender_ci is used by the watcher (alembic check) and by pytest (throwaway schemas).
CREATE DATABASE tender_ci OWNER tender;
-- The role the app connects as (Stage 5C): no ownership, so row-level security binds it
-- (the owner `tender` is a superuser here and bypasses it). Dev password only; production
-- sets its own (Secret Manager) and migrations run as the owner (MIGRATION_DATABASE_URL).
CREATE ROLE tender_app LOGIN PASSWORD 'tender_app';
GRANT CONNECT ON DATABASE tender TO tender_app;
GRANT CONNECT ON DATABASE tender_ci TO tender_app;
