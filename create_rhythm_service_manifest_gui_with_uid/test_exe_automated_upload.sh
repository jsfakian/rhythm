#!/usr/bin/env bash
# End-to-end pipeline test: the committed RHYTHM_manifest_tool.exe (run
# under Wine, the exact binary partners run) generates a manifest for a
# real registered protocol, and that manifest is driven through the real
# Automated Upload API against the live running app — proving the
# partner-facing .exe and the server-side pipeline actually interoperate,
# not just that each works in isolation.
#
# This is a different (complementary) check from build_windows_exe.sh:
#   - build_windows_exe.sh: build the .exe, run it once, sanity-check its
#     output against the schema. Doesn't touch a running app.
#   - this script: use the ALREADY-BUILT, committed .exe against a REAL
#     registered protocol in the live dev stack, and confirm the whole
#     upload -> Celery worker -> Orthanc pipeline produces the same
#     CTExamination/StudyMapping result Manual Exam Entry would.
#
# Prerequisites:
#   - Docker
#   - host python3 with jsonschema installed
#   - the ct_upload_platform Docker stack already running against a dev/
#     test database you don't mind writing throwaway rows to (`make up`
#     in ct_upload_platform/) — this talks to the LIVE stack, not a
#     disposable test DB. Every row and Orthanc study this script creates
#     is deleted again on exit, success or failure.
#   - RHYTHM_manifest_tool.exe already built (see build_windows_exe.sh)
#
# Usage:
#   ./test_exe_automated_upload.sh
#
# Steps:
#   1. Create a real CTProtocol (+ scanner + test user) in the live DB.
#   2. Generate a synthetic GDPR-compliant DICOM ZIP + Excel template
#      referencing that protocol's real id and site code.
#   3. Run the committed RHYTHM_manifest_tool.exe under Wine (CLI mode)
#      against that template to produce a real manifest.json.
#   4. Sanity-check that manifest against the real schema (host python3).
#   5. Copy the manifest + ZIP into the live web container and drive the
#      actual Automated Upload flow (validate-manifest -> chunked/init ->
#      chunk -> complete), waiting for the real Celery worker to process
#      it against the real Orthanc.
#   6. Verify the resulting CTExamination/StudyMapping match the protocol.
#   7. Clean up every row and Orthanc study this run created (always, via
#      a trap — even on failure or Ctrl-C).
#
# Exits non-zero on any failure.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CT_UPLOAD_DIR="$REPO_ROOT/ct_upload_platform"
TOOL_NAME="RHYTHM_manifest_tool"
EXE_PATH="$SCRIPT_DIR/$TOOL_NAME.exe"
IMAGE="cdrx/pyinstaller-windows:python3"
SCHEMA_FILE="$CT_UPLOAD_DIR/uploads/manifest_schema.py"
DJANGO_STEPS="$SCRIPT_DIR/dev/e2e_django_steps.py"
ZIP_FILENAME="e2e_exe_test_study.zip"

compose() {
  (cd "$CT_UPLOAD_DIR" && docker compose "$@")
}

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required but not found on PATH." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import jsonschema" >/dev/null 2>&1; then
  echo "ERROR: host python3 with jsonschema is required (pip install jsonschema)." >&2
  exit 1
fi
if [ ! -f "$EXE_PATH" ]; then
  echo "ERROR: $EXE_PATH not found — run ./build_windows_exe.sh first." >&2
  exit 1
fi
if [ ! -f "$SCHEMA_FILE" ]; then
  echo "ERROR: could not find manifest_schema.py at $SCHEMA_FILE" >&2
  exit 1
fi
if ! compose exec -T web true >/dev/null 2>&1; then
  echo "ERROR: the ct_upload_platform stack doesn't seem to be running." >&2
  echo "       Start it with: (cd ct_upload_platform && make up)" >&2
  exit 1
fi

TAG="exe$(date +%s)$RANDOM"
WORKDIR="$(mktemp -d)"
USERNAME=""  # populated once step 1 succeeds; must stay defined (set -u) and
             # empty-checked below — never rm -rf "/app/raw_data/$USERNAME"
             # unguarded, or an empty value would target raw_data/ itself.
echo "== Work dir: $WORKDIR  (tag: $TAG)"

cleanup() {
  local status=$?
  echo
  echo "== Cleanup (tag: $TAG) =="
  compose exec -T -e E2E_MODE=cleanup -e E2E_TAG="$TAG" web \
    python manage.py shell < "$DJANGO_STEPS" 2>&1 | sed 's/^/  /' || true
  # docker compose cp writes as root; the container's default exec user
  # can't rm its own copies back out of /tmp (sticky bit) — force root.
  compose exec -T -u root web sh -c "rm -f '/tmp/e2e_manifest_$TAG.json' '/tmp/e2e_study_$TAG.zip'" >/dev/null 2>&1 || true
  if [ -n "$USERNAME" ]; then
    compose exec -T -u root web sh -c "rm -rf '/app/raw_data/$USERNAME'" >/dev/null 2>&1 || true
  fi
  docker run --rm -v "$WORKDIR:/w" --entrypoint sh "$IMAGE" \
    -c "chown -R $(id -u):$(id -g) /w" >/dev/null 2>&1 || true
  rm -rf "$WORKDIR"
  exit "$status"
}
trap cleanup EXIT

