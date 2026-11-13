#!/usr/bin/env bash
# Daily backup of every app hosted on the rhythm edge server (backup-rhythm).
#
# Order:
#   1. Database dumps (MariaDB medphys, Postgres CODE, Postgres RHYTHM)
#   2. App data volumes / remote mirrors that ride along with those scripts
#   3. Orthanc DICOM store (index + images)
#   4. Sync RHYTHM Postgres dumps to the rhythm host
#
# Intended for cron at 03:00. Log: ~/backups/backup_all.log
# Exit 0 only if every step succeeded.

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

# --- Databases (and the volume/env artifacts those scripts also write) ---
# medphys: mysqldump medirad + weddb + xspectdb (+ ctrad/idose data vols)
run "db-medphys" "$SRC_ROOT/medphys-tools/scripts/backup_medphys.sh"
# CODE: pg_dump code_db (+ med_app.sql seed)
run "db-code" "$SRC_ROOT/code/scripts/backup_db.sh"
# RHYTHM: pg_dump ct_upload_platform
run "db-rhythm" "$SRC_ROOT/rhythm-repo/ct_upload_platform/scripts/backup_db.sh"
# ctdose-iqurad mirror: mysqldump medirad/weddb/xspectdb/imgqualdb from ctdose
run "db-ctdose-iqurad" "$SRC_ROOT/ctdose-iqurad/backup_ctdose_iqurad.sh"

# --- Orthanc DICOM store (SQLite index + images) ---
run "orthanc" "$SRC_ROOT/rhythm-repo/ct_upload_platform/scripts/backup_orthanc.sh"

# --- Off-box copy of RHYTHM Postgres dumps ---
run "rhythm-sync" "$SRC_ROOT/rhythm-repo/ct_upload_platform/scripts/sync_backups_to_rhythm.sh"

if [ "$fail" -eq 0 ]; then
    log "DONE: all app + DB backups succeeded"
    exit 0
fi
log "DONE WITH ERRORS"
exit 1
