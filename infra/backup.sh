#!/usr/bin/env bash
# Nightly backup of the VM's state (Block 0 of the completion plan, 2026-10-24):
#   1. a pg_dump of the app database (custom format, compressed) and a tar of /data
#      (documents and page renders), kept under BACKUP_ROOT for RETENTION_DAYS;
#   2. the same two files copied to the versioned GCS bucket BACKUP_BUCKET (when set) with
#      the VM's service account (`gcloud --account`); the bucket's lifecycle keeps 30 days;
#   3. a Drive bundle under BACKUP_ROOT/drive: the dump, the tar, `git archive` of the
#      committed tree (tracked files only, so never .env or the allowlist) and a manifest
#      of sha256 sums. Nothing in it is a secret; the owner syncs the folder to Drive.
# The app stays up; pg_dump reads a consistent snapshot. Run by cron as the VM user, or once
# with `make backup`.
#
# Usage: infra/backup.sh [--retention-only]
#   --retention-only   delete expired backups and exit (used by the test)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BACKUP_ROOT="${BACKUP_ROOT:-/work/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
DATA_DIR="${DATA_DIR:-/data}"
COMPOSE="${COMPOSE:-docker compose}"
BACKUP_BUCKET="${BACKUP_BUCKET:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
METADATA="http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email"

mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"

prune() {
  # Older than the retention, by name (the stamp), so a clock change cannot delete today's.
  find "$BACKUP_ROOT" -maxdepth 1 -type f \( -name 'db-*.dump' -o -name 'data-*.tar.gz' \) \
    -mtime "+$RETENTION_DAYS" -print -delete
}

if [[ "${1:-}" == "--retention-only" ]]; then
  prune
  exit 0
fi

cd "$ROOT"
DB_OUT="$BACKUP_ROOT/db-$STAMP.dump"
DATA_OUT="$BACKUP_ROOT/data-$STAMP.tar.gz"

# The database: the owner role, custom format, so pg_restore can pick tables.
$COMPOSE exec -T db pg_dump -U tender -d tender -Fc > "$DB_OUT.part"
mv "$DB_OUT.part" "$DB_OUT"

# The files: documents and renders as the storage interface laid them out.
tar -czf "$DATA_OUT.part" -C "$(dirname "$DATA_DIR")" "$(basename "$DATA_DIR")"
mv "$DATA_OUT.part" "$DATA_OUT"

chmod 600 "$DB_OUT" "$DATA_OUT"

# The Drive bundle: replaced whole each night; no file of it holds a secret.
DRIVE="$BACKUP_ROOT/drive"
rm -rf "$DRIVE.new" && mkdir -p "$DRIVE.new"
cp "$DB_OUT" "$DATA_OUT" "$DRIVE.new/"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"
git -C "$ROOT" archive --format=tar.gz -o "$DRIVE.new/repo-$COMMIT.tar.gz" HEAD
if tar -tzf "$DRIVE.new/repo-$COMMIT.tar.gz" | grep -qE '(^|/)\.env$'; then
  echo "refusing: the repository archive carries a .env" >&2; rm -rf "$DRIVE.new"; exit 2
fi
(cd "$DRIVE.new" && sha256sum -- * > MANIFEST.sha256 && echo "stamp $STAMP commit $COMMIT" >> MANIFEST.sha256)
chmod 600 "$DRIVE.new"/*
rm -rf "$DRIVE" && mv "$DRIVE.new" "$DRIVE"

# Off the VM: the versioned bucket, as the VM's own service account.
UPLOADED="not configured (BACKUP_BUCKET empty)"
if [[ -n "$BACKUP_BUCKET" ]]; then
  SA="$(curl -sf -H 'Metadata-Flavor: Google' "$METADATA" || true)"
  if gcloud ${SA:+--account="$SA"} storage cp "$DB_OUT" "$DATA_OUT" "gs://$BACKUP_BUCKET/$(date -u +%Y/%m)/" >/dev/null 2>"$BACKUP_ROOT/upload.err"; then
    UPLOADED="gs://$BACKUP_BUCKET/$(date -u +%Y/%m)/"
  else
    UPLOADED="FAILED ($(tail -1 "$BACKUP_ROOT/upload.err"))"
  fi
fi

prune
echo "backup $STAMP: $(du -h "$DB_OUT" | cut -f1) database, $(du -h "$DATA_OUT" | cut -f1) files, in $BACKUP_ROOT; drive bundle $DRIVE; bucket: $UPLOADED"
[[ "$UPLOADED" != FAILED* ]]
