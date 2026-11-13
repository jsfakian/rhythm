#!/usr/bin/env bash
# Daily backup of every app hosted on the rhythm edge server (backup-rhythm).
#
# Runs each app's existing backup script in sequence, then syncs the CT-upload
# dumps to the rhythm host. Intended for cron at 03:00.
#
# Env overrides: LOG_FILE (default ~/backups/backup_all.log)
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

run "medphys"   "$SRC_ROOT/medphys-tools/scripts/backup_medphys.sh"
run "code"      "$SRC_ROOT/code/scripts/backup_db.sh"
run "rhythm-db" "$SRC_ROOT/rhythm-repo/ct_upload_platform/scripts/backup_db.sh"
run "rhythm-sync" "$SRC_ROOT/rhythm-repo/ct_upload_platform/scripts/sync_backups_to_rhythm.sh"
run "ctdose-iqurad" "$SRC_ROOT/ctdose-iqurad/backup_ctdose_iqurad.sh"

if [ "$fail" -eq 0 ]; then
    log "DONE: all app backups succeeded"
    exit 0
fi
log "DONE WITH ERRORS"
exit 1
