# Eutempe — System Architecture

## 1. Overview

Eutempe is a Django-based ingestion pipeline for pre-anonymized DICOM CT images. Research institutions submit `.tar` archives of DICOM files, the platform validates GDPR anonymization compliance, and stores accepted images in an Orthanc DICOM server. Django functions as the validation and audit layer — it does not transform DICOM data and does not duplicate image storage.

**Core invariant:** No PHI (Protected Health Information) ever enters the Django database. The database stores only pseudo-identifiers and audit records.

---

## 2. Service Architecture

Five Docker services collaborate to form the system:

```
┌─────────────────────────────────────────────────────────────────┐
│                        External Network                          │
│                                                                 │
│   Client (research partner or web browser)                      │
│      │                                                          │
│      │  HTTP/HTTPS  POST /api/v1/uploads/                       │
│      ▼                                                          │
│ ┌──────────┐   ┌───────────────────────────────────────────┐   │
│ │  web     │   │  Django (Gunicorn, 4 workers)             │   │
│ │ :8000    │──▶│  REST API + Session UI                    │   │
│ └──────────┘   │  auth, size/format checks, job creation   │   │
│                └────────────────┬──────────────────────────┘   │
│                                 │ task.delay()                  │
│                                 ▼                               │
│                ┌───────────────────────────────────────────┐   │
│                │  worker (Celery, concurrency=2)            │   │
│                │  process_upload_job()                      │   │
│                │  ─ unpack tar                             │   │
│                │  ─ validate manifest                      │   │
│                │  ─ pseudo-ID generation + insertion       │   │
│                │  ─ GDPR anonymization validation          │   │
│                │  ─ STOW-RS push to Orthanc               │   │
│                └──────┬─────────────────┬───────────────────┘  │
│                       │                 │                       │
│              ┌────────▼──────┐  ┌───────▼────────┐            │
│              │  db            │  │  orthanc        │            │
│              │  PostgreSQL 15 │  │  :8042          │            │
│              │  audit records │  │  DICOM storage  │            │
│              │  pseudo-ID map │  │  DICOMweb API   │            │
│              └───────────────┘  └─────────────────┘            │
│                                                                 │
│              ┌───────────────┐                                  │
│              │  redis :6379  │  (Celery broker + result store)  │
│              └───────────────┘                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Service Responsibilities

| Service | Image | Role |
|---------|-------|------|
| `web` | Custom Dockerfile | Django + Gunicorn. Handles HTTP requests, runs migrations on startup. |
| `worker` | Same Dockerfile | Celery worker. Runs `process_upload_job` tasks asynchronously. |
| `db` | `postgres:15-alpine` | Stores audit records, pseudo-ID mappings, job state. No DICOM data. |
| `redis` | `redis:7-alpine` | Celery broker and result backend. |
| `orthanc` | `osimis/orthanc:latest` | Authoritative DICOM store. Accepts files via STOW-RS; serves via QIDO-RS/WADO-RS. |

---

## 3. Upload Processing Pipeline

### 3.1 Standard Upload (≤ 2 GB)

```
Client  →  POST /api/v1/uploads/  (multipart, tar_file field)
              │
              ▼
         UploadView.post()
           ├── magic-byte validation (tar / gzip)
           ├── file size check (MAX_UPLOAD_SIZE_MB)
           ├── save tar → raw_data/{uploader_id}/{uuid}.tar
           ├── UploadJob.create(status=PENDING)
           └── process_upload_job.delay(job_id)  →  returns 202 + job_id

Client  →  GET /api/v1/uploads/{job_id}/  (poll for completion)
```

### 3.2 Chunked Upload (up to 1 TB)

```
POST /api/v1/uploads/chunked/init/
  → ChunkedUpload session created (status: INITIATED)
  ← session_id, total_chunks, expires_at

Loop: POST /api/v1/uploads/chunked/{session_id}/chunk/?chunk_number=N&chunk_hash=SHA256
  → store chunk to raw_data/_chunks/{session_id}/chunk_NNNNNN
  → verify SHA256 + CRC32 immediately (auto-verification)
  ← verification_status, needs_reupload

