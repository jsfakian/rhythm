# RHYTHM — CT Medical Image Upload Platform

A Django-based ingestion pipeline for pre-anonymized DICOM CT images. Research partners submit anonymized studysets, the platform validates GDPR anonymization compliance, assigns a Repository Study ID, and stores accepted images in an Orthanc DICOM server.

**PHI boundary:** The Django database never stores patient names, dates of birth, MRNs, or any identifying information. Only pseudo-identifiers and audit records are stored.

---

## Quick Start

```bash
cd ct_upload_platform
cp .env.example .env          # fill in secrets (see Configuration below)
make build                    # build Docker images
make up                       # start web, worker, db, redis, orthanc
make migrate                  # run Django migrations

# Create a login (partners use this for the upload GUI) and, if needed, an API token
docker compose exec -it web python manage.py createsuperuser
docker compose exec web python manage.py create_upload_token <username>
```

| Service | URL |
|---------|-----|
| Web UI (dev, direct) | http://localhost:8003 |
| Web UI (production, via Caddy/TLS) | https://your-domain |
| Django Admin | http://localhost:8003/admin |
| Orthanc | http://localhost:8042 (host-only; not exposed publicly) |

---

## Requirements

- Docker + Docker Compose (v2 `docker compose` CLI)
- Node.js + npx (for Playwright E2E tests only)
- Python 3.13 (local development; Docker is the recommended runtime)

---

## Architecture Overview

Five Docker services work together:

| Service | Role |
|---------|------|
| `web` | Django + Gunicorn. HTTP API and browser UI. |
| `worker` | Celery. Async DICOM validation and Orthanc push. |
| `db` | PostgreSQL 15. Audit records, pseudo-ID mappings. No DICOM data. |
| `redis` | Celery broker and result backend. |
| `orthanc` | Authoritative DICOM store. Accepts via STOW-RS; serves via DICOMweb. |
| `caddy` | Reverse proxy / TLS termination in front of `web` (production). |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design including data flow, module map, database schema, and security model.

---

## Submitting Data

There are two ways to get a studyset into the repository:

| | Pipeline | Who it's for |
|---|---|---|
| **Recommended** | **v2 — server-assigned batch** | Partner institutions submitting one or more studysets, via the browser GUI |
| Legacy | **v1 — single-study archive** | A single `.tar`/`.tar.gz` archive with an inline `manifest.json`, submitted directly to the REST API |

Both pipelines run the same GDPR anonymization validation (see below) before anything reaches Orthanc, and in both cases **the server — never the partner — assigns the final Repository Study ID.**

### v2: Server-Assigned Batch (recommended)

**1. Anonymize locally, first.** This platform validates anonymization; it does not perform it. Before packaging anything, every studyset must already have patient name, original hospital `PatientID`, accession number, date of birth, national identifier, and any other direct identifier removed.

**2. Get the manifest generator tool.** Partners prepare their upload package with a small companion tool (Python script + Windows `.exe`, same behavior either way), in [`create_rhythm_service_manifest_gui_with_uid/`](create_rhythm_service_manifest_gui_with_uid/) along with the Excel metadata template. It does not anonymize DICOM files — it only reads already-anonymized ZIPs and builds the upload manifest. Full partner-facing instructions: [`create_rhythm_service_manifest_gui_with_uid/README.md`](create_rhythm_service_manifest_gui_with_uid/README.md) (also available as a standalone HTML file in the same folder).

**3. Prepare one ZIP per studyset.** Each ZIP contains only the DICOM files for one CT studyset (one `StudyInstanceUID`) — no reports, screenshots, or nested archives. Suggested layout for the working folder:

```text
RHYTHM_Upload/
├── metadata/
│   └── rhythm_server_assigned_metadata_template.xlsx
├── zips/
│   ├── study_001_anonymized.zip
│   └── study_002_anonymized.zip
└── output/
```

**4. Fill in one Excel row per ZIP:**

