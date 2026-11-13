#!/usr/bin/env bash
# Daily backup of apps hosted on rhythm-backup, then copy them to rhythm.
#
# Runs on rhythm-backup (this host). For each app: dump DB (+ data volumes
# where applicable) locally, then rsync everything to rhythm:~/backups/.
#
# Apps covered:
#   medphys  — MariaDB (medirad/weddb/xspectdb) + ctrad/idose volumes + .env
#   code     — Postgres code_db + med_app.sql seed
#   rhythm   — Postgres ct_upload_platform + Orthanc DICOM store
#
# Intended for cron at 03:00. Log: ~/backups/backup_all.log

set -uo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

SRC_ROOT="${SRC_ROOT:-$HOME/Documents/src}"
LOG_DIR="${LOG_DIR:-$HOME/backups}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/backup_all.log}"
mkdir -p "$LOG_DIR"
umask 077

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG_FILE"; }

fail=0
run() {
    local name="$1"
    shift
    log "START: $name"
    if "$@"; then
        log "OK: $name"
    else
        log "FAILED: $name (exit $?)"
        fail=1
    fi
}

# Local dumps on rhythm-backup (medphys/code scripts also try an early rsync).
run "backup-medphys" "$SRC_ROOT/medphys-tools/scripts/backup_medphys.sh"
run "backup-code" "$SRC_ROOT/code/scripts/backup_db.sh"
run "backup-rhythm-db" "$SRC_ROOT/rhythm-repo/ct_upload_platform/scripts/backup_db.sh"
run "backup-orthanc" "$SRC_ROOT/rhythm-repo/ct_upload_platform/scripts/backup_orthanc.sh"

# Authoritative off-box copy: everything → rhythm
run "sync-to-rhythm" "$SRC_ROOT/rhythm-repo/scripts/sync_all_backups_to_rhythm.sh"

if [ "$fail" -eq 0 ]; then
    log "DONE: rhythm-backup apps backed up to rhythm"
    exit 0
fi
log "DONE WITH ERRORS"
exit 1
