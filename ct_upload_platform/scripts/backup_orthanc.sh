#!/usr/bin/env bash
# Daily backup of the Orthanc image store (DICOM files + Orthanc's index).
#
# Archives the Orthanc data volume through a throwaway, read-only helper
# container, so the running Orthanc is never stopped or written to. Prunes
# archives older than RETENTION_DAYS. Intended to run from cron at night,
# when uploads are unlikely; see README "Orthanc Backups".
#
# Usage: backup_orthanc.sh
# Env overrides:
#   RETENTION_DAYS   days of archives to keep (default 7; images are large)
#   ORTHANC_VOLUME   docker volume name or host path of Orthanc's data
#                    (default: read from the running container, so it follows
#                    ORTHANC_DATA_PATH when the store lives on the rhythm HDDs)
#   BACKUP_DIR       where archives go (default: backups/orthanc). Point it at a
#                    different physical disk from the Orthanc volume.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups/orthanc}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
CONTAINER="ct_upload_orthanc"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/orthanc_backup_${TIMESTAMP}.tar.gz"
LOG_FILE="$BACKUP_DIR/backup.log"

mkdir -p "$BACKUP_DIR"

log() {
    echo "[$(date -Iseconds)] $*" >> "$LOG_FILE"
}

if [ -z "${ORTHANC_VOLUME:-}" ]; then
    ORTHANC_VOLUME="$(docker inspect "$CONTAINER" \
        --format '{{range .Mounts}}{{if eq .Destination "/var/lib/orthanc/db"}}{{if .Name}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' 2>>"$LOG_FILE" || true)"
fi
if [ -z "$ORTHANC_VOLUME" ]; then
    log "FAILED: could not determine the Orthanc data volume (is $CONTAINER running?)"
    exit 1
fi

# Refuse to start if the archive could fill the disk: require free space of
# at least twice the current volume size (gzip rarely helps much on DICOM).
VOLUME_KB="$(docker run --rm -v "$ORTHANC_VOLUME":/data:ro alpine du -sk /data | cut -f1)"
FREE_KB="$(df -Pk "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
if [ "$FREE_KB" -lt $((VOLUME_KB * 2)) ]; then
    log "FAILED: not enough free disk (${FREE_KB} KB free, need $((VOLUME_KB * 2)) KB for a ${VOLUME_KB} KB volume)"
    exit 1
fi

if ! docker run --rm -v "$ORTHANC_VOLUME":/data:ro alpine \
        tar -czf - -C /data . > "$BACKUP_FILE" 2>>"$LOG_FILE"; then
    log "FAILED: tar exited non-zero, removing incomplete file $BACKUP_FILE"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# A truncated archive fails the integrity test; never keep one silently.
if ! gzip -t "$BACKUP_FILE" 2>>"$LOG_FILE"; then
    log "FAILED: archive failed gzip integrity check, removing $BACKUP_FILE"
    rm -f "$BACKUP_FILE"
    exit 1
fi

log "OK: backed up volume $ORTHANC_VOLUME to $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

find "$BACKUP_DIR" -maxdepth 1 -name 'orthanc_backup_*.tar.gz' -mtime "+${RETENTION_DAYS}" -print -delete >> "$LOG_FILE" 2>&1 || true
