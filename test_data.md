# Test Data for CT Upload Platform

## 1. Sample manifest.json

```json
{
  "manifest_version": "1.0",
  "patient": {
    "pseudo_id": "PAT_2025_0001",
    "sex": "M",
    "age_at_first_acquisition": 62,
    "cohort_tag": "lung_cancer_screening"
  },
  "study": {
    "pseudo_study_uid": "STUDY_2025_0001",
    "acquisition_date": "2025-02-15",
    "clinical_indication": "Suspected lung nodule follow-up",
    "pathology_labels": ["nodule", "ground_glass"],
    "contrast_used": false,
    "cohort_tag": "lung_cancer_screening",
    "source_institution": "Hospital ABC",
    "notes": "High-resolution CT chest with 1mm slices"
  },
  "images": [
    {
      "filename": "images/ct_001.dcm",
      "checksum_sha256": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
      "body_part_examined": "CHEST",
      "slice_thickness_mm": 1.0,
      "pixel_spacing_mm": [0.5, 0.5],
      "laterality": "B"
    },
    {
      "filename": "images/ct_002.dcm",
      "checksum_sha256": "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3",
      "body_part_examined": "CHEST",
      "slice_thickness_mm": 1.0,
      "pixel_spacing_mm": [0.5, 0.5],
      "laterality": "B"
    },
    {
      "filename": "images/ct_003.dcm",
      "checksum_sha256": "c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
      "body_part_examined": "CHEST",
      "slice_thickness_mm": 1.0,
      "pixel_spacing_mm": [0.5, 0.5],
      "laterality": "B"
    }
  ],
  "annotations": [
    {
      "annotation_uid": "ANN_001",
      "image_filename": "images/ct_001.dcm",
      "annotator_id": "PATHOLOGIST_001",
      "annotation_date": "2025-02-20",
      "type": "SEGMENTATION",
      "label": "left_upper_lobe_nodule",
      "annotation_file": "annotations/seg_001.nii.gz"
    }
  ]
}
```

---

## 2. Database Fixture (JSON format for Django fixtures)

```json
[
  {
    "model": "uploads.patient",
    "pk": "550e8400-e29b-41d4-a716-446655440001",
    "fields": {
      "pseudo_id": "PAT_2025_0001",
      "sex": "M",
      "age_at_first_acquisition": 62,
      "cohort_tag": "lung_cancer_screening",
      "created_at": "2025-02-15T10:00:00Z"
    }
  },
  {
    "model": "uploads.uploadjob",
    "pk": "550e8400-e29b-41d4-a716-446655440002",
    "fields": {
      "uploader_id": "UPLOADER_001",
      "status": "COMPLETE",
      "submitted_at": "2025-02-15T10:05:00Z",
      "completed_at": "2025-02-15T10:15:00Z",
      "manifest_raw": {
        "manifest_version": "1.0",
        "patient": {"pseudo_id": "PAT_2025_0001"},
        "study": {"pseudo_study_uid": "STUDY_2025_0001"}
      },
      "error_report": null
    }
  },
  {
    "model": "uploads.studymapping",
    "pk": "550e8400-e29b-41d4-a716-446655440003",
    "fields": {
      "patient": "550e8400-e29b-41d4-a716-446655440001",
      "upload_job": "550e8400-e29b-41d4-a716-446655440002",
      "pseudo_study_uid": "STUDY_2025_0001",
      "orthanc_study_id": "a1b2c3d4-e5f6-47a8-9012-345678901234",
      "acquisition_date": "2025-02-15",
      "clinical_indication": "Suspected lung nodule follow-up",
      "pathology_labels": ["nodule", "ground_glass"],
      "contrast_used": false,
      "cohort_tag": "lung_cancer_screening",
      "source_institution": "Hospital ABC",
      "notes": "High-resolution CT chest with 1mm slices",
      "created_at": "2025-02-15T10:15:00Z"
    }
  },
  {
    "model": "uploads.annotation",
    "pk": "550e8400-e29b-41d4-a716-446655440004",
    "fields": {
      "study_mapping": "550e8400-e29b-41d4-a716-446655440003",
      "orthanc_instance_id": "instance-uuid-001",
      "annotation_uid": "ANN_001",
      "annotator_id": "PATHOLOGIST_001",
      "annotation_date": "2025-02-20",
      "type": "SEGMENTATION",
      "label": "left_upper_lobe_nodule",
      "annotation_data": null,
      "annotation_file": "annotations/seg_001.nii.gz"
    }
  }
]
```

---

## 3. Example API Requests & Responses

### 3.1 Upload Request

```bash
curl -X POST http://localhost:8000/api/v1/uploads/ \
  -H "Authorization: Bearer test-token-abc123" \
  -F "tar_file=@upload.tar" \
  -F "uploader_id=UPLOADER_001"
```