POST /api/v1/uploads/chunked/{session_id}/complete/
  → assemble chunks → raw_data/{uploader_id}/{session_id}.tar
  → verify assembled file hash
  → UploadJob.create(status=PENDING)
  → process_upload_job.delay(job_id)
  ← job_id
```

### 3.3 Celery Task: `process_upload_job`

The task in [ct_upload_platform/uploads/tasks.py](ct_upload_platform/uploads/tasks.py) runs in the `worker` container. Steps in order:

```
1. Load UploadJob → set status=PROCESSING

2. Validate tar file exists at tar_temp_path

3. validate_tar_safety()
   ├── member count ≤ MAX_IMAGES_PER_UPLOAD
   ├── no path traversal ("..") or absolute paths
   ├── no symlinks
   └── total uncompressed size ≤ MAX_UPLOAD_SIZE_MB

4. Extract tar → processed_data/{job_id}/

5. Parse & validate manifest.json
   └── validate_manifest() → JSON Schema v1 + future-date check + duplicate filename check

6. PseudoIDUniquenessValidator.validate_manifest_pseudo_ids()
   └── reject if pseudo_id already maps to a different patient (collision)

7. GDPRAnonymizationPipeline.anonymize_and_insert_pseudo_ids()
   ├── generate organ-specific pseudo IDs per image
   │   format: {base_pseudo_id}_{ORGAN_ABBR}{index:02d}
   │   e.g. PAT12345678_CHT01
   └── write PatientID tag into each DICOM file (pydicom)

8. Per-image processing loop:
   ├── verify file exists
   ├── compute SHA256 → compare with manifest checksum_sha256
   ├── validate_gdpr_anonymization()
   │   ├── PHI tags absent (PatientName, BirthDate, Age, …)
   │   ├── PatientID == organ-specific pseudo_id
   │   ├── StudyInstanceUID / SeriesInstanceUID present and non-empty
   │   ├── no private tags (odd group numbers)
   │   ├── no overlay/curve/audio data
   │   └── no temporal tags (StudyDate, SeriesDate, etc.)
   ├── orthanc_client.push_dicom_file(bytes)  (STOW-RS)
   ├── save orthanc_study_id → StudyMapping
   └── create Annotation records if manifest has annotations

9. Determine final status:
   ├── all passed → COMPLETE
   ├── some passed → PARTIAL
   └── none passed → FAILED

10. Cleanup:
    ├── FAILED → delete processed_data/{job_id}/
    └── COMPLETE/PARTIAL → preserve for audit
```

Retries: the task retries up to 3 times on unexpected exceptions with exponential back-off (60 s, 120 s, 240 s).

---

## 4. Module Map

```
ct_upload_platform/
├── ct_upload_platform/          Django project package
│   ├── settings.py              All config (env-driven via django-environ)
│   ├── celery.py                Celery app + autodiscover
│   ├── middleware.py            IPWhitelistMiddleware (CIDR-based access control)
│   └── urls.py                  Mounts uploads.urls at /api/v1/
│
└── uploads/                     Main Django app
    ├── models.py                Patient, UploadJob, StudyMapping, Image,
    │                             Annotation, AuditLog, ChunkedUpload, UploadChunk
    ├── views.py                 UploadView, UploadJobDetailView, StudyListView,
    │                             StudyDetailView, LoginView, UploadIndexView,
    │                             UploadAdvancedView
    ├── chunked_upload_views.py  ChunkedUploadInitView, ChunkedUploadChunkView,
    │                             ChunkedUploadCompleteView, ChunkedUploadProgressView,
    │                             ChunkedUploadCancelView, ManifestValidationView,
    │                             ChunkVerificationView, UploadProgressView
    ├── tasks.py                 process_upload_job (Celery shared_task)
    ├── serializers.py           DRF serializers for all models
    ├── urls.py                  All URL patterns
    ├── auth.py                  BearerTokenAuthentication (Bearer + Token prefix)
    ├── gdpr_validator.py        GDPRAnonymizationValidator, validate_gdpr_anonymization()
    ├── gdpr_anonymizer.py       GDPRAnonymizationPipeline, PseudoIDGenerator,
    │                             DICOMAnonymizer
    ├── manifest_schema.py       MANIFEST_SCHEMA_V1 (JSON Schema), validate_manifest()
    ├── orthanc_client.py        OrthancClient (STOW-RS push, QIDO-RS query),
    │                             get_client() singleton
    ├── chunk_manager.py         store_chunk(), assemble_chunks(), verify_uploaded_chunks(),
    │                             cleanup_session(), cleanup_expired_uploads()
    ├── file_manager.py          get_raw_data_user_dir(), get_processed_data_job_dir()
    ├── pseudo_id_validator.py   PseudoIDUniquenessValidator, PseudoIDCollisionError
    └── management/commands/
        ├── create_upload_token.py
        └── create_user.py
