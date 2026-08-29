"""
Celery tasks for the uploads app.
Handles validation and ingestion of pre-anonymized DICOM images from uploaded tar files.
"""

import hashlib
import json
import logging
import os
import shutil
import tarfile
import tempfile
import zipfile
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pydicom
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import UploadJob, Patient, StudyMapping, CTExamination, Annotation, AuditLog
from .manifest_schema import validate_manifest
from .orthanc_client import get_client, OrthancPushError
from .gdpr_validator import validate_gdpr_anonymization
from .gdpr_anonymizer import GDPRAnonymizationPipeline, PseudoIDGenerator
from .pseudo_id_validator import (
    PseudoIDUniquenessValidator,
    PseudoIDCollisionError,
    _is_valid_pseudo_id_format,
)
from .file_manager import get_processed_data_job_dir
from .repository_study_id import generate_repository_study_id_from_codes

# Configure logging
logger = logging.getLogger(__name__)


def compute_sha256(file_path):
    """Compute SHA-256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def validate_tar_safety(tar_path):
    """
    Perform safety checks on a tar file before extraction.
    
    Raises ValueError if any check fails.
    """
    with tarfile.open(tar_path, "r:*") as tar:
        members = tar.getmembers()
        
        # Check member count
        if len(members) > settings.MAX_IMAGES_PER_UPLOAD:
            raise ValueError(
                f"Tar contains {len(members)} members, exceeds limit of {settings.MAX_IMAGES_PER_UPLOAD}"
            )
        
        total_size = 0
        max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        
        for member in members:
            # Check for path traversal
            if ".." in member.name or member.name.startswith("/"):
                raise ValueError(f"Invalid path in tar: {member.name}")
            
            # Check for symlinks
            if member.issym() or member.islnk():
                raise ValueError(f"Symlinks not allowed: {member.name}")
            
            # Check size
            if member.isfile():
                total_size += member.size
                if total_size > max_size:
                    raise ValueError(
                        f"Total uncompressed size {total_size} exceeds limit of {max_size}"
                    )


def is_zip_archive(path) -> bool:
    """Return True if *path* is a valid ZIP file, based on content (magic
    bytes), not the filename extension — chunked uploads are always
    assembled under a `.tar` name regardless of the original archive type."""
    try:
        return zipfile.is_zipfile(path)
    except Exception:
        return False


def validate_zip_safety(zip_path):
    """
    Perform safety checks on a ZIP file before extraction (mirrors
    validate_tar_safety for the tar case).

    Raises ValueError if any check fails.
    """
    with zipfile.ZipFile(zip_path, "r") as z:
        members = z.infolist()

        if len(members) > settings.MAX_IMAGES_PER_UPLOAD:
            raise ValueError(
                f"ZIP contains {len(members)} members, exceeds limit of {settings.MAX_IMAGES_PER_UPLOAD}"
            )

        total_size = 0
        max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

        for member in members:
            if ".." in member.filename or member.filename.startswith("/"):
                raise ValueError(f"Invalid path in ZIP: {member.filename}")
            # ZipInfo has no direct symlink flag; the external_attr high bits
            # encode Unix file mode when the ZIP was created on Unix — a
            # symlink has S_IFLNK (0o120000) in the top 16 bits.
            unix_mode = member.external_attr >> 16
            if unix_mode and (unix_mode & 0o170000) == 0o120000:
                raise ValueError(f"Symlinks not allowed: {member.filename}")

            if not member.is_dir():
                total_size += member.file_size
                if total_size > max_size:
                    raise ValueError(
                        f"Total uncompressed size {total_size} exceeds limit of {max_size}"
                    )


# ---------------------------------------------------------------------------
# v2 (server-assigned batch) pipeline
#
# Produced by the create_rhythm_server_assigned_manifest_gui[_with_uid].py
# partner tools: one manifest per batch, each item describing one ZIP archive
# containing one already-anonymized CT DICOM studyset. Unlike the v1 pipeline
# (which computes and INSERTS an organ-specific pseudo PatientID into every
# DICOM file), v2 archives are expected to already carry a valid, anonymized
# PatientID — the server only extracts and validates it, it never rewrites it.
# ---------------------------------------------------------------------------

# Maps a v2 manifest item's contrast_code to CTExamination/StudyMapping's
# boolean contrast_used field.
_CONTRAST_CODE_USED = {
    "NC": False,
    "CE": True,
    "MIX": True,
}

# Best-effort mapping from the free-text image_quality values partner tools
# may send to CTExamination.IMAGE_QUALITY_CHOICES. Falls back to "MODERATE"
# (a safe middle default) for anything unrecognized, with a warning logged.
_IMAGE_QUALITY_ALIASES = {
    "EXCELLENT": "EXCELLENT",
    "GOOD": "GOOD",
    "ACCEPTABLE": "MODERATE",
    "MODERATE": "MODERATE",
    "FAIR": "MODERATE",
    "POOR": "POOR",
    "UNACCEPTABLE": "POOR",
}


def _normalize_image_quality(raw_value: str) -> str:
    key = (raw_value or "").strip().upper()
    mapped = _IMAGE_QUALITY_ALIASES.get(key)
    if mapped:
        return mapped
    logger.warning(f"Unrecognized image_quality value '{raw_value}', defaulting to MODERATE")
    return "MODERATE"


def _patient_group_code_to_protocol_fields(group_code: str) -> tuple[str, str]:
    """Derive (protocol_type, examination_group) from a coded patient group
    like 'PH-G4' — the inverse of repository_study_id.get_patient_group_code.
    Best-effort only; used for display on the resulting CTExamination row,
    not for repository_study_id generation (which uses the code directly)."""
    group_code = (group_code or "").upper()
    if group_code.startswith("PH-G"):
        return "PEDIATRIC_HEAD", f"Group {group_code[4:]}"
    if group_code.startswith("PB-G"):
        return "PEDIATRIC_BODY", f"Group {group_code[4:]}"
    if group_code.startswith("YA-G"):
        return "YOUNG_ADULT", f"Group {group_code[4:]}"
    return "", group_code


def _extract_dicom_uids(dicom_path: str) -> dict | None:
    """Read a DICOM file's identifying UIDs without modifying it.

    Returns None if the file cannot be read as DICOM or has no
    StudyInstanceUID (i.e. it's not a usable image for this pipeline).
    """
    try:
        ds = pydicom.dcmread(dicom_path, stop_before_pixels=True, force=False)
    except Exception:
        return None

    study_uid = str(getattr(ds, "StudyInstanceUID", "") or "").strip()
    if not study_uid:
        return None

    return {
        "patient_id": str(getattr(ds, "PatientID", "") or "").strip(),
        "study_uid": study_uid,
        "series_uid": str(getattr(ds, "SeriesInstanceUID", "") or "").strip(),
        "sop_uid": str(getattr(ds, "SOPInstanceUID", "") or "").strip(),
        "study_date": str(getattr(ds, "StudyDate", "") or "").strip(),
    }


def _parse_dicom_date(value: str):
    """Parse a DICOM DA value (YYYYMMDD) into a date, or None."""
    if not value or len(value) != 8:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _fail_job(job: "UploadJob", message: str, code: str = "pipeline_error") -> None:
    logger.error(message)
    job.status = "FAILED"
    job.error_report = [{"field": "-", "code": code, "message": message}]
    job.completed_at = timezone.now()
    job.save()


def process_v2_batch_item(job: "UploadJob", archive_path: str, extract_dir: str) -> None:
    """
    Process one item of a v2 (server-assigned batch) manifest: one ZIP
    archive containing one already-anonymized CT DICOM studyset.

    job.manifest_raw holds the manifest item (site_code,
    clinical_indication_code, contrast_code, patient_group_code,
    patient_weight_kg, patient_age_years, ctdivol_mgy, dlp_mgy_cm,
    image_quality, protocol_name, and optionally repository_study_id_override
    when this job was created by Manual Exam Entry reusing an ID it already
    assigned synchronously).

    Mutates job in place (status/error_report/completed_at), mirroring the
    v1 pipeline's error-handling style. Does not raise on validation
    failures — only on truly unexpected errors, which propagate to the
    caller's retry logic.
    """
    item = job.manifest_raw or {}

    if is_zip_archive(archive_path):
        try:
            validate_zip_safety(archive_path)
        except ValueError as e:
            return _fail_job(job, f"ZIP validation failed: {e}")
        try:
            with zipfile.ZipFile(archive_path, "r") as z:
                z.extractall(path=extract_dir)
        except Exception as e:
            return _fail_job(job, f"Failed to extract ZIP: {e}")
    else:
        try:
            validate_tar_safety(archive_path)
        except ValueError as e:
            return _fail_job(job, f"Tar validation failed: {e}")
        try:
            with tarfile.open(archive_path, "r:*") as tar:
                tar.extractall(path=extract_dir)
        except Exception as e:
            return _fail_job(job, f"Failed to extract archive: {e}")

    # Walk every extracted file, keep the ones readable as DICOM with a
    # StudyInstanceUID. Non-DICOM files (readme, csv, etc.) are silently
    # skipped, matching the partner tool's own inspection logic.
    dicom_files = []
    study_uids = set()
    patient_ids = set()
    study_date_raw = ""
    for root, _dirs, files in os.walk(extract_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            uids = _extract_dicom_uids(fpath)
            if uids is None:
                continue
            dicom_files.append(fpath)
            study_uids.add(uids["study_uid"])
            if uids["patient_id"]:
                patient_ids.add(uids["patient_id"])
            if uids["study_date"] and not study_date_raw:
                study_date_raw = uids["study_date"]

    if not dicom_files:
        return _fail_job(
            job,
            f"No readable DICOM files with StudyInstanceUID found in archive: {item.get('filename', '-')}",
            code="no_dicom_files",
        )
    if len(study_uids) > 1:
        return _fail_job(
            job,
            f"Archive contains multiple StudyInstanceUID values, expected exactly one studyset per archive: {sorted(study_uids)}",
            code="multiple_study_uids",
        )
    if len(patient_ids) > 1:
        return _fail_job(
            job,
            f"Archive contains multiple DICOM PatientID values under one study: {sorted(patient_ids)}",
            code="multiple_patient_ids",
        )
    if not patient_ids:
        return _fail_job(
            job,
            "No DICOM PatientID found. Archives must already carry an anonymized pseudo patient ID.",
            code="missing_patient_id",
        )

    study_uid = study_uids.pop()
    pseudo_id = patient_ids.pop()

    if not _is_valid_pseudo_id_format(pseudo_id):
        return _fail_job(
            job,
            f"DICOM PatientID '{pseudo_id}' does not match the required pseudo-ID format "
            "(8-64 alphanumeric characters, hyphens, underscores).",
            code="invalid_pseudo_id_format",
        )

    # Get or create the Patient record, enforcing global pseudo-ID uniqueness.
    patient, created, patient_error = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
        pseudo_id=pseudo_id,
        age_at_acquisition=item.get("patient_age_years"),
    )
    if patient_error:
        return _fail_job(job, f"Failed to get or create patient: {patient_error}")
    logger.info(f"Patient {'created' if created else 'reused'} with pseudo_id: {patient.pseudo_id}")

    orthanc = get_client()

    error_report = []
    images_processed = 0
    images_failed = 0

    for image_path in dicom_files:
        try:
            with transaction.atomic():
                is_valid, validation_errors = validate_gdpr_anonymization(image_path, pseudo_id=pseudo_id)
                if not is_valid:
                    for error in validation_errors:
                        logger.warning(
                            f"GDPR validation failed for {os.path.basename(image_path)}: "
                            f"{error.get('code')} - {error.get('message')}"
                        )
                    error_report.append({
                        "filename": os.path.basename(image_path),
                        "code": "gdpr_validation_failed",
                        "message": "DICOM file is not anonymized according to GDPR-strict rules",
                        "validation_errors": validation_errors,
                    })
                    images_failed += 1
                    continue

                try:
                    with open(image_path, "rb") as f:
                        dicom_bytes = f.read()
                except Exception as e:
                    error_report.append({
                        "filename": os.path.basename(image_path),
                        "code": "file_read_error",
                        "message": f"Failed to read DICOM file: {e}",
                    })
                    images_failed += 1
                    continue

                try:
                    orthanc.push_dicom_file(dicom_bytes)
                    images_processed += 1
                except OrthancPushError as e:
                    error_report.append({
                        "filename": os.path.basename(image_path),
                        "code": "orthanc_push_error",
                        "message": f"Failed to push to Orthanc: {e.message}",
                    })
                    images_failed += 1
        except Exception as e:
            images_failed += 1
            error_msg = f"Error processing {os.path.basename(image_path)}: {e}"
            logger.error(error_msg, exc_info=True)
            error_report.append({"filename": os.path.basename(image_path), "code": "processing_error", "message": error_msg})

    if images_processed == 0:
        job.error_report = error_report
        job.status = "FAILED"
        job.completed_at = timezone.now()
        job.save()
        return

    # Upsert StudyMapping for this study.
    acquisition_date = _parse_dicom_date(study_date_raw) or date.today()
    study_mapping, _ = StudyMapping.objects.update_or_create(
        pseudo_study_uid=study_uid,
        defaults={
            "patient": patient,
            "upload_job": job,
            "site_code": item.get("site_code", job.site_code),
            "acquisition_date": acquisition_date,
            "clinical_indication": item.get("clinical_indication_code", ""),
            "contrast_used": _CONTRAST_CODE_USED.get(item.get("contrast_code"), False),
            "notes": f"protocol_name: {item.get('protocol_name', '')}".strip(),
        },
    )

    # Assign (or reuse) the Repository Study ID.
    repository_study_id = item.get("repository_study_id_override")
    if not repository_study_id:
        repository_study_id = generate_repository_study_id_from_codes(
            site_code=item.get("site_code", ""),
            indication_code=item.get("clinical_indication_code", "OTHER"),
            contrast_code=item.get("contrast_code", "UNK"),
            group_code=item.get("patient_group_code", "UNK"),
        )

    protocol_type, examination_group = _patient_group_code_to_protocol_fields(
        item.get("patient_group_code", "")
    )

    CTExamination.objects.create(
        rhythm_pseudo_id=repository_study_id,
        anatomical_region=item.get("anatomical_region", ""),
        clinical_indication=item.get("clinical_indication_code", ""),
        contrast=item.get("contrast_code", ""),
        protocol_type=protocol_type,
        examination_group=examination_group,
        patient_weight=item.get("patient_weight_kg"),
        patient_age=item.get("patient_age_years"),
        number_of_phases=1,
        ctdi_vol_per_phase=[item["ctdivol_mgy"]] if item.get("ctdivol_mgy") is not None else [],
        dlp_per_phase=[item["dlp_mgy_cm"]] if item.get("dlp_mgy_cm") is not None else [],
        image_quality=_normalize_image_quality(item.get("image_quality", "")),
        created_by=job.uploader_id,
        site_code=item.get("site_code", job.site_code),
        upload_job=job,
    )

    job.error_report = error_report if error_report else None
    job.completed_at = timezone.now()
    job.status = "COMPLETE" if images_failed == 0 else "PARTIAL"
    job.save()

    logger.info(
        f"Completed v2 batch item for job {job.id}: status={job.status}, "
        f"repository_study_id={repository_study_id}, processed={images_processed}, failed={images_failed}"
    )


def extract_dicom_metadata(file_path):
    """
    Extract relevant DICOM metadata using pydicom.
    
    Returns a dict of DICOM tag values (PHI tags will be stripped later).
    """
    if not settings.DICOM_ENRICHMENT_ENABLED:
        return {}
    
    try:
        ds = pydicom.dcmread(file_path, stop_before_pixels=True)
        metadata = {}
        
        # Extract specific tags
        tag_mapping = {
            "BodyPartExamined": "body_part",
            "Laterality": "laterality",
            "SliceThickness": "slice_thickness_mm",
            "PixelSpacing": "pixel_spacing_mm",
            "Rows": "image_rows",
            "Columns": "image_cols",
            "Manufacturer": "scanner_manufacturer",
            "ManufacturerModelName": "scanner_model",
            "KVP": "kvp",
        }
        
        for dicom_tag, key in tag_mapping.items():
            if hasattr(ds, dicom_tag):
                value = getattr(ds, dicom_tag)
                if value is not None:
                    metadata[key] = str(value)
        
        # Derive view plane from ImageOrientationPatient if present
        if hasattr(ds, "ImageOrientationPatient"):
            try:
                orientation = ds.ImageOrientationPatient
                if len(orientation) == 6:
                    row_cosines = orientation[:3]
                    col_cosines = orientation[3:]
                    # Cross product to get normal
                    normal = [
                        row_cosines[1] * col_cosines[2] - row_cosines[2] * col_cosines[1],
                        row_cosines[2] * col_cosines[0] - row_cosines[0] * col_cosines[2],
                        row_cosines[0] * col_cosines[1] - row_cosines[1] * col_cosines[0],
                    ]
                    # Determine plane based on which component is largest
                    abs_normal = [abs(n) for n in normal]
                    max_idx = abs_normal.index(max(abs_normal))
                    planes = ["SAGITTAL", "CORONAL", "AXIAL"]
                    metadata["view_plane"] = planes[max_idx]
            except Exception:
                pass
        
        return metadata
    except Exception as e:
        logger.warning(f"Failed to extract DICOM metadata from {file_path}: {e}")
        return {}


def strip_phi_tags(file_path):
    """
    DEPRECATED: Do not use this function. 
    DICOM files must be pre-anonymized by the client before upload.
    This function is kept for backward compatibility but will raise an error.
    """
    raise NotImplementedError(
        "Strip PHI is not supported. DICOM files must be pre-anonymized before upload. "
        "Use gdpr_validator.validate_gdpr_anonymization() to validate anonymization instead."
    )


@shared_task(bind=True, max_retries=3)
def process_upload_job(self, job_id: str):
    """
    Process an upload job: extract tar, validate manifest and GDPR anonymization, and ingest DICOM images.
    
    The system validates that uploaded DICOM files are already anonymized according to GDPR-strict.json
    rules. Files that pass validation are pushed to Orthanc as-is (no modifications).
    
    Args:
        job_id: UUID of the UploadJob to process
    
    Raises:
        Exception: On unexpected errors (for Celery retry)
    """
    extract_dir = None
    try:
        # 1. Load UploadJob and set status to PROCESSING
        try:
            job = UploadJob.objects.get(id=job_id)
        except UploadJob.DoesNotExist:
            logger.error(f"UploadJob {job_id} not found — task abandoned")
            raise
        
        job.status = "PROCESSING"
        job.save()
        
        logger.info(f"Processing upload job {job_id}")
        
        # 2. Validate tar exists at specified path
        tar_path = job.tar_temp_path
        if not tar_path or not os.path.exists(tar_path):
            error_msg = f"Tar file not found at {tar_path}"
            logger.error(error_msg)
            job.status = "FAILED"
            job.error_report = [{"field": "-", "code": "pipeline_error", "message": error_msg}]
            job.completed_at = timezone.now()
            job.save()
            return
        
        # 2b. v2 (server-assigned batch item) jobs carry their item metadata
        # directly on manifest_raw instead of an embedded manifest.json, and
        # may be ZIP rather than tar archives — hand off to the dedicated
        # v2 pipeline and skip the v1-specific steps below entirely.
        if isinstance(job.manifest_raw, dict) and "clinical_indication_code" in job.manifest_raw:
            processed_job_dir = get_processed_data_job_dir(job_id)
            extract_dir = str(processed_job_dir)
            process_v2_batch_item(job, tar_path, extract_dir)
            return

        # 3. Safety-check the tar
        try:
            validate_tar_safety(tar_path)
        except ValueError as e:
            error_msg = f"Tar validation failed: {str(e)}"
            logger.error(error_msg)
            job.status = "FAILED"
            job.error_report = [{"field": "-", "code": "pipeline_error", "message": error_msg}]
            job.completed_at = timezone.now()
            job.save()
            return

        # 4. Create processed_data/{job_id} directory and extract tar there
        processed_job_dir = get_processed_data_job_dir(job_id)
        extract_dir = str(processed_job_dir)

        try:
            with tarfile.open(tar_path, "r:*") as tar:
                tar.extractall(path=extract_dir)
        except Exception as e:
            error_msg = f"Failed to extract tar: {str(e)}"
            logger.error(error_msg)
            job.status = "FAILED"
            job.error_report = [{"field": "-", "code": "pipeline_error", "message": error_msg}]
            job.completed_at = timezone.now()
            job.save()
            return
        
        manifest_path = os.path.join(extract_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            error_msg = "manifest.json not found at archive root"
            logger.error(error_msg)
            job.status = "FAILED"
            job.error_report = [{"field": "-", "code": "pipeline_error", "message": error_msg}]
            job.completed_at = timezone.now()
            job.save()
            return
        
        # 5. Parse and validate manifest
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
        except json.JSONDecodeError as e:
            error_msg = f"Failed to parse manifest.json: {str(e)}"
            logger.error(error_msg)
            job.status = "FAILED"
            job.error_report = [{"field": "-", "code": "json_parse_error", "message": error_msg}]
            job.completed_at = timezone.now()
            job.save()
            return
        
        # Store raw manifest for audit
        job.manifest_raw = manifest
        job.save()
        
        validation_errors = validate_manifest(manifest)
        if validation_errors:
            error_msg = "Manifest validation failed"
            logger.error(f"{error_msg}: {validation_errors}")
            job.status = "FAILED"
            job.error_report = validation_errors
            job.completed_at = timezone.now()
            job.save()
            return
        
        # 5b. Validate pseudo patient ID uniqueness
        # Ensure this pseudo_id is unique across the system and not already assigned to a different patient
        patient_data = manifest.get("patient", {})
        base_pseudo_id = patient_data.get("pseudo_id")
        
        logger.info(f"Validating pseudo ID uniqueness for: {base_pseudo_id}")
        
        is_unique, uniqueness_errors = PseudoIDUniquenessValidator.validate_manifest_pseudo_ids(
            manifest,
            allow_existing=True  # Allow re-uploads of same patient
        )
        
        if not is_unique:
            error_msg = "Pseudo patient ID validation failed"
            logger.error(f"{error_msg}: {uniqueness_errors}")
            job.status = "FAILED"
            job.error_report = uniqueness_errors
            job.completed_at = timezone.now()
            job.save()
            return
        
        # Log the pseudo ID for audit trail
        PseudoIDUniquenessValidator.log_pseudo_id_tracking(base_pseudo_id, str(job.id))

        # 5c. Pre-flight integrity check: verify every image file exists and
        # matches its manifest checksum BEFORE anonymization touches it.
        # This must run first — the GDPR anonymization step below rewrites
        # each DICOM file in place (inserting the organ-specific pseudo
        # PatientID), so checksumming afterward would compare against bytes
        # the server itself just changed and could never match the
        # client-supplied checksum of the original upload. Only images that
        # pass this check are anonymized, GDPR-validated, and pushed;
        # images that fail are reported and skipped entirely, without ever
        # being modified on disk.
        checksum_errors = []
        verified_image_entries = []
        for pre_idx, pre_image_entry in enumerate(manifest.get("images", [])):
            pre_filename = pre_image_entry.get("filename")
            pre_path = os.path.join(extract_dir, pre_filename)

            if not os.path.exists(pre_path):
                error_msg = f"Image file not found: {pre_filename}"
                logger.warning(error_msg)
                checksum_errors.append({
                    "image_index": pre_idx,
                    "filename": pre_filename,
                    "code": "file_not_found",
                    "message": error_msg,
                })
                continue

            actual_checksum = compute_sha256(pre_path)
            expected_checksum = pre_image_entry.get("checksum_sha256")

            if actual_checksum != expected_checksum:
                error_msg = (
                    f"Checksum mismatch: expected {expected_checksum}, "
                    f"got {actual_checksum}"
                )
                logger.warning(error_msg)
                checksum_errors.append({
                    "image_index": pre_idx,
                    "filename": pre_filename,
                    "code": "checksum_mismatch",
                    "message": error_msg,
                })
                continue

            verified_image_entries.append((pre_idx, pre_image_entry))

        verified_images_only = [entry for _, entry in verified_image_entries]

        # 6. Generate organ-specific pseudo patient IDs and insert into DICOM files
        # This happens after tar extraction but before GDPR validation, and
        # only for images that passed the integrity check above.
        patient_data = manifest.get("patient", {})
        base_pseudo_id = patient_data.get("pseudo_id")

        logger.info(f"Starting GDPR anonymization pipeline for job {job_id}")

        try:
            anonymization_pipeline = GDPRAnonymizationPipeline(
                manifest={**manifest, "images": verified_images_only},
                extract_dir=extract_dir,
                base_pseudo_id=base_pseudo_id
            )

            success, anonymization_errors = anonymization_pipeline.anonymize_and_insert_pseudo_ids()
            
            anonymization_report = anonymization_pipeline.get_report()
            logger.info(f"Anonymization report: {anonymization_report}")
            
            # Store anonymization report in job for audit trail
            job.anonymization_report = anonymization_report
            job.save()
            
            if not success and anonymization_errors:
                # Log all anonymization errors
                error_msg = "GDPR anonymization/pseudonymization failed"
                logger.error(f"{error_msg}: {anonymization_errors}")
                job.status = "FAILED"
                job.error_report = anonymization_errors
                job.completed_at = timezone.now()
                job.save()
                return
                
        except Exception as e:
            error_msg = f"Unexpected error in anonymization pipeline: {str(e)}"
            logger.error(error_msg, exc_info=True)
            job.status = "FAILED"
            job.error_report = [{"field": "-", "code": "pipeline_error", "message": error_msg}]
            job.completed_at = timezone.now()
            job.save()
            return
        
        # 7. Process each image that passed the pre-flight integrity check.
        error_report = list(checksum_errors)
        images_processed = 0
        images_failed = len(checksum_errors)
        
        patient_data = manifest.get("patient", {})
        study_data = manifest.get("study", {})
        
        orthanc = get_client()
        
        # Get or create Patient with uniqueness enforcement
        patient, patient_created, patient_error = PseudoIDUniquenessValidator.get_or_create_patient_with_pseudoid(
            pseudo_id=patient_data.get("pseudo_id"),
            sex=patient_data.get("sex"),
            age_at_acquisition=patient_data.get("age_at_acquisition"),
            cohort_tag=patient_data.get("cohort_tag"),
        )
        
        if patient_error:
            error_msg = f"Failed to get or create patient: {patient_error}"
            logger.error(error_msg)
            job.status = "FAILED"
            job.error_report = [{"field": "-", "code": "pipeline_error", "message": error_msg}]
            job.completed_at = timezone.now()
            job.save()
            return
        
        patient_action = "created" if patient_created else "reused"
        logger.info(f"Patient {patient_action} with pseudo_id: {patient.pseudo_id}")
        
        # Upsert StudyMapping once
        study_mapping, _ = StudyMapping.objects.update_or_create(
            pseudo_study_uid=study_data.get("study_uid"),
            defaults={
                "patient": patient,
                "upload_job": job,
                "site_code": job.site_code,
                "acquisition_date": study_data.get("acquisition_date"),
                "clinical_indication": study_data.get("clinical_indication", ""),
                "pathology_labels": study_data.get("pathology_labels", []),
                "contrast_used": study_data.get("contrast_used", False),
                "contrast_agent": study_data.get("contrast_agent"),
                "source_institution": manifest.get("source_institution"),
                "notes": study_data.get("notes", ""),
            },
        )
        
        for idx, image_entry in verified_image_entries:
            try:
                with transaction.atomic():
                    # File existence and checksum were already verified in
                    # the pre-flight pass above (step 5c), before this image
                    # was anonymized — re-checking here would compare against
                    # the now-rewritten file and always mismatch.
                    image_filename = image_entry.get("filename")
                    image_path = os.path.join(extract_dir, image_filename)

                    # c. Validate GDPR-strict anonymization compliance
                    # Use organ-specific pseudo ID that was inserted by anonymization pipeline
                    body_part = image_entry.get("body_part", "OTHER")
                    organ_image_index = list(
                        filter(lambda e: e.get("body_part") == body_part,
                               verified_images_only)
                    ).index(image_entry) + 1
                    
                    organ_specific_pseudo_id = PseudoIDGenerator.generate_organ_specific_pseudo_id(
                        base_pseudo_id,
                        body_part,
                        organ_image_index
                    )
                    
                    logger.debug(
                        f"Validating GDPR compliance for {image_filename} "
                        f"with pseudo ID {organ_specific_pseudo_id} (body_part={body_part})"
                    )
                    
                    is_valid, validation_errors = validate_gdpr_anonymization(
                        image_path,
                        organ_specific_pseudo_id
                    )
                    
                    if not is_valid:
                        # Detailed error logging
                        for error in validation_errors:
                            logger.warning(
                                f"GDPR validation failed for {image_filename}: "
                                f"{error.get('code')} - {error.get('message')}"
                            )
                        
                        error_report.append({
                            "image_index": idx,
                            "filename": image_filename,
                            "code": "gdpr_validation_failed",
                            "message": "DICOM file is not anonymized according to GDPR-strict rules",
                            "validation_errors": validation_errors,
                        })
                        images_failed += 1
                        continue
                    
                    # d. Read DICOM file for pushing (no modification, already anonymized with pseudo ID)
                    try:
                        with open(image_path, "rb") as f:
                            dicom_bytes = f.read()
                    except Exception as e:
                        error_msg = f"Failed to read DICOM file: {str(e)}"
                        logger.warning(error_msg)
                        error_report.append({
                            "image_index": idx,
                            "filename": image_filename,
                            "code": "file_read_error",
                            "message": error_msg,
                        })
                        images_failed += 1
                        continue
                    
                    # e. Push to Orthanc via STOW-RS
                    try:
                        push_result = orthanc.push_dicom_file(dicom_bytes)
                        orthanc_study_id = push_result.get('orthanc_study_id')
                        orthanc_instance_id = push_result.get('orthanc_instance_id')
                        
                        # Update StudyMapping with Orthanc study ID if not already set
                        if orthanc_study_id and not study_mapping.orthanc_study_id:
                            study_mapping.orthanc_study_id = orthanc_study_id
                            study_mapping.save()
                        
                        logger.info(f"Successfully pushed image {idx + 1} to Orthanc")
                        
                    except OrthancPushError as e:
                        error_msg = f"Failed to push to Orthanc: {e.message}"
                        logger.warning(error_msg)
                        error_report.append({
                            "image_index": idx,
                            "filename": image_filename,
                            "code": "orthanc_push_error",
                            "message": error_msg,
                        })
                        images_failed += 1
                        continue
                    
                    # f. Handle annotations
                    for anno_entry in image_entry.get("annotations", []):
                        try:
                            annotation_obj = Annotation.objects.create(
                                study_mapping=study_mapping,
                                orthanc_instance_id=orthanc_instance_id or "",
                                annotation_uid=anno_entry.get("annotation_uid", ""),
                                annotator_id=anno_entry.get("annotator_id", ""),
                                annotation_date=anno_entry.get("annotation_date"),
                                type=anno_entry.get("type", "LANDMARK"),
                                label=anno_entry.get("label", ""),
                                annotation_data=anno_entry.get("annotation_data"),
                            )
                            
                            # Handle annotation file if provided
                            file_ref = anno_entry.get("file_ref")
                            if file_ref:
                                anno_file_path = os.path.join(extract_dir, file_ref)
                                if os.path.exists(anno_file_path):
                                    try:
                                        with open(anno_file_path, "rb") as af:
                                            annotation_obj.annotation_file.save(
                                                os.path.basename(file_ref),
                                                af,
                                                save=True
                                            )
                                    except Exception as ae:
                                        logger.warning(
                                            f"Failed to save annotation file {file_ref}: {ae}"
                                        )
                        except Exception as ae:
                            logger.warning(f"Failed to create annotation: {ae}")
                    
                    images_processed += 1
                    logger.info(f"Processed image {idx + 1}/{len(manifest.get('images', []))} successfully (of {len(verified_images_only)} that passed integrity check)")
            
            except Exception as e:
                images_failed += 1
                error_msg = f"Error processing image {image_entry.get('filename')}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                error_report.append({
                    "image_index": idx,
                    "filename": image_entry.get("filename"),
                    "code": "processing_error",
                    "message": error_msg,
                })
        
        # 7. Update job status and completed_at
        job.error_report = error_report if error_report else None
        job.completed_at = timezone.now()
        
        if images_failed == 0:
            job.status = "COMPLETE"
        elif images_processed == 0:
            job.status = "FAILED"
        else:
            job.status = "PARTIAL"
        
        job.save()
        
        logger.info(
            f"Completed upload job {job_id}: "
            f"status={job.status}, processed={images_processed}, failed={images_failed}"
        )
    
    except Exception as e:
        # 8. Handle unexpected exceptions with retry
        logger.error(f"Unexpected error in process_upload_job({job_id}): {str(e)}", exc_info=True)
        
        try:
            job = UploadJob.objects.get(id=job_id)
            job.status = "FAILED"
            job.error_report = [{"code": "task_error", "message": f"Task error: {str(e)}"}]
            job.completed_at = timezone.now()
            job.save()
        except UploadJob.DoesNotExist:
            logger.error(f"Could not update job status for {job_id}")
        
        # Retry with exponential backoff
        countdown = 60 * (2 ** self.request.retries)
        logger.info(f"Retrying job {job_id} in {countdown} seconds")
        raise self.retry(exc=e, countdown=countdown)
    
    finally:
        # 8. Clean up on failure, preserve on success
        if extract_dir and os.path.exists(extract_dir):
            # Only clean up temp extraction directory on failure
            # On success, keep the extracted data in processed_data/{job_id}/
            try:
                job = UploadJob.objects.get(id=job_id)
                if job.status == "FAILED" or job.status == "PROCESSING":
                    # Delete the extracted contents on failure
                    shutil.rmtree(extract_dir)
                    logger.debug(f"Cleaned up temp directory {extract_dir} due to failed processing")
                else:
                    # On success, keep the directory but log it
                    logger.info(f"Preserving processed data in {extract_dir}")
            except UploadJob.DoesNotExist:
                # If job doesn't exist, clean up
                shutil.rmtree(extract_dir)
                logger.debug(f"Cleaned up temp directory {extract_dir} due to missing job")
            except Exception as e:
                logger.warning(f"Error during cleanup decision for {extract_dir}: {e}")