echo
echo "== 1. Creating a real protocol + scanner + test user in the live DB =="
SETUP_OUT="$(compose exec -T -e E2E_MODE=setup -e E2E_TAG="$TAG" web python manage.py shell < "$DJANGO_STEPS" 2>&1)"
echo "$SETUP_OUT" | sed 's/^/  /'
PROTOCOL_ID="$(echo "$SETUP_OUT" | sed -n 's/^PROTOCOL_ID=//p')"
SCANNER_ID="$(echo "$SETUP_OUT" | sed -n 's/^SCANNER_ID=//p')"
SITE_CODE="$(echo "$SETUP_OUT" | sed -n 's/^SITE_CODE=//p')"
USERNAME="$(echo "$SETUP_OUT" | sed -n 's/^USERNAME=//p')"
if [ -z "$PROTOCOL_ID" ] || [ -z "$SCANNER_ID" ] || [ -z "$SITE_CODE" ] || [ -z "$USERNAME" ]; then
  echo "ERROR: setup step did not report all of PROTOCOL_ID/SCANNER_ID/SITE_CODE/USERNAME." >&2
  exit 1
fi
echo "protocol_id=$PROTOCOL_ID scanner_id=$SCANNER_ID site_code=$SITE_CODE username=$USERNAME"

echo
echo "== 2. Generating a synthetic DICOM ZIP + Excel template for that protocol =="
docker run --rm -v "$WORKDIR:/src/" -v "$SCRIPT_DIR/dev/generate_test_fixtures.py:/src/generate_test_fixtures.py:ro" \
  -v "$SCRIPT_DIR/create_rhythm_server_assigned_manifest_gui_with_uid.py:/src/create_rhythm_server_assigned_manifest_gui_with_uid.py:ro" \
  --entrypoint sh "$IMAGE" -c "
    set -e
    pip install -q pydicom openpyxl
    cd /src
    python generate_test_fixtures.py --out-dir testdata --site-code '$SITE_CODE' --protocol-id '$PROTOCOL_ID' --zip-filename '$ZIP_FILENAME'
  "
if [ $? -ne 0 ]; then
  echo "ERROR: fixture generation failed." >&2
  exit 1
fi

echo
echo "== 3. Running the committed $TOOL_NAME.exe under Wine against those fixtures =="
cp "$EXE_PATH" "$WORKDIR/$TOOL_NAME.exe"
docker run --rm -v "$WORKDIR:/src/" --entrypoint sh "$IMAGE" -c "
  set -e
  export WINEDEBUG=-all
  cd /src
  wine '$TOOL_NAME.exe' --input testdata/template.xlsx --zip-folder testdata/zips --out testdata/out/rhythm_upload_manifest.json
"
if [ $? -ne 0 ]; then
  echo "ERROR: the .exe failed to produce a manifest." >&2
  exit 1
fi
MANIFEST_PATH="$WORKDIR/testdata/out/rhythm_upload_manifest.json"
ZIP_PATH="$WORKDIR/testdata/zips/$ZIP_FILENAME"
if [ ! -s "$MANIFEST_PATH" ] || [ ! -s "$ZIP_PATH" ]; then
  echo "ERROR: expected output files are missing." >&2
  exit 1
fi

echo
echo "== 4. Sanity-checking the manifest against the real schema (host python3) =="
python3 - "$SCHEMA_FILE" "$MANIFEST_PATH" <<'PYEOF'
import importlib.util, json, sys
schema_file, manifest_file = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("manifest_schema", schema_file)
manifest_schema = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest_schema)
manifest = json.loads(open(manifest_file).read())
errors = manifest_schema.validate_manifest_v2(manifest)
if errors:
    print("Schema validation FAILED:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("Schema validation passed.")
PYEOF
if [ $? -ne 0 ]; then
  echo "ERROR: the .exe's output did not pass schema validation." >&2
  exit 1
fi

echo
echo "== 5. Driving the real Automated Upload flow against the live app =="
compose cp "$MANIFEST_PATH" "web:/tmp/e2e_manifest_$TAG.json"
compose cp "$ZIP_PATH" "web:/tmp/e2e_study_$TAG.zip"
DRIVE_OUT="$(compose exec -T \
  -e E2E_MODE=drive -e E2E_TAG="$TAG" -e E2E_USERNAME="$USERNAME" \
  -e E2E_MANIFEST_PATH="/tmp/e2e_manifest_$TAG.json" -e E2E_ZIP_PATH="/tmp/e2e_study_$TAG.zip" \
  -e E2E_PROTOCOL_ID="$PROTOCOL_ID" -e E2E_SCANNER_ID="$SCANNER_ID" \
  web python manage.py shell < "$DJANGO_STEPS" 2>&1)"
echo "$DRIVE_OUT" | sed 's/^/  /'

echo
if echo "$DRIVE_OUT" | grep -q '^RESULT=PASS$'; then
  echo "=== RESULT: PASS — the .exe's manifest produced the same outcome a manual upload would ==="
  exit 0
else
  echo "=== RESULT: FAIL — see output above ===" >&2
  exit 1
fi