| Column | Description |
|---|---|
| `filename` | Exact ZIP filename — must match a file in the selected ZIP folder |
| `site_code` | Coded submitting site, e.g. `S001` — must match (case-insensitively) the submitting site of the protocol referenced by `protocol_id`, or the server rejects the row |
| `protocol_id` | UUID of a protocol already registered in the RHYTHM app — copy it from the **Protocol Records** page (`/protocols/records/`). The server derives anatomical region, clinical indication, contrast, protocol type, examination group, and scanner from this protocol — none of those are re-typed in the manifest |
| `patient_weight_kg`, `patient_age_years` | Numeric |
| `ctdivol_mgy`, `dlp_mgy_cm` | Dose metrics |
| `image_quality` | e.g. `Acceptable` |

> ⚠️ If the protocol you need isn't registered yet, add it first via the app's Protocol GUI — the manifest tool cannot create one for you, and an unrecognized `protocol_id` fails the upload.

**5. Generate the manifest** with the tool from step 2:

```bash
# Windows executable
create_rhythm_server_assigned_manifest_gui_with_uid.exe
# → select the Excel file, the ZIP folder, an output path, and an optional batch ID

# Python
pip install pydicom openpyxl
python create_rhythm_server_assigned_manifest_gui_with_uid.py \
  --input metadata\rhythm_server_assigned_metadata_template.xlsx \
  --zip-folder zips\ \
  --out output\rhythm_upload_manifest.json \
  --batch S001-2026-07-12-001
```

This produces `rhythm_upload_manifest.json` (submit this) and `rhythm_upload_manifest_index.csv` (for your own review). Before writing them, the tool checks that: the Excel file is readable and has the required columns; every `filename` exists in the ZIP folder and is a valid ZIP; each ZIP contains readable DICOM files with exactly **one** `StudyInstanceUID` (it stops with an error otherwise — split the ZIP and re-run); and, if enabled, computes each ZIP's SHA-256 checksum.

A generated item looks like this:

```json
{
  "ref": "ROW0001",
  "filename": "study_001_anonymized.zip",
  "dicom_uid": "2.25.23890534782093478203948203948203948",
  "dicom": {
    "patient_id": "P-8F3KQ9M2X7AD",
    "series_uids": ["2.25.90823475098237450982374509823745098"],
    "series_count": 1,
    "instance_count": 180
  },
  "site_code": "S001",
  "protocol_id": "5f6a1e9c-6b1a-4b7e-9c2d-8a1e5f6a1e9c",
  "image_quality": "Acceptable"
}
```

`dicom_uid`/`dicom` are informational only — the server independently re-extracts the `StudyInstanceUID` from the ZIP rather than trusting these fields (see step 7).

