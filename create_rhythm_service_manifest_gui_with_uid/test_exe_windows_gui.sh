#!/usr/bin/env bash
# Real-Windows GUI test of RHYTHM_manifest_tool.exe.
#
# build_windows_exe.sh builds the .exe with PyInstaller under Wine and runs
# it there in CLI mode. That never shows the Tk window on real Windows. This
# script does: it boots a Windows 11 VM (dockur/windows, KVM) and, through
# the VM's web viewer, opens the .exe from Explorer like a partner would,
# fills in the form, generates a manifest from a 3-study test batch
# (retain_after_project yes / no / empty), copies it back and checks it:
#   * one item per ZIP, each with its own DICOM StudyInstanceUID
#   * retain_after_project is true / false / null as declared
#   * the manifest passes the real server schema (validate_manifest_v2)
# Screenshots of every step go to $WINTEST_DIR/runs/<timestamp>/.
#
# The VM is created once and reused: its installed disk lives in
# $WINTEST_DIR/storage. The first run downloads Windows 11 from Microsoft
# (~6 GB) and installs it unattended (30-45 min); later runs boot in ~1 min.
#
# Usage:  ./test_exe_windows_gui.sh [--keep-running]
#         make test-exe-windows            (from ct_upload_platform/)
# Env:    WINTEST_DIR   (default ~/.cache/rhythm-wintest)
#         WINTEST_PORT  web viewer port on 127.0.0.1 (default 8006)
#         EXE           .exe to test (default ./RHYTHM_manifest_tool.exe)
# Needs:  docker with /dev/kvm, node, ct_upload_platform/node_modules
#         (npm install) and ct_upload_platform/.venv (pydicom, openpyxl, jsonschema).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$REPO_ROOT/ct_upload_platform"
PY="$APP_DIR/.venv/bin/python"
WINTEST_DIR="${WINTEST_DIR:-$HOME/.cache/rhythm-wintest}"
PORT="${WINTEST_PORT:-8006}"
EXE="${EXE:-$SCRIPT_DIR/RHYTHM_manifest_tool.exe}"
CONTAINER="rhythm_wintest"
IMAGE="dockurr/windows:latest"
KEEP_RUNNING=0
[ "${1:-}" = "--keep-running" ] && KEEP_RUNNING=1

die() { echo "ERROR: $*" >&2; exit 1; }
[ -e /dev/kvm ] || die "/dev/kvm is missing: the Windows VM needs hardware virtualisation"
[ -x "$PY" ] || die "$PY not found (create ct_upload_platform/.venv first)"
[ -d "$APP_DIR/node_modules/playwright" ] || die "run 'npm install' in ct_upload_platform first"
[ -f "$EXE" ] || die "no .exe at $EXE (build it with build_windows_exe.sh)"

if ! docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "== Creating the Windows VM (first run: downloads and installs Windows 11, 30-45 min)"
  mkdir -p "$WINTEST_DIR/storage" "$WINTEST_DIR/shared"
  docker run -d --name "$CONTAINER" \
    -p "127.0.0.1:$PORT:8006" \
    --device=/dev/kvm --device=/dev/net/tun --cap-add NET_ADMIN \
    -e VERSION=11 -e RAM_SIZE=4G -e CPU_CORES=2 -e DISK_SIZE=40G \
    -e USERNAME=tester -e PASSWORD=rhythm-test \
    -v "$WINTEST_DIR/storage:/storage" -v "$WINTEST_DIR/shared:/data" \
    --stop-timeout 120 "$IMAGE" >/dev/null
  READY_TIMEOUT=3600
elif [ "$(docker container inspect -f '{{.State.Running}}' "$CONTAINER")" != "true" ]; then
  echo "== Starting the existing Windows VM"
  docker start "$CONTAINER" >/dev/null
  READY_TIMEOUT=900
else
  echo "== Windows VM already running"
  READY_TIMEOUT=900
fi

# The share is whatever host folder the container mounts at /data.
SHARE="$(docker container inspect "$CONTAINER" \
  --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')"
