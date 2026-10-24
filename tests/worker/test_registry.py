"""Every process that opens a session registers every table (defect of 2026-10-24).

`llm_call_log.agent_run_id` references `agent_run`; a process whose metadata lacks that
table cannot flush a call log row (`NoReferencedTableError`). The worker ran that way for
two days: 116 section maps were called and none was logged. Each entry point is imported
in a fresh interpreter, so that a table another test module happened to import does not
hide the gap."""

import json
import subprocess
import sys

import pytest
from sqlalchemy import text

from core.config import Settings
from tests.conftest import owner_engine

ENTRY_POINTS = (
    "worker.main",
    "api.main",
    "agent.main",
    "scripts.ingest_tenders",
    "scripts.import_results",
    "scripts.llm_smoke",
    "scripts.review_token",
    "scripts.make_gold",
    "scripts.agent_pass",
    "evals.runner",
    "evals.report",
    "evals.feedback_report",
    "evals.threeway",
)

# After the entry point's imports: resolve every foreign key the way a flush does
# (`sorted_tables` walks them and raises NoReferencedTableError for a table nobody
# registered), then list what is registered.
PROBE = (
    "import importlib, json, sys; importlib.import_module(sys.argv[1]); "
    "from core.models import Base, LLMCallLog; "
    "Base.metadata.sorted_tables; "
    "[fk.column for fk in LLMCallLog.__table__.foreign_keys]; "
    "print(json.dumps(sorted(Base.metadata.tables)))"
)


def migrated_tables(settings: Settings) -> set[str]:
    with owner_engine(settings).connect() as conn:
        rows = conn.execute(
            text("select table_name from information_schema.tables where table_schema = :s"),
            {"s": settings.db_schema},
        )
        return {row[0] for row in rows} - {"alembic_version"}


@pytest.mark.parametrize("module", ENTRY_POINTS)
def test_entry_point_registers_every_migrated_table(module: str, settings: Settings) -> None:
    out = subprocess.run(
        [sys.executable, "-c", PROBE, module],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert out.returncode == 0, (
        f"{module}: a log row could not be flushed from this process\n" + out.stderr[-2000:]
    )
    registered = set(json.loads(out.stdout.strip().splitlines()[-1]))
    missing = migrated_tables(settings) - registered
    assert not missing, f"{module} does not register {sorted(missing)}"
