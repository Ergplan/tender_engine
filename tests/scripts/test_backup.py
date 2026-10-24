"""The backup script's retention: expired files go, fresh ones and anything else stay."""

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "backup.sh"


def test_retention_deletes_only_expired_backups(tmp_path: Path) -> None:
    old = time.time() - 20 * 86400
    for name in ("db-20261001T000000Z.dump", "data-20261001T000000Z.tar.gz"):
        (tmp_path / name).write_bytes(b"x")
        os.utime(tmp_path / name, (old, old))
    (tmp_path / "db-20261024T000000Z.dump").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    os.utime(tmp_path / "notes.txt", (old, old))
    out = subprocess.run(
        [str(SCRIPT), "--retention-only"],
        env={**os.environ, "BACKUP_ROOT": str(tmp_path), "RETENTION_DAYS": "14"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "db-20261001T000000Z.dump" in out.stdout
    assert sorted(p.name for p in tmp_path.iterdir()) == ["db-20261024T000000Z.dump", "notes.txt"]
    assert oct(tmp_path.stat().st_mode)[-3:] == "700"


def test_script_is_executable_and_strict() -> None:
    assert os.access(SCRIPT, os.X_OK)
    text = SCRIPT.read_text()
    assert "set -euo pipefail" in text
    # The Drive bundle is built from `git archive` (tracked files only) and refused if a
    # .env is found in it; the two state files cannot hold one.
    assert "git -C" in text and "archive" in text and "refusing" in text
    assert "--account" in text, "the bucket is written as the VM's service account"


def test_the_repository_archive_carries_no_secret_file() -> None:
    """What the Drive bundle ships of the repository: no .env, no allowlist, no links."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True
    )
    names = {line.rsplit("/", 1)[-1] for line in out.stdout.splitlines()}
    assert ".env" not in names and "allowlist.yaml" not in names
    assert not any(name.endswith("-links.txt") for name in names)


def test_a_key_file_overrides_the_metadata_account(tmp_path: Path) -> None:
    """BACKUP_KEY_FILE (the stop-gap until the VM scope is widened) must be used as the gcloud
    credential and the metadata account left aside; an unreadable key file stops the run."""
    text = SCRIPT.read_text()
    assert "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE" in text
    assert "BACKUP_KEY_FILE not readable" in text
    # No key file may ever be tracked.
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True
    )
    assert not any(
        name.endswith(".json") and "key" in name.lower()
        for name in (line.rsplit("/", 1)[-1] for line in out.stdout.splitlines())
    )
