#!/usr/bin/env bash
# Copy the daily CT-upload DB dumps (made by backup_db.sh) to the rhythm server.
#
# Runs from cron after backup_db.sh. Already-copied files are skipped by rsync;
# remote dumps older than REMOTE_RETENTION_DAYS are pruned.
#
# Env overrides: BACKUP_DIR (default backups/), REMOTE_HOST (default rhythm),
# REMOTE_DIR (default backups/ct_upload, relative to the remote home),
# REMOTE_RETENTION_DAYS (default 30)

set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
REMOTE_HOST="${REMOTE_HOST:-rhythm}"
REMOTE_DIR="${REMOTE_DIR:-backups/ct_upload}"
REMOTE_RETENTION_DAYS="${REMOTE_RETENTION_DAYS:-30}"
LOG_FILE="$BACKUP_DIR/backup.log"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=30"

log() { echo "[$(date -Iseconds)] $*" >> "$LOG_FILE"; }

shopt -s nullglob
files=("$BACKUP_DIR"/db_backup_*.sql)
if [ ${#files[@]} -eq 0 ]; then
    log "SYNC FAILED: no db_backup_*.sql files in $BACKUP_DIR"
    exit 1
fi

if rsync -a -z --partial --timeout=300 -e "$SSH" \
        --rsync-path="mkdir -p $REMOTE_DIR && rsync" \
        "${files[@]}" "$REMOTE_HOST:$REMOTE_DIR/" >>"$LOG_FILE" 2>&1; then
    log "SYNC OK: ${#files[@]} dump(s) present on $REMOTE_HOST:$REMOTE_DIR/"
else
    log "SYNC FAILED: rsync to $REMOTE_HOST:$REMOTE_DIR/"
    exit 1
fi

$SSH "$REMOTE_HOST" "find $REMOTE_DIR -maxdepth 1 -name 'db_backup_*.sql' -mtime +$REMOTE_RETENTION_DAYS -delete" >>"$LOG_FILE" 2>&1 || true