### 3.2 Upload Response (202 Accepted)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440002",
  "status": "PENDING",
  "submitted_at": "2025-02-15T10:05:00Z",
  "completed_at": null,
  "image_count": {
    "submitted": 3,
    "successful": 0
  },
  "orthanc_study_ids": [],
  "errors": []
}
```

### 3.3 Job Status Request (Polling)

```bash
curl -H "Authorization: Bearer test-token-abc123" \
  http://localhost:8000/api/v1/uploads/550e8400-e29b-41d4-a716-446655440002/
```

### 3.4 Job Status Response (COMPLETE)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440002",
  "status": "COMPLETE",
  "submitted_at": "2025-02-15T10:05:00Z",
  "completed_at": "2025-02-15T10:15:00Z",
  "image_count": {
    "submitted": 3,
    "successful": 3
  },
  "orthanc_study_ids": [
    "a1b2c3d4-e5f6-47a8-9012-345678901234"
  ],
  "errors": []
}
```

### 3.5 Partial Success Response (PARTIAL)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440005",
  "status": "PARTIAL",
  "submitted_at": "2025-02-15T11:00:00Z",
  "completed_at": "2025-02-15T11:05:00Z",
  "image_count": {
    "submitted": 3,
    "successful": 2
  },
  "orthanc_study_ids": [
    "a1b2c3d4-e5f6-47a8-9012-345678901234"
  ],
  "errors": [
    {
      "filename": "images/ct_002.dcm",
      "code": "DICOM_PARSE_ERROR",
      "message": "Invalid DICOM file: missing SOP Class UID"
    }
  ]
}
```

### 3.6 List Studies Request

```bash
curl -H "Authorization: Bearer test-token-abc123" \
  http://localhost:8000/api/v1/studies/
```

### 3.7 List Studies Response

```json
{
  "count": 1,
  "results": [
    {
      "pseudo_study_uid": "STUDY_2025_0001",
      "orthanc_study_id": "a1b2c3d4-e5f6-47a8-9012-345678901234",
      "pseudo_id": "PAT_2025_0001",
      "acquisition_date": "2025-02-15",
      "clinical_indication": "Suspected lung nodule follow-up",
      "pathology_labels": ["nodule", "ground_glass"],
      "source_institution": "Hospital ABC"
    }
  ]
}
```

### 3.8 Get Study & Proxy QIDO-RS

```bash
curl -H "Authorization: Bearer test-token-abc123" \
  http://localhost:8000/api/v1/studies/STUDY_2025_0001/
```

### 3.9 Study Detail Response (with proxied Orthanc metadata)

```json
{
  "pseudo_study_uid": "STUDY_2025_0001",
  "orthanc_study_id": "a1b2c3d4-e5f6-47a8-9012-345678901234",
  "pseudo_id": "PAT_2025_0001",
  "acquisition_date": "2025-02-15",
  "clinical_indication": "Suspected lung nodule follow-up",
  "pathology_labels": ["nodule", "ground_glass"],
  "cohort_tag": "lung_cancer_screening",
  "source_institution": "Hospital ABC",
  "notes": "High-resolution CT chest with 1mm slices",
  "annotations": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440004",
      "annotation_uid": "ANN_001",
      "type": "SEGMENTATION",
      "label": "left_upper_lobe_nodule",
      "annotator_id": "PATHOLOGIST_001",
      "annotation_date": "2025-02-20"
    }
  ],
  "orthanc_qido": {
    "00081110": {
      "vr": "DS",
      "Value": ["1"]
    },
    "00081190": {
      "vr": "UR",
      "Value": ["http://orthanc:8042/dicom-web/studies/a1b2c3d4-e5f6-47a8-9012-345678901234"]
    },
    "00200010": {
      "vr": "SH",
      "Value": ["STUDY_2025_0001"]
    }
  }
}
```

---

## 4. Test Tar Archive Structure

```
upload.tar
├── manifest.json                 (as shown in section 1)
├── images/
│   ├── ct_001.dcm               (valid DICOM)
│   ├── ct_002.dcm               (valid DICOM)
│   └── ct_003.dcm               (valid DICOM)
└── annotations/
    └── seg_001.nii.gz           (optional segmentation mask)