[ -n "$SHARE" ] || die "container $CONTAINER has no /data mount"

echo "== Waiting for the VM to boot"
# Look since the container's own start, so this works whether we just
# created or started it, or it was already running before this script.
booted_since="$(docker container inspect -f '{{.State.StartedAt}}' "$CONTAINER")"
booted=0
for _ in $(seq 360); do
  if docker logs --since "$booted_since" "$CONTAINER" 2>&1 | grep -q "started successfully"; then
    booted=1; break
  fi
  sleep 10
done
[ "$booted" -eq 1 ] || die "the VM did not boot within an hour; see 'docker logs $CONTAINER'"

RUN_DIR="$WINTEST_DIR/runs/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN_DIR"

echo "== Preparing the test batch"
# Files written over the share from Windows are owned by root on the host,
# so clean the share from inside the container.
# A new folder per run on the share (Windows caches SMB directory handles,
# so a folder deleted and recreated here can no longer be read there).
RUN_NAME="run_$(basename "$RUN_DIR")"
docker exec "$CONTAINER" sh -c "rm -rf /data/run_* /data/in /data/out && mkdir -p /data/$RUN_NAME/in /data/$RUN_NAME/out && chmod -R 777 /data/$RUN_NAME"
BATCH="$(mktemp -d)"
trap 'rm -rf "$BATCH"' EXIT
"$PY" -I "$SCRIPT_DIR/dev/make_windows_test_batch.py" --out-dir "$BATCH"
cp "$EXE" "$BATCH/RHYTHM_manifest_tool.exe"
docker cp "$BATCH/." "$CONTAINER:/data/$RUN_NAME/in/"
cp "$BATCH/expected.json" "$RUN_DIR/"

echo "== Driving the GUI on Windows (screenshots: $RUN_DIR)"
node "$SCRIPT_DIR/dev/windows_gui_driver.cjs" \
  --share "$SHARE" --shots "$RUN_DIR" --run "$RUN_NAME" --port "$PORT" --ready-timeout "$READY_TIMEOUT"

docker cp "$CONTAINER:/data/$RUN_NAME/out/rhythm_upload_manifest.json" "$RUN_DIR/" \
  || die "the tool did not produce a manifest; see the screenshots in $RUN_DIR"

echo "== Checking the manifest"
"$PY" -I - "$RUN_DIR/rhythm_upload_manifest.json" "$RUN_DIR/expected.json" "$APP_DIR/uploads/manifest_schema.py" <<'EOF'
import importlib.util, json, sys
manifest = json.load(open(sys.argv[1]))
expected = json.load(open(sys.argv[2]))
spec = importlib.util.spec_from_file_location("manifest_schema", sys.argv[3])
schema = importlib.util.module_from_spec(spec); spec.loader.exec_module(schema)

errors = schema.validate_manifest_v2(manifest)
assert not errors, f"server schema rejects the manifest: {errors}"
items = {i["filename"]: i for i in manifest["items"]}
assert len(items) == len(expected), f"expected {len(expected)} items, got {len(items)}"
assert len({i["dicom_uid"] for i in manifest["items"]}) == len(expected), "StudyInstanceUIDs are not distinct"
for exp in expected:
    got = items[exp["filename"]].get("retain_after_project", "MISSING")
    assert got == exp["retain_after_project"], f"{exp['filename']}: retain_after_project {got!r}, expected {exp['retain_after_project']!r}"
    print(f"  {exp['filename']}: retain_after_project = {json.dumps(got)}  OK")
print(f"  tool_version {manifest.get('tool_version')}, server schema: valid")
EOF

if [ "$KEEP_RUNNING" -eq 0 ]; then
  echo "== Stopping the VM (disk kept in $WINTEST_DIR/storage for the next run)"
  docker stop "$CONTAINER" >/dev/null
fi
echo "PASS: the .exe works through its GUI on real Windows 11. Evidence: $RUN_DIR"
