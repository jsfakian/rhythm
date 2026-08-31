#!/usr/bin/env bash
# Daily PostgreSQL backup for the RHYTHM platform.
#
# Dumps the live database via `docker compose exec db pg_dump`, timestamps
# the file, and prunes dumps older than RETENTION_DAYS. Intended to run from
# cron once per day; see the crontab entry installed alongside this script.
#
# Usage: backup_db.sh
# Env overrides: RETENTION_DAYS (default 30)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/db_backup_${TIMESTAMP}.sql"
LOG_FILE="$BACKUP_DIR/backup.log"

mkdir -p "$BACKUP_DIR"
cd "$PROJECT_DIR"

log() {
    echo "[$(date -Iseconds)] $*" >> "$LOG_FILE"
}

# Load DB_USER/DB_NAME from .env if present, matching the Makefile's db-backup target.
if [ -f .env ]; then
    DB_USER="$(grep -m1 '^DB_USER=' .env | cut -d= -f2-)"
    DB_NAME="$(grep -m1 '^DB_NAME=' .env | cut -d= -f2-)"
fi
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-ct_upload_platform}"

if ! docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE" 2>>"$LOG_FILE"; then
    log "FAILED: pg_dump exited non-zero, removing incomplete file $BACKUP_FILE"
    rm -f "$BACKUP_FILE"
    exit 1
fi

if [ ! -s "$BACKUP_FILE" ]; then
    log "FAILED: backup file is empty, removing $BACKUP_FILE"
    rm -f "$BACKUP_FILE"
    exit 1
fi

log "OK: backed up to $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

# Prune backups older than RETENTION_DAYS.
find "$BACKUP_DIR" -maxdepth 1 -name 'db_backup_*.sql' -mtime "+${RETENTION_DAYS}" -print -delete >> "$LOG_FILE" 2>&1 || true
