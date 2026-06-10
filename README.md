# Eutempe — CT Medical Image Upload Platform

A Django-based ingestion pipeline for pre-anonymized DICOM CT images. Research partners submit `.tar` archives, the platform validates GDPR anonymization compliance, and stores accepted images in an Orthanc DICOM server.

**PHI boundary:** The Django database never stores patient names, dates of birth, MRNs, or any identifying information. Only pseudo-identifiers and audit records are stored.

---

## Quick Start

```bash
cd ct_upload_platform
cp .env.example .env          # fill in secrets (see Configuration below)
make build                    # build Docker images
make up                       # start web, worker, db, redis, orthanc
make migrate                  # run Django migrations

# Create a superuser and generate an upload token
docker-compose exec -it web python manage.py createsuperuser
docker-compose exec web python manage.py create_upload_token <username>
```

| Service | URL |
|---------|-----|
| Web UI | http://localhost:8000 |
| Django Admin | http://localhost:8000/admin |
| Orthanc | http://localhost:8042 |

---

## Requirements

- Docker + Docker Compose
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

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design including data flow, module map, database schema, and security model.

---

## Uploading Images

### Archive Format

Every upload must be a `.tar` or `.tar.gz` archive with this layout:

```
upload.tar
├── manifest.json       ← required at archive root
└── images/
    ├── img_001.dcm
    ├── img_002.dcm
    └── ...
```

### manifest.json Schema

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

### GDPR Anonymization Requirements

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

All API endpoints require `Authorization: Bearer <token>` (or `Authorization: Token <token>`).

### Authentication

```bash
POST /api/v1/auth/login/
Content-Type: application/json

{"username": "alice", "password": "secret"}
# → {"token": "abc123...", "user_id": 1, "username": "alice", ...}
```

### Standard Upload (up to 2 GB)

```bash
# Submit archive
curl -X POST http://localhost:8000/api/v1/uploads/ \
  -H "Authorization: Bearer <token>" \
  -F "tar_file=@upload.tar"
# → 202 {"job_id": "uuid", "status": "PENDING", "poll_url": "/api/v1/uploads/uuid/"}

# Poll for completion
curl http://localhost:8000/api/v1/uploads/<job_id>/ \
  -H "Authorization: Bearer <token>"
# → {"id": "uuid", "status": "COMPLETE", "orthanc_study_ids": [...], ...}
```

**Job statuses:** `PENDING` → `PROCESSING` → `COMPLETE` / `PARTIAL` / `FAILED`

`PARTIAL` means some images passed validation and were pushed to Orthanc; others failed. Check `error_report` for per-image details.

### Validate Manifest Before Upload

```bash
POST /api/v1/uploads/validate-manifest/
Content-Type: application/json
Authorization: Bearer <token>

{"manifest": { ...manifest object... }}
# → {"valid": true, "errors": []}
# or {"valid": false, "errors": [{"field": "$.patient.pseudo_id", "code": "pattern", "message": "..."}]}
```

### Chunked Upload (large files)

```bash
# 1. Initialize session
curl -X POST http://localhost:8000/api/v1/uploads/chunked/init/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"filename": "archive.tar.gz", "total_size": 10737418240, "chunk_size": 10485760}'
# → {"session_id": "uuid", "total_chunks": 1024, "expires_at": "..."}

# 2. Upload chunks (repeat for each chunk)
curl -X POST "http://localhost:8000/api/v1/uploads/chunked/<session_id>/chunk/?chunk_number=0&chunk_hash=<sha256>" \
  -H "Authorization: Bearer <token>" \
  --data-binary @chunk_0.bin
# → {"verification_status": "VERIFIED", "needs_reupload": false, "progress_percent": 1, ...}

# 3. Check resume status (if interrupted)
curl http://localhost:8000/api/v1/uploads/chunked/<session_id>/status/ \
  -H "Authorization: Bearer <token>"
# → {"needs_reupload": [5, 25], "verified_chunks": 98, ...}

# 4. Complete
curl -X POST http://localhost:8000/api/v1/uploads/chunked/<session_id>/complete/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"file_hash": "<sha256_of_complete_file>"}'
# → {"job_id": "uuid", "job_status_url": "/api/v1/uploads/uuid/", ...}
```

Each chunk is automatically verified with SHA256 + CRC32 on receipt. The response tells the client immediately whether the chunk needs to be re-uploaded.

### Chunked Upload Endpoint Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/uploads/chunked/init/` | Create session |
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

[chunked_upload_client.py](chunked_upload_client.py) is a self-contained Python script for large uploads from the command line:

```bash
python chunked_upload_client.py \
  --url http://localhost:8000 \
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
docker-compose exec web python manage.py create_user \
  --username john.doe \
  --email john.doe@example.com \
  --first-name John \
  --last-name Doe
# Generates a random password and prints (or emails) credentials.

docker-compose exec web python manage.py create_upload_token john.doe
```

---

## Configuration

Copy `.env.example` to `.env` and fill in these values:

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

# Orthanc
ORTHANC_BASE_URL=http://orthanc:8042
ORTHANC_USERNAME=orthanc
ORTHANC_PASSWORD=<strong password>

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
- [ ] All credentials loaded from environment, not hardcoded
- [ ] HTTPS enforced (`SECURE_SSL_REDIRECT=True`, HSTS headers)
- [ ] Orthanc and PostgreSQL not exposed to the internet
- [ ] Redis not exposed to the internet
- [ ] `IP_WHITELIST` configured if needed
- [ ] Audit logging monitored
- [ ] Database backups tested and encrypted
- [ ] Dependency scanning in CI/CD (`pip-audit` or `safety`)

---

## Project Structure

```
eutempe-repo/
├── README.md                 # This file
├── CLAUDE.md                 # Developer notes and codebase guide
├── GDPR-strict.json          # DICOM anonymization rule set
├── chunked_upload_client.py  # Standalone upload client
├── design_document.md        # System design spec
├── manifest.json             # Example manifest
└── ct_upload_platform/       # Django project root
    ├── manage.py
    ├── docker-compose.yml
    ├── Makefile
    ├── requirements.txt
    ├── Dockerfile
    ├── .env.example
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
    │   ├── tasks.py
    │   ├── serializers.py
    │   ├── auth.py
    │   ├── gdpr_validator.py
    │   ├── gdpr_anonymizer.py
    │   ├── orthanc_client.py
    │   ├── chunk_manager.py
    │   ├── chunked_upload_views.py
    │   ├── file_manager.py
    │   ├── pseudo_id_validator.py
    │   ├── manifest_schema.py
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
