#!/usr/bin/env bash
# Build RHYTHM_manifest_tool.exe from create_rhythm_server_assigned_manifest_gui_with_uid.py
# on a non-Windows machine, and prove it actually works before touching the
# committed binary.
#
# PyInstaller does not cross-compile — it bundles the interpreter for the OS
# it runs on. This script drives PyInstaller *under Wine* (via the
# community `cdrx/pyinstaller-windows` Docker image) to produce a real
# Windows PE executable from Linux/macOS, then smoke-tests that exact
# binary under Wine against synthetic data before replacing
# RHYTHM_manifest_tool.exe.
#
# Usage:
#   ./build_windows_exe.sh
#
# Requires Docker (for the build + Wine smoke test — no local pydicom/
# openpyxl needed, the container supplies its own) and a host `python3`
# with `jsonschema` installed (for the final schema check — see below).
#
# What "test" means here: the built .exe is run under Wine in CLI mode
# against a synthetic GDPR-compliant DICOM ZIP + Excel template, and the
# manifest it produces is validated against the platform's real,
# authoritative v2 schema (ct_upload_platform/uploads/manifest_schema.py —
# imported directly, not re-implemented, so this can't silently drift out
# of sync with the server). That check runs on the *host*, not inside the
# build container: manifest_schema.py's type hints (e.g. `list[dict]`)
# need Python 3.9+, but the build image's own Linux-side Python is 3.5/3.7.
# RHYTHM_manifest_tool.exe is only overwritten if every step succeeds.
#
# Known limitation: `cdrx/pyinstaller-windows` is an old, unmaintained image
# (PyInstaller 3.6 / Python 3.7 / Wine 5.0). It produces a working binary
# (verified below) but a GitHub Actions `windows-latest` job would give a
# more current, more confidently-portable build — worth migrating to if
# this script needs to run often. This script does not open a Tk window
# (no display in the container), so it cannot confirm the GUI itself
# renders — only that the shared build_manifest() logic behind both the
# GUI and the CLI works. Do a real double-click smoke test on Windows
# before a wide partner rollout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOL_NAME="RHYTHM_manifest_tool"
TOOL_SCRIPT="create_rhythm_server_assigned_manifest_gui_with_uid.py"
IMAGE="cdrx/pyinstaller-windows:python3"
SCHEMA_FILE="$REPO_ROOT/ct_upload_platform/uploads/manifest_schema.py"

# pydicom's optional pixel-data encoder backends are loaded via
# importlib.import_module() at runtime, not a plain `import` statement —
# PyInstaller's static analysis can't see them, so they must be listed
# explicitly or the frozen exe crashes on first pydicom use with
# "ModuleNotFoundError: No module named 'pydicom.encoders.gdcm'".
PYDICOM_HIDDEN_IMPORTS=(
  --hidden-import pydicom.encoders.gdcm
  --hidden-import pydicom.encoders.native
  --hidden-import pydicom.encoders.pylibjpeg
)

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required but not found on PATH." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required on the host for the final schema check." >&2
  exit 1
fi

if ! python3 -c "import jsonschema" >/dev/null 2>&1; then
  echo "ERROR: the host python3 needs jsonschema installed: pip install jsonschema" >&2
  exit 1
fi

if [ ! -f "$SCRIPT_DIR/$TOOL_SCRIPT" ]; then
  echo "ERROR: $TOOL_SCRIPT not found next to this script." >&2
  exit 1
fi

if [ ! -f "$SCHEMA_FILE" ]; then
  echo "ERROR: could not find manifest_schema.py at $SCHEMA_FILE" >&2
  echo "       (expected the full rhythm-repo checkout, not just this folder)" >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
cleanup() {
  # Everything under WORKDIR was written by root inside the containers
  # above; reclaim ownership before rm -rf can actually remove it.
  docker run --rm -v "$WORKDIR:/w" --entrypoint sh "$IMAGE" \
    -c "chown -R $(id -u):$(id -g) /w" >/dev/null 2>&1 || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

echo "== Work dir: $WORKDIR"
cp "$SCRIPT_DIR/$TOOL_SCRIPT" "$WORKDIR/"
cp "$SCRIPT_DIR/dev/generate_test_fixtures.py" "$WORKDIR/"
cp "$SCHEMA_FILE" "$WORKDIR/manifest_schema.py"
printf 'pydicom\nopenpyxl\n' > "$WORKDIR/requirements.txt"

echo
echo "== 1. Building $TOOL_NAME.exe under Wine (image: $IMAGE) =="
docker run --rm -v "$WORKDIR:/src/" "$IMAGE" \
  "pyinstaller --onefile --noconsole --name $TOOL_NAME ${PYDICOM_HIDDEN_IMPORTS[*]} $TOOL_SCRIPT"

EXE_PATH="$WORKDIR/dist/$TOOL_NAME.exe"
if [ ! -f "$EXE_PATH" ]; then
  echo "ERROR: build did not produce $EXE_PATH" >&2
  exit 1
fi

FILE_TYPE="$(file -b "$EXE_PATH")"
echo "Built: $EXE_PATH ($FILE_TYPE)"
case "$FILE_TYPE" in
  *"PE32"*"executable"*) ;;
  *)
    echo "ERROR: output is not a Windows PE executable: $FILE_TYPE" >&2
    exit 1
    ;;
esac

echo
echo "== 2. Generating synthetic test fixtures (DICOM ZIP + Excel template) =="
docker run --rm -v "$WORKDIR:/src/" --entrypoint sh "$IMAGE" -c "
  set -e
  pip install -q pydicom openpyxl
  cd /src
  python generate_test_fixtures.py --out-dir testdata
"

echo
echo "== 3. Running the built exe under Wine against the test fixtures =="
docker run --rm -v "$WORKDIR:/src/" --entrypoint sh "$IMAGE" -c "
  set -e
  export WINEDEBUG=-all
  cd /src
  wine 'dist/$TOOL_NAME.exe' \
    --input testdata/template.xlsx \
    --zip-folder testdata/zips \
    --out testdata/out/rhythm_upload_manifest.json
"

OUTPUT_MANIFEST="$WORKDIR/testdata/out/rhythm_upload_manifest.json"
if [ ! -s "$OUTPUT_MANIFEST" ]; then
  echo "ERROR: the exe did not produce a manifest at $OUTPUT_MANIFEST" >&2
  exit 1
fi

echo
echo "== 4. Validating the produced manifest against the real server schema (host python3) =="
python3 - "$WORKDIR" <<'PYEOF'
import importlib.util
import json
import sys
from pathlib import Path

workdir = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("manifest_schema", workdir / "manifest_schema.py")
manifest_schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest_schema)

manifest = json.loads((workdir / "testdata/out/rhythm_upload_manifest.json").read_text())
errors = manifest_schema.validate_manifest_v2(manifest)
if errors:
    print("Schema validation FAILED:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("Schema validation passed:")
print(json.dumps(manifest, indent=2))
PYEOF

echo
echo "== 5. All checks passed — installing the new exe =="
cp "$EXE_PATH" "$SCRIPT_DIR/$TOOL_NAME.exe"
echo "Updated: $SCRIPT_DIR/$TOOL_NAME.exe ($(du -h "$SCRIPT_DIR/$TOOL_NAME.exe" | cut -f1))"
echo
echo "Done. Remember: this proves the packaged logic works under Wine, not"
echo "that the Tk GUI window renders correctly on real Windows — do a"
echo "double-click smoke test there before a wide partner rollout."