```

---

## 5. Data Model

```
Patient (1) ──────────── (N) StudyMapping (N) ──── (1) UploadJob
   │                              │
   │ pseudo_id (UNIQUE)           │ pseudo_study_uid (UNIQUE)
   │ sex, age_at_first_acq        │ orthanc_study_id  ← maps to Orthanc
   │ cohort_tag                   │ acquisition_date
   │                              │ clinical_indication
   │                              │ pathology_labels (JSON array)
   │                              │ contrast_used / contrast_agent
   │                              │ source_institution
   │                              │
   │                    (N) Image │ (N) Annotation
   │                         filename            annotation_uid
   │                         orthanc_instance_id annotator_id
   │                         sop_instance_uid    type (SEGM/BB/LM/CLASS)
   │                                             label, annotation_data (JSON)
   │                                             annotation_file (FileField)
   │
UploadJob
   status: PENDING → PROCESSING → COMPLETE / PARTIAL / FAILED
   manifest_raw (JSON, full audit copy)
   error_report (JSON, per-image errors)
   anonymization_report (JSON, pseudo-ID insertion results)

ChunkedUpload ──── (N) UploadChunk
   status: INITIATED → IN_PROGRESS → COMPLETED / FAILED / CANCELLED
   total_size, total_chunks, uploaded_chunks, chunk_size
   temp_dir (path to chunk files)
   expires_at (auto-cleanup after 7 days)

   UploadChunk
     chunk_number (unique per session)
     chunk_hash (SHA256)
     chunk_crc32 (CRC32, hex)
     verification_status: PENDING / VERIFIED / CORRUPTED / NEEDS_REUPLOAD
     verification_error, verification_timestamp
