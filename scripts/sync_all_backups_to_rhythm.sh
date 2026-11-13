#!/usr/bin/env bash
# Push every local app backup from rhythm-backup to the rhythm host.
#
# Source (this host): medphys, CODE, RHYTHM Postgres dumps, Orthanc archives.
# Destination: rhythm:~/backups/{medphys,code,ct_upload,orthanc}/
#
# Env overrides: REMOTE_HOST (default rhythm), REMOTE_RETENTION_DAYS (default 30),
# ORTHANC_RETENTION_DAYS (default 7; Orthanc archives are large).

set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

SRC_ROOT="${SRC_ROOT:-$HOME/Documents/src}"
REMOTE_HOST="${REMOTE_HOST:-rhythm}"
REMOTE_RETENTION_DAYS="${REMOTE_RETENTION_DAYS:-30}"
ORTHANC_RETENTION_DAYS="${ORTHANC_RETENTION_DAYS:-7}"
LOG_FILE="${LOG_FILE:-$HOME/backups/backup_all.log}"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=30"

mkdir -p "$HOME/backups"
log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG_FILE"; }

rsync_dir() {
    local src="$1" remote_subdir="$2" pattern="$3" retention="$4"
    local remote="backups/$remote_subdir"
    if [ ! -d "$src" ]; then
        log "SKIP: $src missing"
        return 0
    fi
    shopt -s nullglob
    local files=("$src"/$pattern)
    if [ ${#files[@]} -eq 0 ]; then
        log "SKIP: no $pattern in $src"
        return 0
    fi
    if rsync -a -z --partial --timeout=600 -e "$SSH" \
            --rsync-path="mkdir -p $remote && chmod 700 $remote && rsync" \
            "${files[@]}" "$REMOTE_HOST:$remote/" >>"$LOG_FILE" 2>&1; then
        log "OK: synced ${#files[@]} file(s) → $REMOTE_HOST:$remote/"
        $SSH "$REMOTE_HOST" \
            "find $remote -maxdepth 1 -type f -name '$pattern' -mtime +$retention -delete" \
            >>"$LOG_FILE" 2>&1 || true
    else
        log "FAILED: rsync $src → $REMOTE_HOST:$remote/"
        return 1
    fi
}

fail=0
rsync_dir "$HOME/backups/medphys" medphys '*_[0-9]*_[0-9]*' "$REMOTE_RETENTION_DAYS" || fail=1
rsync_dir "$HOME/backups/code" code '*_[0-9]*_[0-9]*' "$REMOTE_RETENTION_DAYS" || fail=1
rsync_dir "$SRC_ROOT/rhythm-repo/ct_upload_platform/backups" ct_upload 'db_backup_*.sql' "$REMOTE_RETENTION_DAYS" || fail=1
rsync_dir "$SRC_ROOT/rhythm-repo/ct_upload_platform/backups/orthanc" orthanc 'orthanc_backup_*.tar.gz' "$ORTHANC_RETENTION_DAYS" || fail=1

[ "$fail" -eq 0 ] || exit 1
log "DONE: all rhythm-backup app backups present on $REMOTE_HOST"
