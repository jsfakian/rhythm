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

**2. Get the manifest generator tool.** Partners prepare their upload package with a small companion tool (Python script + Windows `.exe`, same behavior either way), available at **[github.com/jsfakian/rhythm](https://github.com/jsfakian/rhythm)** along with the Excel metadata template. It does not anonymize DICOM files — it only reads already-anonymized ZIPs and builds the upload manifest.

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
| `site_code` | Coded submitting site, e.g. `S001` |
| `clinical_indication_code` | See table below |
| `anatomical_region` | e.g. `Head`, `Chest/HRCT`, `Abdomen` |
| `contrast_code` | `NC`, `CE`, or `MIX` |
| `patient_group_code` | See table below |
| `scanner_id` | Locally registered CT scanner ID, e.g. `CT01` |
| `protocol_name` | Name of the CT protocol used |
| `patient_weight_kg`, `patient_age_years` | Numeric |
| `ctdivol_mgy`, `dlp_mgy_cm` | Dose metrics |
| `image_quality` | e.g. `Acceptable` |

**Clinical indication codes**

| Code | Meaning |
|---|---|
| `HEADTRAUMA` | Head / Trauma |
| `MASTOID` | Mastoid bone / Inner ear |
| `CHESTCOMP` | Chest / Complicated infections |
| `CHESTFUNG` | Chest / Fungal infections |
| `HRCTILD` | Chest/HRCT — interstitial lung disease and related conditions |
| `ACUTEABD` | Abdomen / Acute abdomen |
| `LYMPHOMA` | Neck-Chest-Abdomen / Lymphoma |
| `CHESTABD` | Chest-Abdomen / Tumor staging and follow-up |

**Patient group codes**

| Code | Meaning | | Code | Meaning |
|---|---|---|---|---|
| `PH-G1`–`PH-G4` | Pediatric Head, Groups 1–4 | | `PB-G1`–`PB-G5` | Pediatric Body, Groups 1–5 |
| `YA-G6` | Young Adult | | | |

> ⚠️ These three coded fields are free-text strings in the manifest schema — the server does not reject an unrecognized code at upload time, so use the values above exactly as shown.

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
  "clinical_indication_code": "HEADTRAUMA",
  "contrast_code": "NC",
  "patient_group_code": "PH-G4",
  "image_quality": "Acceptable"
}
```

`dicom_uid`/`dicom` are informational only — the server independently re-extracts the `StudyInstanceUID` from the ZIP rather than trusting these fields (see step 7).

**6. Upload** `rhythm_upload_manifest.json` together with the ZIP files, through the **Automated Upload** page (`/automated-upload/`, requires a logged-in account). It validates the manifest against the live server schema, then drives the same resumable, checksum-verified chunked-upload API the API client uses — see [REST API](#rest-api) below.

**7. What the server does with each item:**
- Verifies the ZIP's SHA-256 checksum, if the manifest supplied one, before touching the file
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
- [ ] The manifest generated successfully with no reported errors
- [ ] The ZIP files and the JSON manifest are uploaded together

**Manifest generator troubleshooting**

| Problem | Fix |
|---|---|
| ZIP file not found | The Excel `filename` must exactly match a file in the selected ZIP folder |
| File is not a valid ZIP | Re-create it with standard ZIP compression |
| No readable DICOM files found | Check the ZIP holds DICOM files, not a nested ZIP or only screenshots/reports |
| Multiple `StudyInstanceUID` values found | The ZIP has more than one study — split it, one ZIP per studyset |
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
- No private tags (odd DICOM group numbers)
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
# or {"valid": false, "schema_version": "v2", "errors": [{"field": "$.items[0].clinical_indication_code", "code": "required", "message": "..."}]}
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
make test           # Django unit tests (fast, keeps test DB)
make test-coverage  # unit tests + coverage report
make test-e2e       # Playwright E2E tests (requires running stack)
make test-all       # unit + E2E
```

Unit tests use an in-memory SQLite database and mocked Celery / Orthanc. Settings are in [ct_upload_platform/test_settings.py](ct_upload_platform/ct_upload_platform/test_settings.py).

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