```

### PHI Boundary

Django's database stores **only**:
- `pseudo_id` (opaque token, e.g. `PAT12345678`)
- Organ-specific derivative IDs (e.g. `PAT12345678_CHT01`)
- Non-identifying metadata (sex as a single char, age as integer, cohort tag)

Real patient names, dates of birth, MRNs, or any re-identifying DICOM tag are never written here.

---

## 6. GDPR Validation Rules

The file [GDPR-strict.json](GDPR-strict.json) defines the accepted state for each tag. `GDPRAnonymizationValidator` ([uploads/gdpr_validator.py](ct_upload_platform/uploads/gdpr_validator.py)) enforces these checks before any file is pushed to Orthanc:

| Check | Requirement |
|-------|-------------|
| PHI tags (PatientName, BirthDate, Age, Address, …) | Absent or empty |
| `PatientID` | Present and equal to the organ-specific pseudo_id |
| `StudyInstanceUID`, `SeriesInstanceUID` | Present and non-empty (regenerated UIDs) |
| `FrameOfReferenceUID` | Absent or non-empty (not a zero-length string) |
| Private tags (odd group numbers) | None allowed |
| Overlay data (0x60xx) | None allowed |
| Curve data (0x50xx) | None allowed |
| Audio / waveform data (0x54xx) | None allowed |
| Temporal tags (StudyDate, SeriesDate, ContentDate, …) | Absent or empty |

Validation is read-only (`stop_before_pixels=True`). Files that fail any check are recorded in `UploadJob.error_report` and skipped; the remaining files in the batch continue.

---

## 7. Pseudo-ID System

The pseudo-ID system has two levels:

**Base pseudo-ID** — assigned by the uploading institution, stored in `Patient.pseudo_id`.  
Format: `[A-Za-z0-9_-]{8,64}`, e.g. `PAT12345678`

**Organ-specific pseudo-ID** — derived per DICOM file just before GDPR validation.  
Format: `{base_pseudo_id}_{ORGAN_ABBR}{index:02d}`, e.g. `PAT12345678_CHT01`

| Body Part | Abbreviation |
|-----------|-------------|
| CHEST | CHT |
| ABDOMEN | ABD |
| PELVIS | PLS |
| HEAD | HED |
| NECK | NCK |
| SPINE | SPN |
| EXTREMITY | EXR |
| WHOLE_BODY | WHB |
| OTHER | OTH |

The `DICOMAnonymizer.set_pseudo_patient_id()` writes this ID into the DICOM `PatientID` tag in-place before validation runs. The GDPR validator then confirms the tag matches the expected value.

`PseudoIDUniquenessValidator` prevents collision: if a `pseudo_id` is already mapped to a different `Patient` record, the job fails immediately with a `PseudoIDCollisionError`.

---

## 8. REST API Surface

Base path: `/api/v1/`

### Authentication
| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `auth/login/` | None | Returns Bearer token |

### Standard Uploads
| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `uploads/` | Token | Submit tar. Returns 202 + job_id. |
| GET | `uploads/` | Token | List jobs (admin sees all; users see own). |
| GET | `uploads/{job_id}/` | Token | Job status + error report. |
| DELETE | `uploads/{job_id}/` | Admin | Cancel PENDING job. |
| POST | `uploads/validate-manifest/` | Token | Pre-validate manifest before upload. |

### Chunked Uploads
| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `uploads/chunked/init/` | Token | Create session. Returns session_id. |
| POST | `uploads/chunked/{id}/chunk/` | Token | Upload one chunk. Auto-verifies. |
| GET | `uploads/chunked/{id}/progress/` | Token | Upload progress. |
| GET | `uploads/chunked/{id}/status/` | Token | Per-chunk verification status (for resume). |
| POST | `uploads/chunked/{id}/verify/` | Token | On-demand chunk integrity check. |
| POST | `uploads/chunked/{id}/complete/` | Token | Assemble + create UploadJob. |
| DELETE | `uploads/chunked/{id}/` | Token | Cancel and clean up. |

### Studies
| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `studies/` | Token | List studies. Filters: pseudo_id, date range, cohort_tag. |
| GET | `studies/{pseudo_study_uid}/` | Token | Study detail + QIDO-RS / WADO-RS URLs. |

---

## 9. Authentication & Access Control

`BearerTokenAuthentication` ([uploads/auth.py](ct_upload_platform/uploads/auth.py)) extends DRF's `TokenAuthentication` to accept both:
- `Authorization: Bearer <token>`
- `Authorization: Token <token>`

Tokens are created with `python manage.py create_upload_token <username>` or via the login endpoint.

`IPWhitelistMiddleware` ([ct_upload_platform/middleware.py](ct_upload_platform/ct_upload_platform/middleware.py)) optionally restricts all requests to a CIDR whitelist configured in `IP_WHITELIST`. The login endpoint is always exempt.

---

## 10. Orthanc Integration

`OrthancClient` ([uploads/orthanc_client.py](ct_upload_platform/uploads/orthanc_client.py)) is a singleton (created on first use by `get_client()`).

**Ingest (STOW-RS):**
```
POST {ORTHANC_BASE_URL}/dicom-web/studies
Content-Type: multipart/related; type="application/dicom"
```
Returns `StudyInstanceUID`, `SeriesInstanceUID`, `SOPInstanceUID`. The study UID is persisted in `StudyMapping.orthanc_study_id`.

**Query (QIDO-RS):** `GET /dicom-web/studies/{orthanc_study_id}/series`  
**Retrieve (WADO-RS):** `GET /dicom-web/studies/{orthanc_study_id}`

The `StudyMappingSerializer` exposes pre-built `qido_url` and `wado_url` fields that point directly at Orthanc. Downstream consumers can hit Orthanc directly using those URLs.

**Orthanc is not exposed to end users.** Network segmentation should ensure only the `web` and `worker` containers can reach port 8042.

---

## 11. File Storage Layout

```
ct_upload_platform/
├── raw_data/
│   ├── {uploader_id}/
│   │   └── {uuid}.tar          ← uploaded archives (never auto-deleted)
│   └── _chunks/
│       └── {session_id}/
│           ├── chunk_000000    ← temporary, cleaned up on completion
│           └── chunk_000001
│
└── processed_data/
    └── {job_id}/               ← extracted tar contents
        ├── manifest.json
        └── images/
            └── *.dcm
            (preserved on COMPLETE/PARTIAL; deleted on FAILED)
