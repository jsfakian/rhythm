"""
Pseudo Patient ID Uniqueness & Collision Detection

Ensures that pseudo patient IDs are globally unique across all uploads
and enforces constraints to prevent ID collisions.
"""

import logging
from typing import Dict, List, Optional, Tuple

from django.db import IntegrityError
from .models import Patient

logger = logging.getLogger(__name__)


class PseudoIDUniquenessValidator:
    """
    Validates and ensures pseudo patient ID uniqueness across the system.
    
    Prevents collisions where different patients might have the same pseudo_id,
    which would violate GDPR and data integrity requirements.
    """
    
    @staticmethod
    def check_pseudo_id_exists(pseudo_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a pseudo_id already exists in the system.
        
        Args:
            pseudo_id: Base pseudo patient ID to check
        
        Returns:
            Tuple of (exists: bool, patient_uuid: Optional[str])
            - If exists: (True, patient_uuid)
            - If not exists: (False, None)
        """
        try:
            patient = Patient.objects.get(pseudo_id=pseudo_id)
            return True, str(patient.id)
        except Patient.DoesNotExist:
            return False, None
    
    @staticmethod
    def validate_pseudo_id_uniqueness(pseudo_id: str) -> Tuple[bool, Optional[str]]:
        """
        Validate that a pseudo_id is unique and safe to use.
        
        Returns:
            Tuple of (is_unique: bool, error_message: Optional[str])
        """
        exists, patient_id = PseudoIDUniquenessValidator.check_pseudo_id_exists(pseudo_id)
        
        if exists:
            error_msg = (
                f"Pseudo patient ID '{pseudo_id}' already exists in system "
                f"(patient_id: {patient_id}). Cannot reuse same ID for different patients."
            )
            logger.warning(error_msg)
            return False, error_msg
        
        return True, None
    
    @staticmethod
    def get_or_create_patient_with_pseudoid(
        pseudo_id: str,
        sex: Optional[str] = None,
        age_at_acquisition: Optional[float] = None,
        cohort_tag: Optional[str] = None
    ) -> Tuple[object, bool, Optional[str]]:
        """
        Get or create a Patient with the given pseudo_id.
        
        Ensures that:
        1. Each pseudo_id maps to exactly one patient record
        2. Same patient across multiple uploads has same patient record
        3. Different patients have different pseudo_ids
        
        Args:
            pseudo_id: Patient pseudo identifier
            sex: Patient sex
            age_at_acquisition: Patient age at acquisition
            cohort_tag: Research cohort tag
        
        Returns:
            Tuple of (patient: Patient, created: bool, error: Optional[str])
            - Success: (patient_obj, created_bool, None)
            - Collision: (None, False, error_msg)
        """
        try:
            patient, created = Patient.objects.get_or_create(
                pseudo_id=pseudo_id,
                defaults={
                    "sex": sex,
                    "age_at_first_acquisition": age_at_acquisition,
                    "cohort_tag": cohort_tag,
                }
            )
            
            if created:
                logger.info(
                    f"Created new Patient record with pseudo_id: {pseudo_id}"
                )
            else:
                logger.info(
                    f"Using existing Patient record for pseudo_id: {pseudo_id}"
                )
            
            return patient, created, None
            
        except IntegrityError as e:
            error_msg = (
                f"Integrity error creating patient with pseudo_id '{pseudo_id}': {str(e)}. "
                f"This pseudo_id may already exist or be invalid."
            )
            logger.error(error_msg)
            return None, False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error ensuring patient with pseudo_id '{pseudo_id}': {str(e)}"
            logger.error(error_msg)
            return None, False, error_msg
    
    @staticmethod
    def validate_manifest_pseudo_ids(
        manifest: Dict,
        allow_existing: bool = True
    ) -> Tuple[bool, List[Dict]]:
        """
        Validate all pseudo_ids in a manifest for uniqueness.
        
        Args:
            manifest: Parsed manifest dictionary
            allow_existing: If True, allow reusing existing patient pseudo_ids
                          If False, all pseudo_ids must be new
        
        Returns:
            Tuple of (all_valid: bool, errors: List[Dict])
        """
        errors = []
        patient_data = manifest.get("patient", {})
        pseudo_id = patient_data.get("pseudo_id")
        
        if not pseudo_id:
            errors.append({
                "code": "missing_pseudo_id",
                "field": "patient.pseudo_id",
                "message": "Manifest missing patient.pseudo_id"
            })
            return False, errors
        
        # Validate pseudo_id format
        if not _is_valid_pseudo_id_format(pseudo_id):
            errors.append({
                "code": "invalid_pseudo_id_format",
                "field": "patient.pseudo_id",
                "message": f"Pseudo ID '{pseudo_id}' does not match required format (8-64 alphanumeric chars, hyphens, underscores)"
            })
            return False, errors
        
        # Check uniqueness
        exists, existing_patient_id = PseudoIDUniquenessValidator.check_pseudo_id_exists(pseudo_id)
        
        if exists and not allow_existing:
            errors.append({
                "code": "pseudo_id_already_exists",
                "field": "patient.pseudo_id",
                "message": f"Pseudo ID '{pseudo_id}' already exists in system (patient_id: {existing_patient_id}). Cannot upload duplicate patient."
            })
            return False, errors
        
        if exists and allow_existing:
            logger.info(
                f"Pseudo ID '{pseudo_id}' already exists in system. "
                f"Will reuse existing patient record for multi-upload studies."
            )
        
        return True, errors
    
    @staticmethod
    def log_pseudo_id_tracking(pseudo_id: str, upload_job_id: str) -> None:
        """
        Log pseudo ID mapping for audit trail.
        
        Args:
            pseudo_id: Patient pseudo ID
            upload_job_id: Associated upload job UUID
        """
        logger.info(
            f"Pseudo ID Tracking: pseudo_id={pseudo_id}, upload_job={upload_job_id}"
        )


def _is_valid_pseudo_id_format(pseudo_id: str) -> bool:
    """
    Validate pseudo_id format.
    
    Valid format: 8-64 characters, alphanumeric + hyphens + underscores
    Example: PAT12345678, PATIENT_2024_ABC, etc.
    """
    if not isinstance(pseudo_id, str):
        return False
    
    if len(pseudo_id) < 8 or len(pseudo_id) > 64:
        return False
    
    # Allow alphanumeric, hyphens, underscores
    import re
    if not re.match(r'^[A-Za-z0-9_-]+$', pseudo_id):
        return False
    
    return True


class PseudoIDCollisionError(Exception):
    """Raised when a pseudo ID collision is detected."""
    
    def __init__(self, pseudo_id: str, existing_patient_id: str):
        self.pseudo_id = pseudo_id
        self.existing_patient_id = existing_patient_id
        super().__init__(
            f"Pseudo ID collision: '{pseudo_id}' already assigned to patient {existing_patient_id}"
        )


class PseudoIDFormatError(Exception):
    """Raised when pseudo ID format is invalid."""
    
    def __init__(self, pseudo_id: str, reason: str = "Invalid format"):
        self.pseudo_id = pseudo_id
        super().__init__(f"Invalid pseudo ID '{pseudo_id}': {reason}")
