# CT Medical Image Upload Platform — System Design Document

**Version:** 2.0 | **Confidential**

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Architecture](#2-system-architecture)
3. [Chunked Upload Architecture](#3-chunked-upload-architecture)
4. [Upload Improvements: Early Validation & Corruption Detection](#4-upload-improvements-early-validation--corruption-detection)
5. [Expected Tar Structure](#5-expected-tar-structure)
6. [REST API](#6-rest-api)
7. [Database Schema](#7-database-schema)
8. [Validation Rules](#8-validation-rules)
9. [Orthanc Integration](#9-orthanc-integration)
10. [Security & Compliance](#10-security--compliance)
11. [Configuration Reference](#11-configuration-reference)
12. [Key Dependencies](#12-key-dependencies)

---

## 1. Overview

This document describes the design of a Django-based web application for batch uploading anonymized CT medical images. The system accepts `.tar` archives containing **pre-anonymized DICOM files** and a `manifest.json`, validates anonymization compliance against GDPR-strict rules, validates and ingests metadata, and pushes DICOM files into an **Orthanc DICOM server** as the authoritative storage backend. Django acts as an ingestion validation pipeline and audit layer — Orthanc owns all DICOM data after ingest.

| Field | Value |
|---|---|
| Project | CT Image Upload Platform |
| Stack | Django 5.x, PostgreSQL, Celery, Redis, Orthanc |
| Auth | API token + session (UI) |
| Primary format | Pre-anonymized DICOM (.dcm) inside .tar archive with manifest.json |
| DICOM storage | Orthanc (via STOW-RS REST API) |
| Anonymization | **Client-side** (upstream of this platform); platform **validates** compliance only |
| Compliance scope | GDPR-aligned validation; no PHI stored in Django DB; only anonymized DICOM accepted |
| Document version | 2.0 |

---

## 2. System Architecture

### 2.1 High-Level Components

The system is composed of five main layers:

- **Upload Layer** (Django REST API + UI) — Accepts tar file submissions via multipart HTTP or browser form. Performs initial size and format checks synchronously. Saves the raw tar to `raw_data/{uploader_id}/` directory for archival and audit purposes.
- **Validation & Ingestion Worker** (Celery) — Asynchronously unpacks the tar to `processed_data/{job_id}/`, validates the manifest, **validates DICOM anonymization compliance** against GDPR-strict.json standards, and pushes only compliant files to Orthanc via STOW-RS. Non-compliant files are rejected with detailed error codes. Extracted data is preserved for successful jobs and cleaned up for failed jobs.
- **DICOM Server** (Orthanc) — Authoritative store for all anonymized DICOM data. Manages the patient/study/series/instance hierarchy internally. Exposes DICOMweb endpoints (STOW-RS, WADO-RS, QIDO-RS) and its own REST API for downstream consumers.
- **Database** (PostgreSQL) — Stores upload job audit records, the `pseudo_id → Orthanc StudyInstanceUID` mapping, and annotation metadata. Does **not** duplicate DICOM image or series data.
- **Admin / Monitoring** (Django Admin + Celery Flower) — Operational dashboard for upload status, failure inspection, and reprocessing triggers.

### 2.2 Request Flow

```
Client (UI or REST)
        │
        │  POST /api/v1/uploads/  (multipart tar with pre-anonymized DICOM)
        ▼
  Django Upload View
  ├── Validate content-type, size
  ├── Save tar to raw_data/{uploader_id}/ directory
  ├── Create UploadJob (status: PENDING)
  └── Return 202 + job_id
        │
        │  Celery task: process_upload_job(job_id)
        ▼
  Celery Worker
  ├── Extract tar to processed_data/{job_id}/ (with safety checks)
  ├── Parse & validate manifest.json
  ├── For each DICOM file:
  │   ├── Verify file exists + checksum
  │   ├── Parse DICOM headers (pydicom)
  │   ├── VALIDATE against GDPR-strict.json rules
  │   │   ├── Verify all PHI tags are missing/empty/compliant
  │   │   ├── Verify no private tags present
  │   │   ├── Verify no overlay/curve/audio data
  │   │   ├── Verify UIDs are not in original format
  │   │   └── Fail image if non-compliant
  │   ├── If VALID: POST to Orthanc /dicom-web/studies (STOW-RS) AS-IS
  │   ├── Record orthanc_study_id in DB
  │   └── Create Annotation records if present
  ├── Set UploadJob status: COMPLETE / PARTIAL / FAILED
  ├── Preserve processed_data/{job_id}/ if successful; delete if failed
  └── Preserve raw_data/{uploader_id}/*.tar files (not deleted)
        │
        ▼
     Orthanc
     ├── Stores anonymized DICOM files (filesystem or its own storage plugin)
     ├── Manages Patient/Study/Series/Instance hierarchy
     └── Exposes QIDO-RS / WADO-RS / DICOMweb for downstream use
```

**Critical:** DICOM files must be **pre-anonymized by the uploading client** before submission. The platform only validates anonymization compliance. If any file fails validation, the entire image is rejected and an error is recorded; remaining files in the batch continue processing (partial ingest behavior).

The client polls `GET /api/v1/uploads/{job_id}/` for job status. Final DICOM data is retrieved directly from Orthanc by downstream consumers.

### 2.3 File Management & Storage

The system maintains a two-tier file storage model for data retention and audit:

**Raw Data Directory (`raw_data/{uploader_id}/`):**
- Stores original tar archives uploaded by users
- Organized by uploader ID for easy access and cleanup
- Tar files are preserved indefinitely for audit and compliance purposes
- Supports integrity validation and re-processing if needed

**Processed Data Directory (`processed_data/{job_id}/`):**
- Stores extracted tar contents (manifests, DICOM files) during and after processing
- Organized by job ID for isolation and easy tracking
- Preserved after successful validation for reference and troubleshooting
- Deleted if processing fails to reclaim disk space
- Enables post-processing analysis and auditing without re-extracting tar files

Both directories use restricted file permissions (`0600` / `rw-------`) and are stored outside the web-accessible document root for security.

---

## 3. Chunked Upload Architecture

### 3.1 Large File Support

For files **larger than 2GB** (up to **1TB**), the system provides a **resumable chunked upload API** that splits large files into manageable smaller chunks, uploads them independently, and assembles them on the server after all chunks are received.

**Key Features:**
- **Resumable Uploads**: If an upload is interrupted, the client can resume from the last successfully uploaded chunk without re-uploading completed chunks.
- **Integrity Verification**: Each chunk is validated with SHA256 hashing on both client and server sides.
- **Parallel Uploads**: Multiple chunks can be uploaded in parallel for faster transfer speeds on high-bandwidth connections.
- **Auto-cleanup**: Incomplete uploads expire automatically after 7 days to reclaim disk space.
- **Progress Tracking**: Real-time progress information available via dedicated endpoint.

### 3.2 Chunked Upload Flow

```
Client
  │
  │  POST /api/v1/uploads/chunked/init/
  │  ├── filename: "large_archive.tar.gz"
  │  ├── total_size: 68719476736  (64GB)
  │  ├── chunk_size: 10485760     (10MB, configurable)
  │  └── file_hash: "sha256_hex"  (optional, for verification)
  ├─────────────────────┐
  │                     ▼
  │              ChunkedUpload session created
  │              ├── status: INITIATED
  │              ├── total_chunks: 6872
  │              └── session_id: UUID
  │                     │
  │  Return: session_id, total_chunks, chunk_size, expires_at
  │
  │  Loop: For chunk_number = 0 to total_chunks-1
  │  POST /api/v1/uploads/chunked/{session_id}/chunk/
  │  ├── query params: chunk_number, chunk_hash
  │  ├── body: raw chunk data (binary)
  │  │
  │  ├─────────────────────┐
  │  │                     ▼
  │  │           Store chunk to disk
  │  │           Verify chunk hash
  │  │           Update uploaded_chunks counter
  │  │           Set status: IN_PROGRESS
  │  │                     │
  │  │  Return: progress%, uploaded_chunks count
  │  │
  │  └─────────────────────┘  [Repeat until all chunks uploaded]
  │
  │  GET /api/v1/uploads/chunked/{session_id}/progress/  [Optional - check status]
  │
  │  POST /api/v1/uploads/chunked/{session_id}/complete/
  │  ├── body: { "file_hash": "sha256_of_complete_file" }
  │  │
  │  ├─────────────────────┐
  │  │                     ▼
  │  │           Verify all chunks present
  │  │           Assemble chunks into final file
  │  │           Verify complete file hash
  │  │           Clean up chunk temp files
  │  │           Create UploadJob from assembled file
  │  │           Set ChunkedUpload status: COMPLETED
  │  │                     │
  │  │  Return: job_id, assembled_file_path, final_hash
  │  │
  │  └─────────────────────┘
  │
  └─────────────────────────────────────────────────────►  proceed to normal processing
           (job_id created, regular UploadJob processing continues)
```

### 3.3 Chunked Upload Data Model

**ChunkedUpload Session:**
- Tracks the entire chunked upload process
- Stores metadata: filename, total size, total chunks, uploaded chunks count
- Maintains status: INITIATED → IN_PROGRESS → COMPLETED / FAILED / CANCELLED
- Auto-expires after 7 days of inactivity
- Contains temp directory path where chunks are stored

**UploadChunk Records:**
- One record per chunk (chunk_number 0 to total_chunks-1)
- Stores: chunk number, chunk size, chunk hash, file path
- Tracks verification status
- Unique constraint on (chunked_upload_id, chunk_number)

### 3.4 Chunk Storage Location

Chunks are temporary files stored at:
```
raw_data/_chunks/{session_id}/
├── chunk_000000   (first 10MB)
├── chunk_000001   (second 10MB)
├── chunk_000002
└── ...
```

After successful completion:
- Chunks are cleaned up (deleted)
- Final assembled file is stored at: `raw_data/{uploader_id}/{session_uuid}.tar`
- Session directory remains but is empty (or can be removed)

### 3.5 Resumability Mechanism

If an upload is interrupted (network failure, client crash, etc.):

1. **Client detects interruption** and stores the session_id locally
2. **Client reconnects** and calls `GET /api/v1/uploads/chunked/{session_id}/progress/`
3. **Server responds** with current upload state: which chunks have been received
4. **Client resumes** by uploading only the missing chunks (skips already-uploaded chunks)
5. **After all chunks received**, `POST .../complete/` finalizes the upload

This allows resumption of very large uploads across network failures or client restarts.

### 3.6 Configuration for Chunked Uploads

| Setting | Default | Description |
|---|---|---|
| `CHUNKED_UPLOAD_ENABLED` | true | Enable/disable chunked upload feature |
| `CHUNKED_UPLOAD_MAX_SIZE_BYTES` | 1 TB | Maximum file size for chunked uploads |
| `CHUNKED_UPLOAD_DEFAULT_CHUNK_SIZE` | 10 MB | Default chunk size in bytes |
| `CHUNKED_UPLOAD_EXPIRATION_DAYS` | 7 | Auto-expire incomplete uploads after N days |
| `CHUNKED_UPLOAD_MAX_FILE_SIZE_MB` | 2048 | Do NOT apply to chunked uploads (different limit) |

---

## 4. Upload Improvements: Early Validation & Corruption Detection

### 4.1 Early Manifest Validation (Fail Fast)

**Problem**: Previously, manifest.json validation occurred AFTER uploading entire files (hours for large uploads), potentially wasting bandwidth and time on invalid data.

**Solution**: New `/api/v1/uploads/validate-manifest/` endpoint allows clients to validate manifest.json **before** starting file upload, discovering errors in <1 second.

**Benefits**:
- ✅ Fail fast without uploading data (saves 99% of time for invalid manifests)
- ✅ Instant feedback on validation errors with detailed field paths
- ✅ Validate multiple times before/during upload if needed
- ✅ Improves user experience and reduces support burden

**Implementation**:
- Endpoint: `POST /api/v1/uploads/validate-manifest/`
- Time to validate: <1 second
- Data uploaded: 0 bytes (detects errors before upload)
- Returns: `{valid: bool, errors: [...]}`
- Uses existing `validate_manifest()` function from manifest_schema.py

**Request/Response Example**:
```json
POST /api/v1/uploads/validate-manifest/
{
  "manifest": {
    "manifest_version": "1.0",
    "upload_id": "550e8400-e29b-41d4-a716-446655440000",
    ...
  }
}

Response: 
{
  "valid": true,
  "errors": []
}

Or (if invalid):
{
  "valid": false,
  "errors": [
    {
      "field": "$.patient.pseudo_id",
      "code": "pattern",
      "message": "Value does not match pattern '^[A-Za-z0-9_-]{8,64}$'"
    }
  ]
}
```

### 4.2 Chunk Corruption Detection (Enhanced Verification)

**Problem**: After uploading chunks, there was no way to detect if chunks became corrupted on disk or during transfer (bit rot, network errors, etc.).

**Solution**: Enhanced chunk storage with dual-hash verification (SHA256 + CRC32) and new `/api/v1/uploads/chunked/{session_id}/verify/` endpoint.

**Key Features**:
- ✅ SHA256 hashing (cryptographic, used during upload verification)
- ✅ CRC32 checksums (fast, computed automatically, used for quick corruption detection)
- ✅ Verify chunks anytime (not just during upload)
- ✅ Detailed error reporting (per-chunk corruption details)
- ✅ Recovery recommendations (what to do if corruption detected)

**Database Enhancement**:
- New field: `UploadChunk.chunk_crc32` (8-char hex string)
- Stored automatically during chunk upload
- Used for quick verification checks

**Verification Strategies**:

1. **During Chunk Upload** (existing):
   - Client computes SHA256 of chunk
   - Server stores chunk, verifies SHA256
   - High-confidence verification before storage

2. **After Upload Complete** (NEW):
   - Client can call verify endpoint anytime
   - Endpoint checks file existence, SHA256, and CRC32
   - Detailed report of any corrupted chunks
   - Can verify all chunks or specific chunks

**Request/Response Example**:
```json
POST /api/v1/uploads/chunked/{session_id}/verify/
Authorization: Bearer TOKEN

Response (All Healthy):
{
  "session_id": "abc-123-def",
  "verification_status": "success",
  "total_checked": 100,
  "passed": 100,
  "failed": 0,
  "corrupted_chunks": []
}

Response (Corruption Detected):
{
  "session_id": "abc-123-def",
  "verification_status": "corruption_detected",
  "total_checked": 100,
  "passed": 95,
  "failed": 5,
  "recommend_restart": true,
  "corrupted_chunks": [
    {
      "chunk_number": 23,
      "error": "SHA256 mismatch: expected abc..., got def...",
      "status": "sha256_mismatch"
    },
    {
      "chunk_number": 45,
      "error": "CRC32 mismatch: expected 12345678, got 87654321",
      "status": "crc32_mismatch"
    }
  ]
}
```

**Error Status Codes**:
- `missing` - Chunk file not found on disk
- `sha256_mismatch` - SHA256 hash doesn't match (corrupted data)
- `crc32_mismatch` - CRC32 checksum mismatch (fast corruption detection)
- `metadata_missing` - Database record not found

### 4.3 New Database Fields

**UploadChunk Model Enhancement**:
```python
chunk_crc32 = CharField(max_length=8, null=True, blank=True)
# Stores hex-formatted CRC32 checksum for fast corruption detection
```

**Backward Compatibility**:
- Field is nullable (optional for old chunks)
- No breaking changes to existing uploads
- Existing code still works unchanged

### 4.4 Integration with Upload Flow

**Old Flow** ❌:
```
1. Start uploading → 2. Upload file (hours) → 3. Extract & validate → 4. ❌ ERROR: Invalid manifest
```

**New Flow** ✅:
```
1. Validate manifest (< 1 sec)
2. ✅ Start upload (if valid)
3. Upload file (hours)
4. [OPTIONAL] Verify chunks (1-5 sec)
5. Complete & extract
6. Process in background
```

---

### 4.5 Automatic Chunk Verification During Upload

**New Feature** (Latest):  Chunked uploads now verify each chunk automatically during upload without requiring separate API calls.

#### Problem Solved
- Users uploading large files (> 2GB) had no way to know if chunks were corrupted until the very end (after uploading everything)
- If corruption was detected, users had no way to know which specific chunks needed retry
- Corruption detection required an extra API call to `/verify/` endpoint
- Large file uploads meant wasted bandwidth and time if corruption occurred midway

#### Solution: Real-Time Chunk Verification
```
Upload chunk 1 
  ↓
Automatic SHA256 + CRC32 verification
  ↓
Response includes: "verification_status": "VERIFIED", "needs_reupload": false
  ↓
Upload chunk 2
  ↓
Automatic verification
  ↓
If corruption: Response includes error details
  ↓
User can immediately retry just that chunk
  ↓
No need to call separate /verify/ endpoint!
```

#### Key Features

**Immediate Feedback:**
- Each chunk upload response includes verification results
- No extra API call needed
- User knows immediately if chunk is good or bad

**Detailed Error Information:**
- Which specific chunks are corrupted
- SHA256 vs CRC32 mismatch details
- Timestamp of when verification occurred

**Resume Capability:**
- `GET /api/v1/uploads/chunked/{session_id}/status/` endpoint shows:
  - Total verified chunks
  - List of chunks needing retry
  - Error details for each corrupted chunk
- Users can retry only the failing chunks

**Example Upload Response**
```json
{
  "session_id": "uuid",
  "chunk_number": 0,
  "verification_status": "VERIFIED",
  "verification_success": true,
  "verification_error": null,
  "needs_reupload": false,
  "verified_chunks": 1,
  "corrupted_chunks": 0
}
```

**Example Status Endpoint Response**
```json
{
  "session_id": "uuid",
  "total_chunks": 100,
  "verified_chunks": 95,
  "corrupted_chunks": 3,
  "needs_reupload": [5, 25, 80],
  "upload_can_resume": true,
  "chunks_status": [
    {
      "chunk_number": 5,
      "status": "CORRUPTED",
      "error": "CRC32 mismatch: expected a1b2c3d4, got e5f6g7h8"
    }
  ]
}
```

#### Verification States

| State | Meaning | Action for User |
|---|---|---|
| **VERIFIED** ✅ | Chunk passed SHA256 + CRC32 | None, continue uploading |
| **CORRUPTED** ❌ | Chunk failed verification | Retry this chunk |
| **NEEDS_REUPLOAD** ⚠️ | Reserved for future use | Retry this chunk |
| **PENDING** | Not yet verified | Wait for verification |

#### Recovery Workflow

```
Scenario: Upload 10 chunks, chunk #5 gets corrupted

1. Upload chunks 0-4: ✅ All verified
2. Upload chunk 5: ❌ Corruption detected
   - Response: "needs_reupload": true, "error": "CRC32 mismatch..."
3. Query /status/ endpoint
   - Returns: needs_reupload: [5]
4. Retry chunk 5
   - New verification passes ✅
5. Upload chunks 6-9: ✅ All verified
6. All chunks ready for completion!
```

#### Implementation Details

**Verification Process:**
1. Chunk bytes are received and stored to disk
2. SHA256 hash computed (cryptographic verification)
3. CRC32 hash computed (quick corruption check)
4. Hashes compared with expected values from client
5. If all match: `verification_status='VERIFIED'`, timestamp recorded
6. If mismatch: `verification_status='CORRUPTED'`, error details stored

**Database Schema:**
- `UploadChunk.verification_status`: CharField with choices (PENDING/VERIFIED/CORRUPTED/NEEDS_REUPLOAD)
- `UploadChunk.verification_error`: TextField for storing error details
- `UploadChunk.verification_timestamp`: DateTimeField for when verification occurred
- Index on `verification_status` for fast filtering

**Backward Compatibility:**
- Legacy `verified` boolean field still functional
- Existing chunks get `verification_status='PENDING'` if not previously verified
- Old `/verify/` endpoint still works for explicit verification (can be called anytime)

#### Benefits

✅ **No Extra API Calls** — Verification happens automatically during upload
✅ **Early Detection** — Know immediately if chunk is bad
✅ **Faster Recovery** — Retry only corrupted chunks, not the entire upload
✅ **Clear Visibility** — Always know which chunks need retry via /status/ endpoint
✅ **Peace of Mind** — Every chunk verified with both SHA256 and CRC32

---

## 5. Expected Tar Structure

Every uploaded archive must conform to the following layout. `manifest.json` must be at the root of the archive.

```
upload.tar
├── manifest.json       ← required, at root
└── images/             ← all DICOM files, flat or nested
    ├── img_001.dcm
    ├── img_002.dcm
    └── ...
```

Filenames in the `images` array of `manifest.json` must match paths relative to the archive root. The system rejects archives with path traversal characters (`../`) or symlinks.

---

## 6. REST API

### 6.1 Endpoints

#### Standard Upload Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/uploads/` | Token | Submit a new tar archive (up to 2GB). Returns job_id. |
| GET | `/api/v1/uploads/{job_id}/` | Token | Poll upload job status and error details. |
| GET | `/api/v1/uploads/` | Token | List all jobs for the authenticated uploader. |
| GET | `/api/v1/studies/` | Token | List ingested studies with Orthanc study UIDs. |
| GET | `/api/v1/studies/{study_uid}/` | Token | Retrieve study mapping + proxied QIDO-RS metadata from Orthanc. |
| DELETE | `/api/v1/uploads/{job_id}/` | Admin | Cancel a pending job and purge temp files. |

#### Manifest Validation Endpoint (Early Validation - NEW)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/uploads/validate-manifest/` | Token | Validate manifest.json BEFORE uploading large files. Returns validation errors or success. |

#### Chunked Upload Endpoints (For Large Files > 2GB)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/uploads/chunked/init/` | Token | Initialize a chunked upload session. Returns session_id. |
| POST | `/api/v1/uploads/chunked/{session_id}/chunk/` | Token | Upload a single chunk. Query params: chunk_number, chunk_hash. **Automatic verification happens in response** ✨ |
| GET | `/api/v1/uploads/chunked/{session_id}/progress/` | Token | Get chunked upload progress (list of uploaded chunks). |
| GET | `/api/v1/uploads/chunked/{session_id}/status/` | Token | Get detailed resumption status: verified/corrupted chunks, which ones need retry. **(NEW - Automatic Verification)** ✨ |
| POST | `/api/v1/uploads/chunked/{session_id}/verify/` | Token | Verify chunks for corruption using SHA256 + CRC32. (Optional - for explicit on-demand verification) |
| POST | `/api/v1/uploads/chunked/{session_id}/complete/` | Token | Assemble chunks and create UploadJob. Body: { "file_hash": "..." } |
| DELETE | `/api/v1/uploads/chunked/{session_id}/` | Token | Cancel chunked upload and clean up temp files. |

> **✨ New Feature:** Chunk uploads now include automatic verification results in the response. No separate `/verify/` call needed for standard operation. See [Section 4.5](#45-automatic-chunk-verification-during-upload) for details.

> **Note:** Image and series metadata queries are answered by proxying to Orthanc's QIDO-RS endpoint, not from Django's database. Django holds only the `pseudo_id ↔ orthanc_study_id` mapping.

### 6.2 Standard Upload Request

`Content-Type: multipart/form-data`

- **`tar_file`** — The `.tar` or `.tar.gz` archive. Maximum size configurable, default 2 GB.
- **`uploader_id`** — Optional. Pseudonymized identifier for the submitting user. Defaults to the authenticated token's owner.

### 6.3 Chunked Upload Request Examples

**1. Initialize Chunked Upload**

```
POST /api/v1/uploads/chunked/init/
Content-Type: application/json
Authorization: Bearer TOKEN

{
  "filename": "medical_archive_2024.tar.gz",
  "total_size": 68719476736,
  "chunk_size": 10485760,
  "file_hash": "a1b2c3d4e5f6..."
}
```

Response:
```
HTTP 201 Created
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "medical_archive_2024.tar.gz",
  "total_size": 68719476736,
  "total_chunks": 6872,
  "chunk_size": 10485760,
  "expires_at": "2024-03-10T10:00:00Z"
}
```

**2. Upload Chunk**

```
POST /api/v1/uploads/chunked/550e8400.../chunk/?chunk_number=0&chunk_hash=abc123...
Authorization: Bearer TOKEN

[binary chunk data]
```

Response:
```
HTTP 202 Accepted
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "chunk_number": 0,
  "chunk_size": 10485760,
  "uploaded_chunks": 1,
  "total_chunks": 6872,
  "progress_percent": 0,
  "status": "IN_PROGRESS"
}
```

**3. Check Progress**

```
GET /api/v1/uploads/chunked/550e8400-e29b-41d4-a716-446655440000/progress/
Authorization: Bearer TOKEN
```

Response:
```
HTTP 200 OK
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "medical_archive_2024.tar.gz",
  "status": "IN_PROGRESS",
  "total_chunks": 6872,
  "uploaded_chunks": 3436,
  "progress_percent": 50,
  "chunks": [
    {
      "chunk_number": 0,
      "chunk_size": 10485760,
      "chunk_hash": "abc123...",
      "uploaded_at": "2024-02-26T10:00:05Z",
      "verified": true
    },
    ...
  ]
}
```

**4. Complete Upload**

```
POST /api/v1/uploads/chunked/550e8400-e29b-41d4-a716-446655440000/complete/
Content-Type: application/json
Authorization: Bearer TOKEN

{
  "file_hash": "a1b2c3d4e5f6..."
}
```

Response:
```
HTTP 200 OK
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "COMPLETED",
  "filename": "medical_archive_2024.tar.gz",
  "file_hash": "a1b2c3d4e5f6...",
  "job_id": "660e8400-e29b-41d4-a716-446655440001",
  "job_status_url": "/api/v1/uploads/660e8400-e29b-41d4-a716-446655440001/",
  "completed_at": "2024-02-26T10:30:00Z"
}
```

### 6.4 Job Status Response

`GET /api/v1/uploads/{job_id}/` returns:

- `job_id` — UUID string
- `status` — one of: `PENDING`, `PROCESSING`, `COMPLETE`, `FAILED`, `PARTIAL`
- `submitted_at` / `completed_at` — ISO 8601 timestamps
- `image_count` — total images in manifest vs. successfully pushed to Orthanc
- `orthanc_study_ids` — list of Orthanc study UUIDs created during this job
- `errors` — array of structured error objects with `filename`, `code`, and `message`

---

## 7. Database Schema

Django's PostgreSQL database stores only what Orthanc cannot: upload audit records, the pseudo_id mapping, and annotation metadata. DICOM image and series data are **not** duplicated here — query Orthanc's QIDO-RS for those.

### UploadJob

| Column | Type |
|---|---|
| id | UUID PK |
| uploader_id | VARCHAR — pseudonymized submitter |
| status | ENUM (PENDING, PROCESSING, COMPLETE, FAILED, PARTIAL) |
| submitted_at | TIMESTAMPTZ |
| completed_at | TIMESTAMPTZ nullable |
| manifest_raw | JSONB — original manifest retained for audit |
| error_report | JSONB nullable — structured per-image errors |

### Patient

| Column | Type |
|---|---|
| id | UUID PK |
| pseudo_id | VARCHAR UNIQUE — opaque patient pseudonym |
| sex | CHAR(1) nullable |
| age_at_first_acquisition | INT nullable |
| cohort_tag | VARCHAR nullable |
| created_at | TIMESTAMPTZ |

### StudyMapping

Maps Django's pseudonymized study identity to Orthanc's internal study ID. This is the critical join between the two systems.

| Column | Type |
|---|---|
| id | UUID PK |
| patient | FK → Patient |
| upload_job | FK → UploadJob |
| pseudo_study_uid | VARCHAR UNIQUE — pseudonymized UID from manifest |
| orthanc_study_id | VARCHAR UNIQUE — UUID returned by Orthanc after STOW-RS |
| acquisition_date | DATE |
| clinical_indication | TEXT nullable |
| pathology_labels | VARCHAR[] nullable |
| contrast_used | BOOLEAN |
| cohort_tag | VARCHAR nullable |
| source_institution | VARCHAR nullable |
| notes | TEXT nullable |
| created_at | TIMESTAMPTZ |

### Annotation

Annotations are stored in Django rather than Orthanc because they are research/ML artifacts that may not conform to standard DICOM SR. They reference Orthanc resources by instance ID.

| Column | Type |
|---|---|
| id | UUID PK |
| study_mapping | FK → StudyMapping |
| orthanc_instance_id | VARCHAR — Orthanc instance UUID this annotation targets |
| annotation_uid | VARCHAR — from manifest |
| annotator_id | VARCHAR — pseudonymized |
| annotation_date | DATE nullable |
| type | ENUM (SEGMENTATION, BOUNDING_BOX, LANDMARK, CLASSIFICATION) |
| label | VARCHAR |
| annotation_data | JSONB nullable — inline annotation payload |
| annotation_file | FileField nullable — stored on Django server filesystem |

### ChunkedUpload

Tracks large file uploads that are split into chunks. Used for files >2GB and up to 1TB.

| Column | Type |
|---|---|
| id | UUID PK |
| uploader_id | VARCHAR — user uploading the file |
| filename | VARCHAR — original filename |
| status | ENUM (INITIATED, IN_PROGRESS, COMPLETED, FAILED, CANCELLED) |
| total_size | BIGINT — total file size in bytes |
| total_chunks | INT — total number of expected chunks |
| uploaded_chunks | INT — number of chunks successfully received |
| chunk_size | INT — size of each chunk in bytes (default 10MB) |
| file_hash | VARCHAR nullable — SHA256 hash of complete file (for verification) |
| temp_dir | VARCHAR — temporary directory where chunks are stored |
| created_at | TIMESTAMPTZ |
| updated_at | TIMESTAMPTZ |
| completed_at | TIMESTAMPTZ nullable — when upload was completed |
| expires_at | TIMESTAMPTZ nullable — auto-delete incomplete uploads after this time |

### UploadChunk

Individual chunks within a chunked upload session.

| Column | Type |
|---|---|
| id | UUID PK |
| chunked_upload | FK → ChunkedUpload |
| chunk_number | INT — sequential chunk number (0-based) |
| chunk_size | BIGINT — actual size of this chunk in bytes |
| chunk_hash | VARCHAR — SHA256 hash of chunk (for integrity verification) |
| file_path | VARCHAR — path to chunk file on disk |
| uploaded_at | TIMESTAMPTZ |
| verified | BOOLEAN — whether chunk integrity has been verified |
| **Constraint** | UNIQUE (chunked_upload_id, chunk_number) |

---

## 8. Validation Rules

### 7.1 Tar Validation

- Archive must be a valid `.tar` or `.tar.gz`; other formats rejected
- Must not exceed configured size limit (default 2 GB)
- Must contain `manifest.json` at root level
- Must not contain path traversal sequences (`../`) or symbolic links
- Total file count must not exceed configured maximum (default 10,000)

### 7.2 Manifest Validation

- Must be valid JSON conforming to the v1.0 JSON Schema
- `manifest_version` must be a supported version string
- `study.acquisition_date` must be a valid ISO 8601 date, not in the future
- `patient.pseudo_id` must be non-empty and match pattern `[A-Za-z0-9_-]{8,64}`
- Each image entry must reference a file that exists in the tar
- Duplicate filenames within a single manifest are rejected
- `checksum_sha256` must match the actual file content

### 7.3 DICOM Anonymization Validation

Before pushing to Orthanc, the worker validates that each DICOM file is **already anonymized** according to GDPR-strict.json standards:

1. **Parse DICOM headers** — Read DICOM file with `pydicom` to extract and validate structure.
2. **Validate GDPR-strict compliance** — Check that file conforms to all rules defined in `GDPR-strict.json`:
   - Verify all PHI tags are absent or properly emptied (PatientName, BirthDate, Sex, etc.)
   - Verify PatientID matches the manifest pseudo_id
   - Verify StudyID, StudyInstanceUID, SeriesInstanceUID are pseudonymized/new (not original format)
   - Verify no private tags exist
   - Verify no overlay, curve, or audio data present
   - Verify UIDs are in new format (e.g., UUIDs), not original DICOM UIDs
3. **Optional pixel-level scanning** — Use OCR to scan pixel data for visible text/identifiers.
4. **Pass/Fail Decision** — If all checks pass, push to Orthanc. If any check fails, reject the image with a detailed error code.
5. **In-memory processing** — All validation occurs in memory; original file is never modified.
6. **Push to Orthanc** — Send DICOM file to Orthanc via STOW-RS **without any modifications**. Original file is deleted with temp directory on task completion.

**Important:** The system does **not modify or transform** DICOM data. It only **validates** that incoming files are already properly anonymized. If validation fails, the file is rejected and not pushed to Orthanc.

---

## 9. Orthanc Integration

### 7.1 STOW-RS Push (Ingest)

Each scrubbed DICOM file is pushed to Orthanc using the DICOMweb STOW-RS endpoint:

```
POST {ORTHANC_BASE_URL}/dicom-web/studies
Content-Type: multipart/related; type="application/dicom"
```

Orthanc returns a response body containing the assigned `StudyInstanceUID`, `SeriesInstanceUID`, and `SOPInstanceUID`. The `StudyInstanceUID` is stored in `StudyMapping.orthanc_study_id`.

If Orthanc returns a non-2xx response for an individual file, the image is recorded in the job's `error_report` and processing continues with the remaining files (partial ingest behaviour).

### 7.2 QIDO-RS Proxy (Metadata Retrieval)

Django does not store DICOM series or instance metadata. The `GET /api/v1/studies/{study_uid}/` endpoint:

1. Looks up `orthanc_study_id` from `StudyMapping` using the provided `pseudo_study_uid`
2. Proxies a QIDO-RS request to Orthanc: `GET {ORTHANC_BASE_URL}/dicom-web/studies/{orthanc_study_id}/series`
3. Returns the Orthanc response to the client, merged with Django-side fields (`pseudo_id`, `annotations`)

### 7.3 Orthanc Configuration Requirements

The Orthanc instance must have the following plugins enabled:

- **DicomWeb plugin** — for STOW-RS ingest and QIDO-RS/WADO-RS queries
- **PostgreSQL plugin** (recommended) — for production-grade Orthanc index storage instead of SQLite
- **Authorization plugin** (recommended) — to restrict direct Orthanc API access to trusted services only

Orthanc should **not** be directly exposed to end users. All access flows through the Django API layer, which enforces pseudonymization and token authentication.

### 7.4 Orthanc Storage Options

Orthanc manages its own storage independently. This is an Orthanc-level configuration concern and does not affect the Django application layer.

| Backend | Use case |
|---|---|
| Filesystem (default) | Development and small deployments |
| orthanc-object-storage plugin | Production with MinIO or cloud-hosted S3 |
| PostgreSQL plugin | Scalable index; combine with filesystem or object-storage for file data |

---

## 10. Security & Compliance

### 8.1 Authentication & Access Control

#### IP-Based Access Restriction
The system provides a **whitelist-based IP access control mechanism** to restrict API access to authorized networks only.

**Configuration:**
```python
# .env file
IP_WHITELIST=192.168.1.0/24,10.0.0.0/8,203.0.113.50
```

**Features:**
- Supports single IP addresses and CIDR notation (network ranges)
- Automatically detects proxied clients via `X-Forwarded-For` header
- Configurable exempted paths (always accessible for authentication)
  - `/admin/login/` - Django admin interface
  - `/api/v1/auth/login/` - API login endpoint
- Returns HTTP 403 Forbidden for blocked IPs
- Logs all denied access attempts to security audit trail

**Example CIDR Ranges:**
| Range | Meaning | Example Use |
|---|---|---|
| `10.0.0.0/8` | 10.0.0.0 to 10.255.255.255 | Private network class A |
| `172.16.0.0/12` | 172.16.0.0 to 172.31.255.255 | Private network class B |
| `192.168.0.0/16` | 192.168.0.0 to 192.168.255.255 | Private network class C |
| `203.0.113.50/32` | Only 203.0.113.50 | Single IP |

**Implementation Details:**
- Middleware: `ct_upload_platform.middleware.IPWhitelistMiddleware`
- Enabled in `settings.py` MIDDLEWARE list
- Uses Python `ipaddress` library for CIDR range matching
- When disabled (IP_WHITELIST empty), all IPs are allowed

#### User Login & Bearer Token Authentication
The system provides both REST API and web-based login, using bearer tokens for stateless API authentication.

**Login REST API Endpoint:**
```
POST /api/v1/auth/login/
Content-Type: application/json

Request:
{
  "username": "john.doe",
  "password": "SecurePassword123"
}

Response (200 OK):
{
  "token": "abc123xyz...",
  "user_id": 42,
  "username": "john.doe",
  "email": "john.doe@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "is_staff": false
}

Error Response (401 Unauthorized):
{
  "error": "Invalid username or password"
}
```

**Features:**
- No authentication required (accessible from exempt IPs)
- Returns full user information including token
- Token can be immediately used in subsequent API calls
- Supports both `Bearer <token>` and `Token <token>` authorization headers
- Token is created/retrieved from database (persistent across sessions)

**Security Characteristics:**
- Tokens are **one-per-user** (additional logins return the same token)
- Tokens have no built-in expiry at the application level (configurable in settings)
- Tokens are transmitted only in Authorization header (never in query strings or body)
- Token signing uses Django REST Framework defaults (salted hashing)

**Login Page (Web UI):**
- URL: `/login/`
- Modern, responsive design with error handling
- Stores token in browser localStorage on successful login
- Auto-redirects authenticated users to main page
- Client-side JavaScript integrates with REST API

#### User Creation & Credential Distribution

**Management Command:**
```bash
python manage.py create_user \
  --username john.doe \
  --email john.doe@example.com \
  --first-name John \
  --last-name Doe \
  [--is-staff] \
  [--is-superuser] \
  [--no-email] \
  [--password-length 16]
```

**Features:**
- Generates cryptographically random password (16+ characters by default)
- Sends credentials via email using configured email backend
- Supports staff and superuser roles
- Validates username/email uniqueness
- Password includes mixed case, digits, and special characters (excludes ambiguous chars like 'l', 'O')
- Can skip email sending via `--no-email` flag

**Email Template:**
New users receive an email containing:
- Username
- Auto-generated password
- Login URL
- Reminder to change password on first login

**Configuration:**
```python
# .env file
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-specific-password
DEFAULT_FROM_EMAIL=noreply@ct-upload-platform.local
```

#### Token-Based API Authentication

All REST API endpoints (except `/api/v1/auth/login/`) require a **Bearer token** in the Authorization header:

```bash
# Preferred format
curl -H "Authorization: Bearer abc123..." http://localhost:8000/api/v1/uploads/

# Also supported (legacy)
curl -H "Authorization: Token abc123..." http://localhost:8000/api/v1/uploads/
```

**Authentication Flow:**
1. Client calls `POST /api/v1/auth/login/` with username and password
2. Server returns Bearer token
3. Client includes token in `Authorization: Bearer <token>` header for all subsequent requests
4. Server validates token and grants access

**Permissions:**
- `AllowAny`: `/api/v1/auth/login/` - No authentication required
- `IsAuthenticated`: All other endpoints - Valid token required
- `IsAdminUser`: Future admin endpoints - Staff user with token required

### 8.2 Data Protection & PHI Handling

#### No PHI in Django or Orthanc
- The Django database **never** stores patient names, DOBs, original MRN, addresses, medical record numbers, or any identifying information.
- DICOM files uploaded to this platform **must already be anonymized** according to GDPR-strict.json standards.
- The platform **validates** anonymization compliance, not performs it. Files that fail anonymization validation are rejected.
- Because only anonymized DICOM data is accepted and pushed to Orthanc, Orthanc stores only de-identified data.
- The `pseudo_id ↔ orthanc_study_id` mapping in Django is the **only re-identification key** and must be protected with extreme care (see **Access Control** section below).

#### GDPR-Strict Anonymization Validation
The system validates that each DICOM file **is already anonymized** according to `GDPR-strict.json` rules before accepting it:

**Validation Rules:**
| DICOM Tag | Must Be | Validation Check |
|---|---|---|
| `PatientName` | Empty/Missing | Reject if present and non-empty |
| `PatientID` | Present, matches manifest pseudo_id | Reject if missing or doesn't match |
| `PatientBirthDate` | Empty/Missing | Reject if present |
| `PatientSex` | Empty/Missing | Reject if present |
| `PatientAge` | Empty/Missing | Reject if present |
| `InstitutionName` | Empty/Missing | Reject if present |
| `ReferringPhysicianName` | Empty/Missing | Reject if present |
| `AccessionNumber` | Empty/Missing | Reject if present |
| `StudyID` | Present, pseudonymized | Reject if original format detected |
| `StudyInstanceUID` | Present, new UID (not original) | Reject if original format detected |
| `SeriesInstanceUID` | Present, new UID (not original) | Reject if original format detected |
| `FrameOfReferenceUID` | Empty or new UID (if present) | Reject if original format detected |
| **Private Tags** | None present | Reject if any private tags found (group number `%2 == 1`) |
| **Overlay Data** | None present | Reject if overlay data exists |
| **Curve/Audio Data** | None present | Reject if curve or audio data exists |

**Pixel-Level Validation:**
- The system scans pixel data for visible text, burn-in identifiers, or stamps using OCR (optional but recommended).
- If potential identifying information is detected in pixel data, the image is flagged for manual review and **rejected by default** (configurable).
- Blackout regions must be verified as properly applied (uniform color/noise, not just masked).

**Non-Compliant File Handling:**
- If a DICOM file fails anonymization validation, it is **rejected** with a detailed error code indicating which tags/rules failed.
- The image is **not pushed to Orthanc**.
- The error is logged in the job's `error_report` with the filename and specific validation failure reasons.
- Processing continues with the next files (partial ingest behavior); the upload job is marked as `PARTIAL` if some files pass but others fail.

#### File Storage & Cleanup Strategy
- **Raw tar files** in `raw_data/{uploader_id}/` are **never automatically deleted** to preserve audit trail and enable re-processing.
- **Extracted tar contents** in `processed_data/{job_id}/` are:
  - **Preserved** if processing completes successfully (COMPLETE or PARTIAL status) for auditing and troubleshooting
  - **Deleted** if processing fails (FAILED status) to reclaim disk space
  - **Deleted** if explicitly requested by admin via cleanup job
- **Disk space monitoring**: Implement periodic audits to track `raw_data/` and `processed_data/` sizes and alert on threshold breaches (e.g., 500 GB limit).
- **Enforced cleanup policies** via scheduled Django management commands:
  - Archive `raw_data/` files older than 2 years to cold storage
  - Delete `processed_data/` for jobs older than 1 year with COMPLETE status
  - Script should be configurable and logged
- **Secure deletion** (optional): For sensitive environments, overwrite files with random data before filesystem deletion using `shred` (Linux) or `secure_erase` (macOS).
- **Encryption at rest**: Consider encrypting sensitive files using filesystem-level encryption (dm-crypt, BitLocker, etc.) or application-level encryption for regulatory compliance.

### 8.3 Input Validation & Threat Prevention

#### Tar Archive Validation
- Archive **must** be a valid `.tar` or `.tar.gz`; other formats (ZIP, RAR, etc.) are rejected.
- **Magic byte validation** is performed before any processing.
- Must not exceed configured size limit (default 2 GB) and uncompressed size limits.
- Must contain `manifest.json` at root level.
- Must **not** contain path traversal sequences (`../`, `..\\`), absolute paths, or symbolic links.
- Total file count must not exceed configured maximum (default 10,000).
- **Directory traversal testing**: Incoming archive is scanned for `..` in member names and member paths that escape the extraction directory.
- **Hard limits** on extracted file sizes prevent zip-bomb style attacks (compressed bomb).

#### Manifest JSON Validation
- Must be valid JSON conforming to v1.0 JSON Schema (schema validation is non-nullable).
- `manifest_version` must be an accepted version string; other versions are rejected immediately.
- `study.acquisition_date` must be a valid ISO 8601 date and **must not be in the future** (prevents timezone-based bypass).
- `patient.pseudo_id` must be non-empty, alphanumeric (pattern: `[A-Za-z0-9_-]{8,64}`), and **globally unique across the system**.
  - Duplicate pseudo_ids across separate uploads are **rejected or require explicit reconciliation approval**.
  - UUIDs or cryptographically random identifiers are preferred over human-readable pseudonyms.
- Each image entry must reference a file that exists in the tar (**fail-fast validation before extraction**).
- Duplicate filenames within a single manifest are rejected.
- `checksum_sha256` must match the actual file content; mismatches fail the individual image and log a security event.
- **Additional validation rules:**
  - All string fields are trimmed and validated against whitelisted character sets.
  - No excessively long strings (max 1024 characters per field) to prevent memory exhaustion.
  - All arrays have maximum element counts (e.g., max 1000 images per manifest).

#### DICOM File Validation
- Files are validated for DICOM compliance using `pydicom` before any further processing.
- **All private tags are logged** for audit purposes (even though they are removed).
- DICOM metadata is read in **stop-before-pixels mode** to avoid unnecessary memory overhead.
- Files with unreadable DICOM headers are rejected (image is marked failed, processing continues with next file).
- **Machine Learning / AI-Based Anomaly Detection** (optional advanced control):
  - Consider scanning DICOM pixel data for text/overlays using OCR as a second line of defense.
  - Flag DICOM files with suspicious pixel patterns or detected text for manual review before pushing to Orthanc.

### 8.4 Network Security & Encryption

#### HTTPS / TLS Enforcement
- **All external API traffic must be HTTPS-only** (TLS 1.2 minimum, TLS 1.3 preferred).
- **HTTP is forbidden** in production; requests are redirected or rejected outright.
- Implement `SECURE_SSL_REDIRECT = True` and related Django security settings:
  - `SECURE_HSTS_SECONDS = 63072000` (2 years)
  - `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`
  - `SECURE_HSTS_PRELOAD = True`
  - `SESSION_COOKIE_SECURE = True`
  - `CSRF_COOKIE_SECURE = True`
- Use **strong cipher suites** (no RC4, DES, or export-grade ciphers).
- **Configuration file for TLS:** Maintain a reference nginx/reverse-proxy `ssl.conf` or similar to enforce TLS best practices.

#### Certificate Pinning
- For **service-to-service communication** (Django → Orthanc, Celery → Orthanc):
  - Enable **TLS certificate pinning** to prevent man-in-the-middle (MITM) attacks.
  - Use `certifi` + custom `requests` adapter for Python, or equivalent in other languages.
  - Pin the **leaf certificate or public key**, not the root CA, to allow for seamless renewal.
  - Maintain a **certificate inventory** and rotation schedule (rotate every 6-12 months or on compromise).

#### Internal Network Segmentation
- **Orthanc must not be directly exposed to the internet.** Only accessible from:
  - Django API server (restricted IP range or private network)
  - Celery worker nodes (restricted IP range or private network)
- Use **network firewall rules** (security groups, iptables, etc.) to enforce this segmentation.
- If running in Kubernetes, use **NetworkPolicies** to restrict traffic.
- Django API server **must** be the only external-facing service.

#### Secure Service Configuration
- Redis (Celery broker) **must not be exposed to the internet**. Restrict access to Django/Celery services only.
- PostgreSQL **must not be exposed to the internet** (only accessible from Django).
- All services should run **outside DMZ**; place only load balancer/reverse proxy in DMZ.

### 8.5 Secrets Management & Configuration

#### Secure Secrets Storage
- **Never hardcode secrets** in code or configuration files.
- Use environment variables or a secrets manager for:
  - `SECRET_KEY` (Django)
  - `ORTHANC_USERNAME`, `ORTHANC_PASSWORD`
  - `DB_PASSWORD`
  - `REDIS_PASSWORD` (if Redis has authentication)
  - API token signing key (if custom)
- **Recommended secrets manager** (pick one):
  - **AWS Secrets Manager** (for AWS deployments)
  - **HashiCorp Vault** (multi-cloud, on-premises)
  - **Azure Key Vault** (for Azure deployments)
  - **Kubernetes Secrets + sealed-secrets** (for Kubernetes)
  - **Docker Swarm secrets** (for Swarm deployments)
- If using environment variables, ensure they are **never exposed in logs or error messages**.

#### Configuration Management
- Maintain **separate configuration files** for development, staging, and production:
  - Development: Relaxed settings (debug=true, shorter timeouts)
  - Staging: Prod-like settings with less restricted limits
  - Production: Strict settings (debug=false, TLS enforced, rate limiting, MFA, etc.)
- Use **Django settings modules** (`test_settings.py`, `settings.py`) with conditional imports.
- **Never commit secrets** to version control (use `.env` files with `.gitignore` exclusions).
- Use `python-environ` or similar to load secrets from environment variables at startup.

#### Credential Rotation
- Implement **automated credential rotation** for database, Redis, and Orthanc credentials:
  - Rotate credentials **every 90 days** or immediately on suspected compromise.


#### API Rate Limiting
- Implement **per-user rate limiting** on all API endpoints:
  - `POST /api/v1/uploads/`: Max 10 uploads per hour per user
  - `GET /api/v1/uploads/`: Max 100 requests per minute per user
  - `GET /api/v1/studies/`: Max 100 requests per minute per user
- Use Django packages: `djangorestframework-throttling` or `django-ratelimit`.
- Return `HTTP 429 Too Many Requests` with `Retry-After` header when limit is exceeded.
- **Burst protection:** Limit concurrent requests from a single user (e.g., max 5 concurrent uploads).

#### DDoS Mitigation
- Deploy behind a **CDN or WAF** (Cloudflare, AWS WAF, Akamai) in production.
- WAF rules should block:
  - Requests with excessively large headers or bodies
  - SQL injection signatures
  - XSS payloads
  - Path traversal attempts
- Monitor request origins and **GeoIP block** if necessary (e.g., block uploads from countries outside scope).
- Implement **CAPTCHA or proof-of-work** for IP addresses with suspicious patterns.

### 8.7 Logging & Audit Trail

#### Comprehensive Audit Logging
- Log **all security-relevant events** with structured, machine-readable format (JSON):
  - Upload submission (user, timestamp, file size, manifest checksum)
  - Upload validation (pass/fail, specific failures, manifest version)
  - DICOM processing (file count, PHI tags removed, errors)
  - Authentication events (successful login, failed login, token creation/revocation, MFA attempts)
  - Authorization failures (user attempts to access another user's data)
  - Configuration changes (admin modifies settings, secrets are rotated)
  - Errors and exceptions (with stack traces for debugging, but **sanitized of credentials**)
- Create a dedicated `AuditLog` model or use an external logging service (ELK, Splunk, Datadog).
- **Structured logging format** (example):
  ```json
  {
    "timestamp": "2024-02-26T10:30:45.123Z",
    "level": "AUDIT",
    "event": "upload_submitted",
    "user_id": "user_pseudo_id",
    "upload_job_id": "uuid",
    "file_size_mb": 125.5,
    "manifest_sha256": "abc123...",
    "ip_address": "192.168.1.100",
    "user_agent": "Mozilla/5.0..."
  }
  ```

#### Log Security
- **Never log PHI** (patient names, IDs, DOBs, etc.).
- **Never log credentials** (passwords, tokens, API keys, connection strings).
- **Never log raw DICOM data** or pixel values.
- Logs are **encrypted at rest** and **in transit**.
- Log retention: Keep logs for **minimum 1 year** for audit/compliance; archive old logs to secure cold storage.
- **Log access control**: Restrict who can read logs (not accessible via web interface; admins only via secure backend).
- Implement **log integrity** via write-once storage or cryptographic signing to prevent tampering.

#### Security Monitoring & Alerting
- **Set up alerts** for suspicious activities:
  - Multiple failed authentication attempts (5+ in 5 minutes)
  - User attempting to access another user's uploads
  - Uploads with unusually large file sizes or image counts
  - DICOM validation failures spike
  - Orthanc push failures spike
  - Repeated PHI strip tag warnings (indicates malicious uploads)
  - Admin actions without documented reason
- Alert thresholds and destinations must be **configurable and monitored**.

### 8.8 Error Handling & Information Disclosure

#### Safe Error Messages
- **Never expose sensitive information** in error messages or HTTP responses:
  - ❌ `"Database connection failed: user=postgres password=secret"`
  - ✅ `"Server error: Please contact support (Error ID: abc123)"`
- Return **generic error messages** to clients; log detailed errors server-side with error IDs.
- **Error ID tracking:** Generate a unique error ID for each exception, return it to client, and enable support team to look up detailed logs by ID.
- **Stack traces are never returned** to clients in production (debug=false ensures this).

#### 500 Error Handling
- Catch **all unhandled exceptions** and return a generic 500 response with error ID.
- Implement custom exception handlers in `settings.py`:
  ```python
  EXCEPTION_HANDLER = 'your_app.exceptions.custom_exception_handler'
  ```

### 8.9 Dependency Management & Vulnerability Scanning

#### Dependency Pinning & Scanning
- **Pin all dependency versions** in `requirements.txt` (not floating versions like `Django>=4.0`).
  - Use `pip freeze > requirements.txt` to capture exact versions.
  - Regularly audit dependencies for security vulnerabilities.
- **Automated vulnerability scanning:**
  - Use `safety check` (command-line tool for Python)
  - Use `pip-audit` (maintained by PyPA)
  - Integrate into CI/CD pipeline (runs on every pull request)
  - Set up **dependency update bots** (Dependabot, Renovate) that auto-create PRs for security updates
- **Review all third-party packages** before first use (check GitHub stars, activity, known CVEs).

### 8.10 CORS & CSRF Protection

#### CORS (Cross-Origin Resource Sharing)
- **Restrict CORS** to trusted origins only:
  - Use `django-cors-headers` package
  - Configure `CORS_ALLOWED_ORIGINS = ['https://trusted-client.example.com']` (HTTPS only)
  - Never use `CORS_ALLOW_ALL_ORIGINS = True` in production
- **Restrict CORS methods** to necessary verbs (GET, POST) — never allow DELETE/PATCH without explicit need
- **Restrict CORS headers** — use whitelist, not wildcard

#### CSRF Protection
- **Enable CSRF protection** for all state-changing requests (POST, PUT, PATCH, DELETE).
- Django's `CsrfViewMiddleware` is enabled by default; ensure it's **never disabled**.
- For API endpoints, use **token-based CSRF** (X-CSRFToken header) or **same-site cookie attribute**:
  - `SESSION_COOKIE_SAMESITE = 'Strict'` (HTTPS only, same-site)
  - `CSRF_COOKIE_SAMESITE = 'Strict'`
- For REST API with token auth, CSRF is less critical (stateless), but still recommended.

### 8.11 Database Security

#### SQL Injection Prevention
- **Always use Django ORM** (QuerySet API); never construct raw SQL.
- If raw SQL is necessary, use **parameterized queries**:
  ```python
  # ✅ SAFE
  cursor.execute("SELECT * FROM uploads_uploadjob WHERE user_id = %s", [user_id])
  
  # ❌ UNSAFE
  cursor.execute(f"SELECT * FROM uploads_uploadjob WHERE user_id = {user_id}")
  ```
- Django's ORM automatically escapes values.

#### Database Access Control
- Implement **least-privilege database users**:
  - Django app connects as `app_user` with `SELECT, INSERT, UPDATE` on relevant tables only
  - Admin/maintenance connects as `admin_user` with full access
  - Read-only analytics connects as `readonly_user` with `SELECT` only
- **Enable PostgreSQL row-level security (RLS)** for multi-tenant scenarios (if applicable)
- **Database encryption at rest** (if available/required by compliance):
  - PostgreSQL: Use `pgcrypto` extension or filesystem encryption (dm-crypt, BitLocker, etc.)
  - Cloud databases: Enable transparent data encryption (AWS RDS encryption, Azure transparent encryption, etc.)

#### Database Backups
- **Backups are encrypted** at rest and in transit.
- **Backup retention policy:** Keep backups for minimum 90 days for recovery purposes.
- **Regular backup restoration testing** (monthly) to ensure backups are valid.
- **Backups are stored off-site** (different region/cloud account if possible).

### 8.12 File Upload Security

#### Upload Permissions & Storage
- Uploaded tar files and annotations are stored with **restricted file permissions** (`0600` / `rw-------`).
- **Uploaded files are scanned** for malware (optional but recommended):
  - Integrate ClamAV or similar antivirus engine
  - Scan all uploaded tarballs and media files
  - Quarantine files flagged as malicious and alert admin
- **File storage isolation**: Ensure temp files and media files are stored in directories **not served over HTTP**.
  - `TEMP_UPLOAD_DIR` should be outside the web root (not under `STATIC_ROOT` or `MEDIA_ROOT` that are served)
- **Annotation files** are stored with restricted permissions and served only to authenticated users (never publicly).

### 8.13 Production Deployment Checklist

- [ ] `DEBUG = False` in production settings
- [ ] `SECRET_KEY` is a long, random string (minimum 50 characters)
- [ ] `ALLOWED_HOSTS` is configured to specific domain(s); never use `*`
- [ ] All credentials (database, Redis, Orthanc) are loaded from environment variables
- [ ] HTTPS/TLS is enforced with `SECURE_SSL_REDIRECT = True` and HSTS headers
- [ ] CORS is restricted to trusted origins
- [ ] Rate limiting is enabled on all API endpoints
- [ ] Authentication & authorization checks are in place and tested
- [ ] Audit logging is enabled and monitored
- [ ] Error handling returns generic messages (no information disclosure)
- [ ] Dependency scanning runs in CI/CD pipeline
- [ ] Database backups are tested and encrypted
- [ ] Secrets manager is integrated (Vault, AWS Secrets Manager, etc.)
- [ ] Network segmentation isolates Orthanc and PostgreSQL
- [ ] Firewall rules restrict service-to-service access
- [ ] Log aggregation and alerting are configured

---

## 11. Configuration Reference

| Setting | Description |
|---|---|
| `IP_WHITELIST` | Comma-separated list of allowed IP addresses and/or CIDR ranges. Example: `192.168.1.0/24,10.0.0.0/8,203.0.113.50`. If not set, all IPs are allowed. Default: None |
| `EMAIL_BACKEND` | Django email backend class. Use `django.core.mail.backends.smtp.EmailBackend` for production; use `django.core.mail.backends.console.EmailBackend` for development (prints to console). Default: `console.EmailBackend` |
| `EMAIL_HOST` | SMTP server hostname (e.g., `smtp.gmail.com`, `mail.example.com`) |
| `EMAIL_PORT` | SMTP server port (typically 587 for TLS, 465 for SSL). Default: 587 |
| `EMAIL_USE_TLS` | Boolean. Use TLS for SMTP connection. Default: True |
| `EMAIL_HOST_USER` | SMTP authentication username (often an email address) |
| `EMAIL_HOST_PASSWORD` | SMTP authentication password. Use app-specific password for Gmail, Microsoft 365, etc. |
| `DEFAULT_FROM_EMAIL` | Email address used as the "From" header for system emails. Example: `noreply@ct-upload-platform.local` |
| `TOKEN_EXPIRY_DAYS` | Authentication token lifetime in days. Default: 30 |
| `ORTHANC_BASE_URL` | Base URL of the Orthanc instance, e.g. `http://orthanc:8042` |
| `ORTHANC_USERNAME` | Orthanc HTTP auth username |
| `ORTHANC_PASSWORD` | Orthanc HTTP auth password |
| `MAX_UPLOAD_SIZE_MB` | Maximum tar file size in MB. Default: 2048 |
| `MAX_IMAGES_PER_UPLOAD` | Maximum image count per archive. Default: 10000 |
| `CELERY_BROKER_URL` | Redis broker URL for async workers |
| `GDPR_STRICT_CONFIG_PATH` | Path to `GDPR-strict.json` file defining anonymization validation rules. Default: `./GDPR-strict.json` |
| `GDPR_PIXEL_SCAN_ENABLED` | Boolean. If true, use OCR to scan pixel data for visible identifiers. Default: false |
| `GDPR_PIXEL_SCAN_CONFIDENCE_THRESHOLD` | OCR confidence threshold (0-100) for flagging potential text in pixel data. Default: 80 |
| `MANIFEST_SCHEMA_VERSION` | Accepted manifest version strings. Default: 1.0 |
| `UPLOAD_TOKEN_EXPIRY_DAYS` | Upload token expiration in days (legacy, kept for compatibility). Default: 90 |
| `RAW_DATA_DIR` | Local filesystem path for storing uploaded tar files organized by uploader ID. Default: `{BASE_DIR}/raw_data` |
| `PROCESSED_DATA_DIR` | Local filesystem path for storing extracted tar contents organized by job ID. Default: `{BASE_DIR}/processed_data` |
| `CHUNKED_UPLOAD_ENABLED` | Enable/disable chunked upload feature. Default: true |
| `CHUNKED_UPLOAD_MAX_FILE_SIZE_BYTES` | Maximum file size for chunked uploads in bytes. Default: 1 TB |
| `CHUNKED_UPLOAD_DEFAULT_CHUNK_SIZE` | Default chunk size in bytes. Default: 10 MB |
| `CHUNKED_UPLOAD_EXPIRATION_DAYS` | Auto-expire incomplete chunked uploads after N days. Default: 7 |

---

## 12. Browser UI

The platform ships a server-rendered, JavaScript-enhanced browser interface in addition to the REST API. All browser pages require session authentication (login redirects unauthenticated users to `/login/`).

### 12.1 Page Map

| URL | View | Purpose |
|-----|------|---------|
| `/login/` | `LoginPageView` | AJAX login form; stores token in `localStorage` and redirects to `/` |
| `/signup/` | `SignupPageView` | Self-service account creation; token stored on success |
| `/` | `UploadAdvancedView` | Primary file-upload interface (single and chunked), status polling |
| `/examinations/entry/` | `ExaminationEntryView` | AJAX data-entry form for CT dose/quality records |
| `/examinations/` | `ExaminationListView` | Paginated list with image-quality filter |
| `/examinations/<pk>/delete/` | `ExaminationDeleteView` | POST-confirm delete for one examination record |
| `/protocols/` | `ProtocolsHubView` | Landing page linking to GUI and records |
| `/protocols/gui/` | `ProtocolGUIView` | 3-step clinical-indication → scanner → protocol-fields wizard |
| `/protocols/records/` | `ProtocolRecordsView` | Table of saved protocols with type filter |
| `/protocols/<type>/` | `ProtocolListView` | Protocols by type (PEDIATRIC_HEAD, PEDIATRIC_BODY, YOUNG_ADULT) |
| `/protocols/<type>/create/` | `ProtocolCreateView` | Django ModelForm for a new protocol |
| `/protocols/<type>/<pk>/` | `ProtocolDetailView` | Read-only protocol detail |
| `/protocols/<type>/<pk>/edit/` | `ProtocolUpdateView` | Edit an existing protocol |
| `/protocols/<type>/<pk>/delete/` | `ProtocolDeleteView` | POST-confirm delete |
| `/scanners/` | `ScannerProfileListView` | List of registered CT scanner profiles |
| `/scanners/create/` | `ScannerProfileCreateView` | Create a scanner profile |
| `/scanners/<pk>/edit/` | `ScannerProfileEditView` | Edit a scanner profile |

### 12.2 Key UI Patterns

**Cascading dropdowns**: Manufacturer → scanner model (via `GET /api/v1/scanners/models/?manufacturer_id=`) and anatomical region → clinical indication (client-side, from inline JSON data).

**Dynamic phases table**: The examination entry form renders one CTDI / DLP row per acquisition phase; the number of rows updates live as the "Number of phases" input changes.

**AJAX form submission**: Examination save (`POST /examinations/api/save/`) and protocol save (`POST /protocols/api/save/`) are non-navigating AJAX requests. Success shows an inline banner and optionally clears the form; duplicates show an "Update existing record" prompt.

**Upload progress**: Single-file uploads display a progress bar during upload. After submission the UI polls `GET /api/v1/uploads/<job_id>/` until the job reaches a terminal state and shows per-image error details if any images fail GDPR validation.

**Token management**: The upload page stores the API token in `sessionStorage` so it survives page reloads. Login and signup pages store it in `localStorage`.

### 12.3 Browser-Facing API Endpoints (non-page)

| Method | Endpoint | Used by |
|--------|----------|---------|
| `POST` | `/api/v1/auth/login/` | Login form |
| `POST` | `/api/v1/auth/signup/` | Signup form |
| `GET` | `/api/v1/scanners/models/?manufacturer_id=` | Manufacturer → model cascade |
| `POST` | `/examinations/api/save/` | Examination entry form |
| `POST` | `/protocols/api/save/` | Protocol GUI form |

---

## 13. E2E Testing

### 13.1 Test Stack

End-to-end tests use **Playwright** (TypeScript) and live in `ct_upload_platform/tests/e2e/`. All tests run against a real Django instance via HTTP — no mocking of the database or Django views.

**Dependencies** (in `ct_upload_platform/package.json`):
- `@playwright/test` — test runner, assertions, browser drivers
- `@types/node` — Node.js type definitions for TypeScript

**TypeScript configuration** (`ct_upload_platform/tsconfig.json`): compiles to ES2020, includes DOM and Node types, strict mode.

### 13.2 Test Spec Files

| File | Pages under test | Test count (approx.) |
|------|-----------------|---------------------|
| `signup.spec.ts` | `/signup/` | 15 |
| `upload.spec.ts` | `/` | 40 |
| `examination.spec.ts` | `/examinations/entry/`, `/examinations/`, `/examinations/<pk>/delete/` | 65 |
| `protocol_gui.spec.ts` | `/protocols/gui/`, `/protocols/records/` | 55 |
| `protocol_records.spec.ts` | `/protocols/records/`, `/protocols/<type>/<pk>/delete/` | 55 |
| `protocols.spec.ts` | `/protocols/<type>/`, `/scanners/` | 30 |

### 13.3 Test Infrastructure

**`fixtures.ts`** provides shared helpers:
- `createTestTarArchive()` / `createOversizedTarArchive()` — generate minimal `.tar` archives for upload tests
- `UploadPageHelper` — page-object wrapper for the upload page (fill token, select file, read status)
- `TEST_CREDENTIALS` — reads `TEST_API_TOKEN` from env, falls back to a default

**Login helper** (`login(page)`) in each authenticated spec:
```typescript
await page.fill('#username', TEST_USER.username);
await page.fill('#password', TEST_USER.password);
await page.click('#loginBtn');
// Login form uses AJAX + 2 s redirect; wait with a 10 s timeout
await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 10000 });
```

**`ensureLoggedIn(page)`** first navigates to the target page; only calls `login()` if the server redirects to `/login/`. This avoids a login round-trip when tests share a browser context.

### 13.4 Running the Suite

Prerequisites: Docker stack up, test user created, Playwright browsers installed.

```bash
# Install Node deps and browsers (once)
cd ct_upload_platform
npm install
npx playwright install chromium

# Create a test superuser (once per DB wipe)
docker compose exec web python manage.py shell -c "
from django.contrib.auth import get_user_model; U = get_user_model()
U.objects.filter(username='testqa').delete()
U.objects.create_superuser('testqa', 'testqa@test.com', 'TestQA123!')
"

# Run all tests (headless, Chromium only for speed)
BASE_URL=http://localhost:8003 TEST_USERNAME=testqa TEST_PASSWORD="TestQA123!" \
  npx playwright test --project=chromium

# Run a single spec with visible browser
BASE_URL=http://localhost:8003 TEST_USERNAME=testqa TEST_PASSWORD="TestQA123!" \
  npx playwright test tests/e2e/examination.spec.ts --project=chromium --headed

# View last HTML report
npx playwright show-report
```

Playwright is also wired to `make test-e2e` (uses `localhost:8000`; adjust `BASE_URL` for Docker port mapping).

### 13.5 Known Limitations

- **`q` full-text search on `/protocols/records/`** is accepted as a form input and appended to the URL but the `ProtocolRecordsView` does not yet filter by it server-side. The tests verify the UI structure but use `protocol_type=NONEXISTENT_TYPE` to trigger the empty-state message.
- Tests that create or delete records leave no cleanup in the database by default; run against a disposable test database or use `make clean` to reset.

---

## 14. Key Dependencies

| Package | Role |
|---|---|
| Django 5.x | Web framework |
| Django REST Framework | API layer |
| Celery | Async task queue |
| Redis | Celery broker and result backend |
| PostgreSQL 15+ | Audit and mapping database |
| pydicom | DICOM parsing, tag extraction, in-memory PHI stripping |
| requests | STOW-RS push and QIDO-RS proxy calls to Orthanc |
| jsonschema | Manifest JSON Schema validation |
| python-magic | File type detection for tar validation |
| Celery Flower (optional) | Worker monitoring dashboard |
| Orthanc + DicomWeb plugin | Authoritative DICOM storage and DICOMweb API |
