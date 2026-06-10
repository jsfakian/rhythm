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
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pydicom
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import UploadJob, Patient, StudyMapping, Annotation, AuditLog
from .manifest_schema import validate_manifest
from .orthanc_client import get_client, OrthancPushError
from .gdpr_validator import validate_gdpr_anonymization
from .gdpr_anonymizer import GDPRAnonymizationPipeline, PseudoIDGenerator
from .pseudo_id_validator import PseudoIDUniquenessValidator, PseudoIDCollisionError
from .file_manager import get_processed_data_job_dir

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
        
        # 6. Generate organ-specific pseudo patient IDs and insert into DICOM files
        # This happens after tar extraction but before GDPR validation
        patient_data = manifest.get("patient", {})
        base_pseudo_id = patient_data.get("pseudo_id")
        
        logger.info(f"Starting GDPR anonymization pipeline for job {job_id}")
        
        try:
            anonymization_pipeline = GDPRAnonymizationPipeline(
                manifest=manifest,
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
        
        # 7. Process each image
        error_report = []
        images_processed = 0
        images_failed = 0
        
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
                "acquisition_date": study_data.get("acquisition_date"),
                "clinical_indication": study_data.get("clinical_indication", ""),
                "pathology_labels": study_data.get("pathology_labels", []),
                "contrast_used": study_data.get("contrast_used", False),
                "contrast_agent": study_data.get("contrast_agent"),
                "source_institution": manifest.get("source_institution"),
                "notes": study_data.get("notes", ""),
            },
        )
        
        for idx, image_entry in enumerate(manifest.get("images", [])):
            try:
                with transaction.atomic():
                    # a. Verify file exists
                    image_filename = image_entry.get("filename")
                    image_path = os.path.join(extract_dir, image_filename)
                    
                    if not os.path.exists(image_path):
                        error_msg = f"Image file not found: {image_filename}"
                        logger.warning(error_msg)
                        error_report.append({
                            "image_index": idx,
                            "filename": image_filename,
                            "code": "file_not_found",
                            "message": error_msg,
                        })
                        images_failed += 1
                        continue
                    
                    # b. Compute SHA-256 and verify
                    actual_checksum = compute_sha256(image_path)
                    expected_checksum = image_entry.get("checksum_sha256")
                    
                    if actual_checksum != expected_checksum:
                        error_msg = (
                            f"Checksum mismatch: expected {expected_checksum}, "
                            f"got {actual_checksum}"
                        )
                        logger.warning(error_msg)
                        error_report.append({
                            "image_index": idx,
                            "filename": image_filename,
                            "code": "checksum_mismatch",
                            "message": error_msg,
                        })
                        images_failed += 1
                        continue
                    
                    # c. Validate GDPR-strict anonymization compliance
                    # Use organ-specific pseudo ID that was inserted by anonymization pipeline
                    body_part = image_entry.get("body_part", "OTHER")
                    organ_image_index = list(
                        filter(lambda e: e.get("body_part") == body_part, 
                               manifest.get("images", []))
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
                    logger.info(f"Processed image {idx + 1}/{len(manifest.get('images', []))} successfully")
            
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