```

---

## 5. Error Test Cases

### 5.1 Invalid Manifest (missing required field)

```json
{
  "manifest_version": "1.0",
  "patient": {
    "pseudo_id": "PAT_2025_0002"
    // Missing: sex, age_at_first_acquisition
  },
  "study": {}
}
```

**Expected Error:**
```json
{
  "status": "FAILED",
  "errors": [
    {
      "code": "VALIDATION_ERROR",
      "message": "study.acquisition_date is required"
    }
  ]
}
```

### 5.2 Invalid pseudo_id (doesn't match pattern)

```json
{
  "patient": {
    "pseudo_id": "INVALID123@#$"  // Contains invalid characters
  }
}
```

**Expected Error:**
```json
{
  "code": "VALIDATION_ERROR",
  "message": "patient.pseudo_id must match pattern [A-Za-z0-9_-]{8,64}"
}
```

### 5.3 Checksum Mismatch

Manifest declares:
```json
{
  "filename": "images/ct_001.dcm",
  "checksum_sha256": "00000000000000000000000000000000"
}
```

But file content SHA-256 is actually: `a1b2c3d4e5f6...`

**Expected Error:**
```json
{
  "status": "FAILED",
  "errors": [
    {
      "filename": "images/ct_001.dcm",
      "code": "CHECKSUM_MISMATCH",
      "message": "SHA-256 mismatch: expected 00000000..., got a1b2c3d4..."
    }
  ]
}
```

### 5.4 Path Traversal Attack

```json
{
  "filename": "../../etc/passwd"
}
```

**Expected Error:**
```json
{
  "code": "SECURITY_ERROR",
  "message": "Path traversal detected in filename: ../../etc/passwd"
}
```

### 5.5 Missing File

Manifest references:
```json
{
  "filename": "images/nonexistent.dcm"
}
```

**Expected Error:**
```json
{
  "filename": "images/nonexistent.dcm",
  "code": "FILE_NOT_FOUND",
  "message": "File referenced in manifest does not exist in archive"
}
```

---

## 6. Valid Test Cases

### 6.1 Minimal Valid Manifest (all required fields only)

```json
{
  "manifest_version": "1.0",
  "patient": {
    "pseudo_id": "PAT_2025_0003"
  },
  "study": {
    "pseudo_study_uid": "STUDY_2025_0003",
    "acquisition_date": "2025-02-15"
  },
  "images": [
    {
      "filename": "images/ct_001.dcm",
      "checksum_sha256": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    }
  ]
}
```

### 6.2 Large Study (edge case: max images per upload)

With `MAX_IMAGES_PER_UPLOAD=10000`, a manifest with exactly 10,000 images should:
- Pass validation
- Process all images successfully
- Return `image_count.successful: 10000`

### 6.3 Multiple Studies from Same Uploader

Same `uploader_id`, different `pseudo_study_uid` values across multiple uploads:
- Each should create separate `UploadJob`
- Each should map to separate `StudyMapping`
- `GET /api/v1/studies/` should return all studies for that uploader

---

## 7. Orthanc STOW-RS Responses

### 7.1 Success (201 Created)

```http
HTTP/1.1 201 Created
Content-Type: application/json

{
  "00081150": {
    "vr": "UI",
    "Value": ["1.2.840.10008.5.1.4.1.1.2"]
  },
  "00081155": {
    "vr": "UI",
    "Value": ["1.2.840.113619.2.55.3.481507977.697"]
  },
  "00080018": {
    "vr": "UI",
    "Value": ["1.2.840.113619.2.55.3.481507977.697.123456"]
  }
}
```

**Mapped to Django:**
- StudyInstanceUID → `orthanc_study_id`
- SeriesInstanceUID → part of Orthanc series hierarchy
- SOPInstanceUID → `orthanc_instance_id` in `Annotation`

### 7.2 Failure (400 Bad Request)

```http
HTTP/1.1 400 Bad Request
Content-Type: application/json

{
  "HttpStatus": 400,
  "HttpReason": "Bad Request",
  "Message": "Orthanc: Bad request"
}
```

**Django Response:**
```json
{
  "status": "PARTIAL",
  "errors": [
    {
      "filename": "images/ct_002.dcm",
      "code": "ORTHANC_PUSH_FAILED",
      "message": "HTTP 400: Orthanc: Bad request"
    }
  ]
}
```

---

## 8. Bearer Token Examples

```
Authorization: Bearer test-token-standard-user-abc123
Authorization: Bearer test-token-admin-xyz789
Authorization: Bearer expired-token-1970 (should return 401 Unauthorized)
```

---

## 9. Test Data Generators (Python)

### Create minimal valid tar for testing

```python
import tarfile
import json
import io
import hashlib

def create_test_tar(filename="upload.tar"):
    """Create a minimal test tar with manifest and dummy DICOM."""
    
    manifest = {
        "manifest_version": "1.0",
        "patient": {"pseudo_id": "PAT_TEST_0001"},
        "study": {
            "pseudo_study_uid": "STUDY_TEST_0001",
            "acquisition_date": "2025-02-15"
        },
        "images": [
            {
                "filename": "images/test_001.dcm",
                "checksum_sha256": hashlib.sha256(b"dummy_dicom_content").hexdigest()
            }
        ]
    }
    
    manifest_json = json.dumps(manifest, indent=2).encode('utf-8')
    dicom_content = b"dummy_dicom_content"
    
    with tarfile.open(filename, "w") as tar:
        # Add manifest.json
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_json)
        tar.addfile(info, io.BytesIO(manifest_json))
        
        # Add dummy DICOM
        info = tarfile.TarInfo(name="images/test_001.dcm")
        info.size = len(dicom_content)
        tar.addfile(info, io.BytesIO(dicom_content))
    
    print(f"Created test tar: {filename}")

if __name__ == "__main__":
    create_test_tar()
```

---

## 10. Token Management

### Create test token (Django shell)

```python
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token

user = User.objects.create_user(username='test-uploader', password='testpass123')
token, created = Token.objects.get_or_create(user=user)
print(f"Token: {token.key}")
```

### Revoke/delete token

```python
Token.objects.filter(user__username='test-uploader').delete()
```