**6. Upload** `rhythm_upload_manifest.json` together with the ZIP files, through the **Automated Upload** page (`/automated-upload/`, requires a logged-in account). It validates the manifest against the live server schema, then drives the same resumable, checksum-verified chunked-upload API the API client uses — see [REST API](#rest-api) below.

**7. What the server does with each item:**
- Verifies the ZIP's SHA-256 checksum, if the manifest supplied one, before touching the file
- Resolves `protocol_id` against the app's registered protocols, and rejects the item if it doesn't exist or its site doesn't match `site_code` (case-insensitively)
- Re-validates GDPR anonymization against `GDPR-strict.json`
- Independently extracts the DICOM `StudyInstanceUID` from the ZIP (it does not trust the manifest's optional `dicom_uid` field)
- Checks for duplicate studies
- Assigns the final Repository Study ID: `RHY-{SITE}-{INDICATION}-{CONTRAST}-{GROUP}-{SEQNO}`, e.g. `RHY-S001-HEADTRAUMA-NC-PH-G4-000123`
- Pushes validated images to Orthanc

Assignment happens **asynchronously** — there is no synchronous "here's your Repository Study ID" response at upload time. Track progress on the **My Uploads** page (`/my-uploads/`) or by polling the job status URL returned when the upload completes.

**Before uploading, confirm:**
- [ ] Every studyset is anonymized
- [ ] Each ZIP contains one studyset only
- [ ] No ZIP contains direct patient identifiers
- [ ] The Excel template has one row per ZIP, and each `filename` matches a ZIP exactly
- [ ] Each `protocol_id` was copied from the correct row on the Protocol Records page, and its site matches `site_code`
- [ ] The manifest generated successfully with no reported errors
- [ ] The ZIP files and the JSON manifest are uploaded together

**Manifest generator troubleshooting**

| Problem | Fix |
|---|---|
| ZIP file not found | The Excel `filename` must exactly match a file in the selected ZIP folder |
| File is not a valid ZIP | Re-create it with standard ZIP compression |
| No readable DICOM files found | Check the ZIP holds DICOM files, not a nested ZIP or only screenshots/reports |
| Multiple `StudyInstanceUID` values found | The ZIP has more than one study — split it, one ZIP per studyset |
| `protocol_id does not match a registered protocol` | Copy the ID again from the Protocol Records page — it must be an exact UUID for a protocol that already exists |
| `site_code does not match the submitting site of protocol` | The `protocol_id` belongs to a different site than `site_code` in this row |
| Excel file cannot be read | Python: `pip install openpyxl`. Executable: close the Excel file before running the tool |
| DICOM UID extraction fails | Python: `pip install pydicom`. Also confirm the ZIP contains valid DICOM files |

### v1: Single-Study Archive (legacy)

A single `.tar`/`.tar.gz` archive with an inline manifest, submitted directly to the REST API:

```
upload.tar
├── manifest.json       ← required at archive root
└── images/
    ├── img_001.dcm
    ├── img_002.dcm
    └── ...
```

```json
{
  "manifest_version": "1.0",
  "upload_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2024-02-26T10:00:00Z",
  "source_institution": "Hospital A",
  "patient": {
    "pseudo_id": "PAT12345678",
    "sex": "M",
    "age_at_acquisition": 45,
    "cohort_tag": "COHORT_2024"
  },
  "study": {
    "study_uid": "1.2.840.113619.2.xxx",
    "acquisition_date": "2024-01-15",
    "clinical_indication": "Chest screening",
    "pathology_labels": ["nodule"],
    "contrast_used": false
  },
  "images": [
    {
      "filename": "images/img_001.dcm",
      "checksum_sha256": "a1b2c3d4...",
      "series_uid": "1.2.840.113619.2.xxx.1",
      "body_part": "CHEST"
    }
  ]
}
```

**Required image fields:** `filename`, `checksum_sha256`, `series_uid`, `body_part`
**`pseudo_id` format:** 8–64 characters, alphanumeric + hyphens + underscores
**`body_part` values:** `CHEST`, `ABDOMEN`, `PELVIS`, `HEAD`, `NECK`, `SPINE`, `EXTREMITY`, `WHOLE_BODY`, `OTHER`

Submitted via `POST /api/v1/uploads/` — see [REST API](#rest-api).

### GDPR Anonymization Requirements (both pipelines)

DICOM files **must be anonymized before upload**. The platform validates but does not transform. Files that fail validation are rejected with detailed error codes; the remaining files in the batch continue processing.

Required state for each file:
- `PatientName`, `PatientBirthDate`, `PatientAge`, `InstitutionName`, and other PHI tags must be absent or empty
- `PatientID` must be set to the `pseudo_id` from the manifest (the platform writes an organ-specific derivative, e.g. `PAT12345678_CHT01`, before validating)
- `StudyInstanceUID` and `SeriesInstanceUID` must be regenerated (not original scanner UIDs)
- Private (vendor) tags are **allowed**: `GDPR-strict.json` sets `KeepPrivateTags: true`, matching the partners' anonymization tool, because vendor private tags often carry dose and reconstruction parameters WP5 needs. Partners remain responsible for not placing identifiers in them. Do not use private or free-text tags to carry retention consent; use the manifest's `retain_after_project` field instead (see [Retention Consent and End-of-Project Deletion](#retention-consent-and-end-of-project-deletion)).
- No overlay, curve, or audio data
- No temporal tags (`StudyDate`, `SeriesDate`, etc.)

See [GDPR-strict.json](GDPR-strict.json) for the full rule set.

---

## REST API

All API endpoints require `Authorization: Bearer <token>` (or `Authorization: Token <token>`), **or** an authenticated browser session — the GUI pages use the latter.

### Authentication

```bash
POST /api/v1/auth/login/
Content-Type: application/json

{"username": "alice", "password": "secret"}
# → {"token": "abc123...", "user_id": 1, "username": "alice", ...}
```

### v1: Standard Upload (up to 2 GB)

```bash
# Submit archive
curl -X POST http://localhost:8003/api/v1/uploads/ \
  -H "Authorization: Bearer <token>" \
  -F "tar_file=@upload.tar"
# → 202 {"job_id": "uuid", "status": "PENDING", "poll_url": "/api/v1/uploads/uuid/"}

# Poll for completion
curl http://localhost:8003/api/v1/uploads/<job_id>/ \
  -H "Authorization: Bearer <token>"
# → {"id": "uuid", "status": "COMPLETE", "orthanc_study_ids": [...], ...}
```

**Job statuses:** `PENDING` → `PROCESSING` → `COMPLETE` / `PARTIAL` / `FAILED`

`PARTIAL` means some images passed validation and were pushed to Orthanc; others failed. Check `error_report` for per-image details.

### Validate a Manifest Before Upload (v1 or v2, auto-detected)

```bash
POST /api/v1/uploads/validate-manifest/
Content-Type: application/json
Authorization: Bearer <token>

{"manifest": { ...manifest object... }}
# → {"valid": true, "schema_version": "v1"|"v2", "errors": []}
# or {"valid": false, "schema_version": "v2", "errors": [{"field": "$.items[0].protocol_id", "code": "required", "message": "..."}]}
```

### Chunked Upload (v1 large files, and all v2 batch items)

```bash
# 1. Initialize session — pass `batch` / `manifest_item` for a v2 batch item
curl -X POST http://localhost:8003/api/v1/uploads/chunked/init/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"filename": "archive.tar.gz", "total_size": 10737418240, "chunk_size": 10485760}'
# → {"session_id": "uuid", "total_chunks": 1024, "expires_at": "..."}

# 2. Upload chunks (repeat for each chunk)
curl -X POST "http://localhost:8003/api/v1/uploads/chunked/<session_id>/chunk/?chunk_number=0&chunk_hash=<sha256>" \
  -H "Authorization: Bearer <token>" \
  --data-binary @chunk_0.bin
# → {"verification_status": "VERIFIED", "needs_reupload": false, "progress_percent": 1, ...}

# 3. Check resume status (if interrupted)
curl http://localhost:8003/api/v1/uploads/chunked/<session_id>/status/ \
  -H "Authorization: Bearer <token>"
# → {"needs_reupload": [5, 25], "verified_chunks": 98, ...}

# 4. Complete
curl -X POST http://localhost:8003/api/v1/uploads/chunked/<session_id>/complete/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"file_hash": "<sha256_of_complete_file>"}'
# → {"job_id": "uuid", "job_status_url": "/api/v1/uploads/uuid/", ...}
```

Each chunk is automatically verified with SHA256 + CRC32 on receipt. The response tells the client immediately whether the chunk needs to be re-uploaded. A `manifest_item` posted at init time is schema-validated immediately — a caller that skips the client-side "Validate Manifest" step still can't queue a v2 item with missing required fields.

### Chunked Upload Endpoint Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/uploads/chunked/init/` | Create session (accepts `batch` / `manifest_item` for v2) |
| POST | `/api/v1/uploads/chunked/{id}/chunk/` | Upload one chunk (auto-verifies) |
| GET | `/api/v1/uploads/chunked/{id}/progress/` | Overall progress |
| GET | `/api/v1/uploads/chunked/{id}/status/` | Per-chunk verification status (resume info) |
| POST | `/api/v1/uploads/chunked/{id}/verify/` | On-demand corruption check |
| POST | `/api/v1/uploads/chunked/{id}/complete/` | Assemble + create UploadJob |
| DELETE | `/api/v1/uploads/chunked/{id}/` | Cancel and clean up |

### List Studies

```bash
GET /api/v1/studies/?pseudo_id=PAT12345678&acquisition_date_from=2024-01-01&cohort_tag=COHORT_2024
# → paginated list of StudyMapping objects with QIDO-RS / WADO-RS URLs
```

---

## Standalone Upload Client

[chunked_upload_client.py](chunked_upload_client.py) is a self-contained Python script for large v1 uploads from the command line:

```bash
python chunked_upload_client.py \
  --url http://localhost:8003 \
  --token <bearer_token> \
  --file large_archive.tar.gz
```

---

## Development

### Running Tests

```bash
make test           # Django unit tests against a throwaway PostgreSQL (test-db)
make test-coverage  # same, with a coverage report
make test-e2e       # Playwright E2E tests (requires running stack)
make test-all       # unit + E2E
```

`make test` never touches the production database or the live `web` container. It starts the `test-db` service (docker compose profile `test`: PostgreSQL in RAM, no published ports), runs the suite in a one-off container with [test_settings_postgres.py](ct_upload_platform/ct_upload_platform/test_settings_postgres.py), then removes `test-db`. Those settings refuse to start if pointed at the production database host. Migrations are skipped and tables are created straight from the models.

For a quick local run without Docker, `python manage.py test uploads --settings=ct_upload_platform.test_settings` uses in-memory SQLite. Both test settings use Celery's in-memory broker, so no test can enqueue tasks on the real Redis/worker. (Before this was fixed, local test runs put fake `process_upload_job` tasks on the production queue, because `.env`'s `REDIS_URL` points at it.) Orthanc is mocked. A few GDPR validator tests expect the rules file at `/app/GDPR-strict.json` and only pass inside the container.

#### Playwright E2E Tests

The E2E suite (`tests/e2e/`) tests the full browser UI against the real running application. It requires:

1. **Node.js** and the Playwright browsers installed:
   ```bash
   cd ct_upload_platform
   npm install
   npx playwright install chromium
   ```

2. **A running Docker stack** (`make up && make migrate`) and a test user:
   ```bash
   docker compose exec web python manage.py shell -c "
   from django.contrib.auth import get_user_model
   U = get_user_model()
   U.objects.filter(username='testqa').delete()
   U.objects.create_superuser('testqa', 'testqa@test.com', 'TestQA123!')
   "
   ```

3. **Run against the Docker web container** (mapped to port 8003 by default):
   ```bash
   cd ct_upload_platform
   BASE_URL=http://localhost:8003 TEST_USERNAME=testqa TEST_PASSWORD="TestQA123!" \
     npx playwright test --project=chromium
   ```

   Run with a visible browser for debugging:
   ```bash
   BASE_URL=http://localhost:8003 TEST_USERNAME=testqa TEST_PASSWORD="TestQA123!" \
     npx playwright test --project=chromium --headed
   ```

**E2E test files and coverage:**

| File | Pages covered |
|------|---------------|
| `signup.spec.ts` | `/signup/` — form validation, registration, error handling |
| `upload.spec.ts` | `/` — file upload, progress, status polling |
| `examination.spec.ts` | `/examinations/entry/`, `/examinations/` — CRUD, phases table, cascade dropdowns, delete confirmation |
| `protocol_gui.spec.ts` | `/protocols/gui/` — 3-step wizard, tabs, save/duplicate/clear |
| `protocol_records.spec.ts` | `/protocols/records/` — filters, table headers, type badges, delete confirmation, CRUD flow |
| `protocols.spec.ts` | `/protocols/<type>/`, `/scanners/` — list and form pages |

### Linting

```bash
make lint                          # flake8 inside Docker
ruff check --select E,F,W,I .      # locally with ruff
```

### Useful Make Targets

```bash
make up             # start all services
make down           # stop services
make logs           # follow all logs
make shell          # Django shell inside web container
make bash           # bash inside web container
make migrate        # run migrations
make status         # health-check all services
make create-token   # interactive: create upload token for a user
make db-backup      # dump PostgreSQL to backups/
make restart        # restart all containers
```

### Adding a New User

```bash
docker compose exec web python manage.py create_user \
  --username john.doe \
  --email john.doe@example.com \
  --first-name John \
  --last-name Doe
# Generates a random password and prints (or emails) credentials.

docker compose exec web python manage.py create_upload_token john.doe
```

---

## Retention Consent and End-of-Project Deletion

The Data Transfer Agreement requires that studies a patient did not authorise for retention are deleted when the Grant Agreement ends. Every `CTExamination` carries a `retention_consent` flag:

| Value | Shown as | At project end |
|---|---|---|
| `RETAIN` | Retain | kept |
| `DELETE` | Delete at end | deleted |
| *(blank)* | Not declared | **deleted**: only explicit authorisation is kept |

**Declaring it**
- *Automated upload:* the v2 manifest item field `retain_after_project` (`true` / `false` / `null`). The manifest tool (v4.1) fills it from the optional `retain_after_project` template column (`yes` / `no` / empty). The Automated Upload page shows each item's value and warns about undeclared ones before upload.
- *Manual Exam Entry:* the "Retention After the Project" choice.
- *Afterwards:* the Retention column on the Examinations page, editable by colleagues of the same institution. Every change is written to the `AuditLog` (`RETENTION_SET`) with who, when, and old/new value. The page shows counts and a filter for each state. Admins see the same column in the File Manager.

**Deleting at the end of the project**
```bash
docker compose exec web python manage.py purge_non_retained_examinations            # dry run (default)
docker compose exec web python manage.py purge_non_retained_examinations --site S001 # dry run, one site
docker compose exec web python manage.py purge_non_retained_examinations --execute --expected-count N --actor <name>
```
- The dry run lists every study to be deleted, per site. `--execute` refuses to run unless `--expected-count` equals the number the dry run reported.
- For each study it deletes the Orthanc study (all series/images), the `StudyMapping`/`Image`/`Annotation` rows and the then-unused `Patient`, the `CTExamination`, its `UploadJob` (unless shared), the uploaded archive, the extracted copy, any Manual Entry study-set file, and the chunked-upload session row. It only ever deletes files inside `MEDIA_ROOT`, `RAW_DATA_DIR` and `PROCESSED_DATA_DIR`.
- If Orthanc refuses a deletion, that study's database rows are left in place and it is reported as `FAILED`, so a re-run retries it.
- Each deleted study gets a `STUDY_PURGED` `AuditLog` entry (not attached to the deleted job, so it survives), and a CSV per site is written to `backups/purge_reports/<timestamp>/` to send to the partners.
- Backups still hold deleted studies until they age out: database dumps after 30 days, Orthanc archives after 7 (see below). Take that into account when confirming deletion to partners.

---

## Orthanc Storage and Backups

**Image store location.** Orthanc's data (images and index) lives in the `orthanc_data` Docker volume by default. Setting `ORTHANC_DATA_PATH` in `.env` moves it to a host directory, intended for the dedicated **`rhythm`** HDD array (e.g. `/mnt/rhythm/orthanc`). To migrate:
```bash
docker compose stop orthanc worker web
sudo rsync -a /var/lib/docker/volumes/ct_upload_platform_orthanc_data/_data/ /mnt/rhythm/orthanc/
echo 'ORTHANC_DATA_PATH=/mnt/rhythm/orthanc' >> .env
docker compose up -d orthanc worker web
```
Then compare a study count in Orthanc Explorer before and after. Keep the old volume until verified.

**Backups.** `scripts/backup_orthanc.sh` archives the Orthanc data through a throwaway read-only container (the running Orthanc is not stopped), verifies the gzip archive, and prunes archives older than `RETENTION_DAYS` (default 7, since images are large). It follows `ORTHANC_DATA_PATH` automatically and refuses to start if free disk is less than twice the data size. Both backup scripts accept `BACKUP_DIR`. Point them at the **`rhythm-backup`** HDD array, a different physical disk from the Orthanc data:
```bash
30 2 * * * BACKUP_DIR=/mnt/rhythm-backup/orthanc /path/to/rhythm-repo/ct_upload_platform/scripts/backup_orthanc.sh
55 23 * * * BACKUP_DIR=/mnt/rhythm-backup/db /path/to/rhythm-repo/ct_upload_platform/scripts/backup_db.sh
```
Restore: stop Orthanc, extract the archive into the (emptied) data directory or volume, start Orthanc. The archive contains Orthanc's `index` database and the storage folders.

---

## Database Backups

`scripts/backup_db.sh` dumps the live PostgreSQL database via `pg_dump`, timestamped, with a log at `backups/backup.log`. It fails loudly (and removes the partial file) rather than silently writing a broken dump, and prunes dumps older than 30 days (`RETENTION_DAYS` env var to override).

Scheduled via the host crontab, once daily at end of day:
```bash
55 23 * * * /path/to/rhythm-repo/ct_upload_platform/scripts/backup_db.sh
```
(`crontab -e` to view/edit; not part of this repo since it's host config, not a project file.) Run it manually with `./scripts/backup_db.sh`, or `make db-backup` for a one-off dump without the log/retention logic.

**Restoring** a dump — the dump is a plain `pg_dump` of an already-populated database, so load it into an *empty* database, not over a live one with existing rows (you'll get conflicts):
```bash
docker compose exec -T db psql -U postgres -c "CREATE DATABASE ct_upload_platform_restored;"
docker compose exec -T db psql -U postgres -d ct_upload_platform_restored < backups/db_backup_YYYYMMDD_HHMMSS.sql
```
Verify it (e.g. compare row counts against the live DB — `SELECT COUNT(*) FROM uploads_ctexamination;` etc.), then either point `DB_NAME` at the restored database, or drop the old one and rename the restored one to `ct_upload_platform`.

Rehearsed 2026-08-31: a fresh dump was restored into a throwaway database and verified with matching table/row counts (33 tables; `uploads_ctexamination`, `uploads_uploadjob`, `uploads_studymapping`, `auth_user` row counts all identical to the live DB) before being dropped. The dump format and this restore procedure are confirmed working end-to-end.

---

## Configuration

Copy `.env.example` to `.env` and fill in these values. **Never leave a credential at a guessable default** — `docker-compose.yml` deliberately fails fast at startup if `DB_PASSWORD` or `ORTHANC_PASSWORD` is unset, and Django refuses to start with `DEBUG=False` if `SECRET_KEY` is still the placeholder default.

```bash
# Django
SECRET_KEY=<50+ random chars>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,localhost

# Database
DB_NAME=ct_upload_platform
DB_USER=postgres
DB_PASSWORD=<strong password>
DB_HOST=db
DB_PORT=5432

# Redis
REDIS_URL=redis://redis:6379/0

# Orthanc — the RegisteredUsers credential itself lives in orthanc.secrets.json
# (gitignored; copy orthanc.secrets.json.example and set a real password)
ORTHANC_BASE_URL=http://orthanc:8042
ORTHANC_USERNAME=orthanc
ORTHANC_PASSWORD=<strong password, matching orthanc.secrets.json>

# Upload limits
MAX_UPLOAD_SIZE_MB=2048
MAX_IMAGES_PER_UPLOAD=10000

# GDPR
GDPR_STRICT_CONFIG_PATH=/app/../GDPR-strict.json
GDPR_PIXEL_SCAN_ENABLED=False

# Access control (optional)
IP_WHITELIST=192.168.1.0/24,10.0.0.0/8

# Email (for create_user command)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your@email.com
EMAIL_HOST_PASSWORD=<app password>
```

---

## Production Checklist

- [ ] `DEBUG=False`, `SECRET_KEY` is long and random
- [ ] `ALLOWED_HOSTS` set to specific domain(s), never `*`
- [ ] All credentials loaded from environment / `orthanc.secrets.json`, never hardcoded
- [ ] HTTPS enforced (`SECURE_SSL_REDIRECT=True`, HSTS headers) — see `Caddyfile`
- [ ] Orthanc and PostgreSQL not exposed to the internet (bound to `127.0.0.1` in `docker-compose.yml`)
- [ ] Redis not exposed to the internet
- [ ] `IP_WHITELIST` configured if needed
- [ ] Audit logging monitored
- [x] Database backups: `scripts/backup_db.sh` runs daily via cron (30-day retention) — see [Database Backups](#database-backups)
- [ ] Orthanc image backups: `scripts/backup_orthanc.sh` scheduled nightly via cron — see [Orthanc Storage and Backups](#orthanc-storage-and-backups)
- [ ] Orthanc data on the `rhythm` HDD array and backups on the `rhythm-backup` array (`ORTHANC_DATA_PATH`, `BACKUP_DIR`)
- [x] Backup restore rehearsed 2026-08-31 (restored into a throwaway DB, row counts verified, dropped) — see [Database Backups](#database-backups)
- [ ] Backups encrypted at rest / shipped off-host (currently plain `.sql` files on the same disk as the live DB)
- [ ] Dependency scanning in CI/CD (`pip-audit` or `safety`)
- [ ] Secret scanning (e.g. GitGuardian) enabled on the repo; `.gitguardian.yaml` allowlists known test-only fixtures

---

## Project Structure

```
rhythm-repo/
├── README.md                 # This file
├── CLAUDE.md                 # Developer notes and codebase guide
├── GDPR-strict.json          # DICOM anonymization rule set
├── chunked_upload_client.py  # Standalone upload client
├── design_document.md        # System design spec
├── manifest.json             # Example v1 manifest
├── create_rhythm_service_manifest_gui_with_uid/  # v2 manifest generator tool (partner-facing)
│   ├── README.md                                             # Usage instructions
│   ├── create_rhythm_server_assigned_manifest_gui_with_uid.py
│   ├── RHYTHM_manifest_tool.exe
│   ├── rhythm_server_assigned_metadata_template.xlsx
│   ├── rhythm_upload_manifest.json                           # Example output
│   └── rhythm_automated_upload_instructions_for_tool.html    # Standalone HTML instructions
└── ct_upload_platform/       # Django project root
    ├── manage.py
    ├── docker-compose.yml
    ├── Makefile
    ├── requirements.txt
    ├── Dockerfile
    ├── .env.example
    ├── orthanc.json                    # Orthanc config (no credentials)
    ├── orthanc.secrets.json.example    # Template for the gitignored real credential
    ├── package.json           # Node deps for Playwright
    ├── tsconfig.json          # TypeScript config for E2E tests
    ├── playwright.config.ts   # Playwright configuration
    ├── ct_upload_platform/   # Django settings package
    │   ├── settings.py
    │   ├── test_settings.py
    │   ├── celery.py
    │   ├── middleware.py
    │   └── urls.py
    ├── uploads/              # Main Django app
    │   ├── models.py
    │   ├── views.py
    │   ├── tasks.py                  # process_upload_job (v1) / process_v2_batch_item (v2)
    │   ├── serializers.py
    │   ├── auth.py
    │   ├── gdpr_validator.py
    │   ├── gdpr_anonymizer.py
    │   ├── orthanc_client.py
    │   ├── chunk_manager.py
    │   ├── chunked_upload_views.py
    │   ├── file_manager.py
    │   ├── pseudo_id_validator.py
    │   ├── manifest_schema.py        # v1 + v2 manifest JSON Schemas
    │   ├── repository_study_id.py    # RHY-{SITE}-{INDICATION}-{CONTRAST}-{GROUP}-{SEQ} generator
    │   ├── migrations/
    │   └── tests/            # Django unit tests
    └── tests/e2e/            # Playwright E2E tests
        ├── fixtures.ts        # Shared helpers and page objects
        ├── signup.spec.ts
        ├── upload.spec.ts
        ├── examination.spec.ts
        ├── protocol_gui.spec.ts
        ├── protocol_records.spec.ts
        ├── protocols.spec.ts
        └── README.md
```