```

---

## 12. Configuration Reference

All settings are injected via environment variables (`.env` file or Docker Compose `environment:`).

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | — | Django secret key. Required in production. |
| `DEBUG` | `False` | Never `True` in production. |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated. |
| `DB_*` | `localhost:5432/ct_upload_platform` | PostgreSQL connection. |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker + result backend. |
| `ORTHANC_BASE_URL` | `http://orthanc:8042` | Orthanc service address. |
| `ORTHANC_USERNAME` / `ORTHANC_PASSWORD` | `orthanc` | Orthanc HTTP auth. |
| `MAX_UPLOAD_SIZE_MB` | `2048` | Standard upload size limit. |
| `MAX_IMAGES_PER_UPLOAD` | `10000` | Tar member count limit. |
| `GDPR_STRICT_CONFIG_PATH` | `../GDPR-strict.json` | Path to anonymization rules. |
| `GDPR_PIXEL_SCAN_ENABLED` | `False` | Enable OCR pixel scanning. |
| `IP_WHITELIST` | `None` (all allowed) | CIDR comma list for IP restriction. |
| `RAW_DATA_DIR` | `{BASE_DIR}/raw_data` | Tar archive storage. |
| `PROCESSED_DATA_DIR` | `{BASE_DIR}/processed_data` | Extracted content storage. |
| `TOKEN_EXPIRY_DAYS` | `30` | Auth token lifetime. |

---

## 13. Key Design Decisions

**No PHI in Django DB.** The `pseudo_id → Orthanc StudyInstanceUID` mapping is the only re-identification key. It is protected by token auth and IP whitelisting.

**Validate, don't transform.** The platform does not scrub PHI from DICOM files. Uploading partners are contractually required to anonymize before submission. The platform validates compliance and rejects non-compliant files.

**Partial ingest.** A batch where some images pass and some fail results in `PARTIAL` status. This prevents one bad file from blocking an entire study.

**Celery retries.** `process_upload_job` retries up to 3 times on unexpected errors with exponential back-off. Transient Orthanc or network failures are handled automatically.

**Dual-hash chunk verification.** Chunks are verified with both SHA256 (cryptographic) and CRC32 (fast) on write. The upload response includes the verification result so clients can retry corrupted chunks without a separate API call.

**Fail-fast manifest validation.** Clients can POST a manifest to `/api/v1/uploads/validate-manifest/` before starting a potentially multi-hour upload. Errors are returned in under one second.

**Organ-specific pseudo-IDs.** Rather than one flat pseudo-ID per patient, the system generates `{base_id}_{ORGAN_ABBR}{index}` per image. This makes multi-organ studies traceable while keeping them de-identified.
