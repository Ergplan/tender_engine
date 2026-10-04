-- Runs once when the Postgres volume is first created.
-- tender_ci is used by the watcher (alembic check) and by pytest (throwaway schemas).
CREATE DATABASE tender_ci OWNER tender;
