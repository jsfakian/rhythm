"""
GDPR-strict DICOM anonymization validator.

Validates that uploaded DICOM files comply with GDPR-strict anonymization rules
defined in GDPR-strict.json. Does not modify files, only validates them.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import pydicom
from django.conf import settings

logger = logging.getLogger(__name__)


class GDPRValidationError(Exception):
    """Raised when a DICOM file fails GDPR anonymization validation."""
    
    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class GDPRConfig:
    """Loads and manages GDPR-strict.json configuration."""
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = getattr(
                settings,
                'GDPR_STRICT_CONFIG_PATH',
                './GDPR-strict.json'
            )
        
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load and parse GDPR-strict.json configuration."""
        try:
            config_file = Path(self.config_path)
            if not config_file.exists():
                raise FileNotFoundError(f"GDPR config not found at {self.config_path}")
            
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            logger.info(f"Loaded GDPR config from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load GDPR config: {e}")
            raise
    
    def __getitem__(self, key: str) -> Any:
        """Get a config value."""
        return self.config.get(key)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value with default."""
        return self.config.get(key, default)


class GDPRAnonymizationValidator:
    """Validates DICOM files against GDPR-strict anonymization rules."""
    
    # Standard PHI tags that should be removed/empty
    STANDARD_PHI_TAGS = {
        'PatientName',
        'PatientBirthDate',
        'PatientAge',
        'PatientAddress',
        'PatientTelephoneNumbers',
        'PatientComments',
        'InstitutionName',
        'InstitutionAddress',
        'ReferringPhysicianName',
        'ReferringPhysicianTelephoneNumbers',
        'ReferringPhysicianAddress',
        'OperatorsName',
        'PerformingPhysicianName',
        'StudyComments',
        'DeviceSerialNumber',
    }
    
    def __init__(self, gdpr_config: Optional[GDPRConfig] = None, pseudo_id: Optional[str] = None):
        """
        Initialize validator.
        
        Args:
            gdpr_config: GDPRConfig instance. If None, loads from default path.
            pseudo_id: Expected pseudo_id for this patient (used to validate PatientID).
        """
        self.gdpr_config = gdpr_config or GDPRConfig()
        self.pseudo_id = pseudo_id
        self.validation_errors: List[Dict[str, Any]] = []
    
    def validate_file(
        self,
        file_path: str,
        pseudo_id: Optional[str] = None
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Validate that a DICOM file is properly anonymized.
        
        Args:
            file_path: Path to DICOM file
            pseudo_id: Expected patient pseudo_id for this file (overrides self.pseudo_id)
        
        Returns:
            Tuple of (is_valid, error_list)
            where error_list contains dicts with 'code', 'field', 'message'
        """
        self.validation_errors = []
        
        if pseudo_id:
            self.pseudo_id = pseudo_id
        
        try:
            ds = pydicom.dcmread(file_path, stop_before_pixels=True)
        except Exception as e:
            self.validation_errors.append({
                'code': 'dicom_read_error',
                'field': 'file',
                'message': f'Failed to read DICOM file: {str(e)}'
            })
            return False, self.validation_errors
        
        # Run validation checks
        self._check_phi_tags_removed(ds)
        self._check_patient_id(ds)
        self._check_study_uid(ds)
        self._check_series_uid(ds)
        self._check_frame_of_reference_uid(ds)
        self._check_private_tags(ds)
        self._check_overlay_data(ds)
        self._check_curve_data(ds)
        self._check_audio_data(ds)
        self._check_temporal_tags(ds)
        
        is_valid = len(self.validation_errors) == 0
        return is_valid, self.validation_errors
    
    def _check_phi_tags_removed(self, ds: pydicom.Dataset) -> None:
        """Verify that standard PHI tags are absent or empty."""
        phi_tags_to_check = {
            'PatientName',
            'PatientBirthDate',
            'PatientAge',
            'PatientAddress',
            'PatientTelephoneNumbers',
            'PatientComments',
            'InstitutionName',
            'InstitutionAddress',
            'ReferringPhysicianName',
            'ReferringPhysicianTelephoneNumbers',
            'ReferringPhysicianAddress',
            'OperatorsName',
            'PerformingPhysicianName',
            'StudyComments',
            'DeviceSerialNumber',
        }
        
        # Check PatientSex specifically (from config)
        patient_sex_action = self.gdpr_config.get('PatientSex')
        if patient_sex_action is None:  # Should be null in config
            if hasattr(ds, 'PatientSex') and ds.PatientSex:
                self.validation_errors.append({
                    'code': 'phi_tag_present',
                    'field': 'PatientSex',
                    'message': 'PatientSex must be removed (found: {})'.format(ds.PatientSex)
                })
        
        for tag_name in phi_tags_to_check:
            if hasattr(ds, tag_name):
                tag_value = getattr(ds, tag_name, None)
                # Check if tag has content (not empty string or None)
                if tag_value and str(tag_value).strip():
                    self.validation_errors.append({
                        'code': 'phi_tag_present',
                        'field': tag_name,
                        'message': f'{tag_name} must be removed (found: {str(tag_value)[:50]}...)'
                    })
    
    def _check_patient_id(self, ds: pydicom.Dataset) -> None:
        """Verify PatientID is present and matches pseudo_id (action: PSEUDO)."""
        patient_id_action = self.gdpr_config.get('PatientID')
        
        if not hasattr(ds, 'PatientID') or not ds.PatientID:
            self.validation_errors.append({
                'code': 'patient_id_missing',
                'field': 'PatientID',
                'message': 'PatientID must be present and set to pseudo_id'
            })
            return
        
        patient_id = str(ds.PatientID).strip()
        
        if self.pseudo_id and patient_id != self.pseudo_id:
            self.validation_errors.append({
                'code': 'patient_id_mismatch',
                'field': 'PatientID',
                'message': f'PatientID must be "{self.pseudo_id}" (found: "{patient_id}")'
            })
    
    def _check_study_id(self, ds: pydicom.Dataset) -> None:
        """Verify StudyID is pseudonymized (action: STUDY from config)."""
        study_id_action = self.gdpr_config.get('StudyID')
        
        if not hasattr(ds, 'StudyID'):
            self.validation_errors.append({
                'code': 'study_id_missing',
                'field': 'StudyID',
                'message': 'StudyID must be present and pseudonymized'
            })
            return
        
        study_id = str(ds.StudyID).strip()
        if not study_id:
            self.validation_errors.append({
                'code': 'study_id_empty',
                'field': 'StudyID',
                'message': 'StudyID must not be empty'
            })
    
    def _check_study_uid(self, ds: pydicom.Dataset) -> None:
        """Verify StudyInstanceUID is a new UID (action: NEWUID)."""
        if not hasattr(ds, 'StudyInstanceUID'):
            self.validation_errors.append({
                'code': 'study_uid_missing',
                'field': 'StudyInstanceUID',
                'message': 'StudyInstanceUID must be present and regenerated'
            })
            return
        
        study_uid = str(ds.StudyInstanceUID).strip()
        if not study_uid:
            self.validation_errors.append({
                'code': 'study_uid_empty',
                'field': 'StudyInstanceUID',
                'message': 'StudyInstanceUID must not be empty'
            })
    
    def _check_series_uid(self, ds: pydicom.Dataset) -> None:
        """Verify SeriesInstanceUID is a new UID (action: NEWUID)."""
        if not hasattr(ds, 'SeriesInstanceUID'):
            self.validation_errors.append({
                'code': 'series_uid_missing',
                'field': 'SeriesInstanceUID',
                'message': 'SeriesInstanceUID must be present and regenerated'
            })
            return
        
        series_uid = str(ds.SeriesInstanceUID).strip()
        if not series_uid:
            self.validation_errors.append({
                'code': 'series_uid_empty',
                'field': 'SeriesInstanceUID',
                'message': 'SeriesInstanceUID must not be empty'
            })
    
    def _check_frame_of_reference_uid(self, ds: pydicom.Dataset) -> None:
        """Verify FrameOfReferenceUID is regenerated if present (action: NEWUID)."""
        if hasattr(ds, 'FrameOfReferenceUID'):
            frame_uid = str(ds.FrameOfReferenceUID).strip()
            # If present, it should be non-empty (regenerated)
            if not frame_uid:
                self.validation_errors.append({
                    'code': 'frame_uid_empty',
                    'field': 'FrameOfReferenceUID',
                    'message': 'FrameOfReferenceUID should be empty or regenerated'
                })
    
    def _check_private_tags(self, ds: pydicom.Dataset) -> None:
        """Verify no private tags are present (KeepPrivateTags: false)."""
        private_tags_found = []
        
        for tag in ds.keys():
            # Private tags have odd group numbers
            if tag.group % 2 == 1:
                private_tags_found.append(f"({tag.group:04X},{tag.elem:04X})")
        
        if private_tags_found:
            self.validation_errors.append({
                'code': 'private_tags_present',
                'field': 'private_tags',
                'message': f'Private tags must be removed (found {len(private_tags_found)}): {", ".join(private_tags_found[:5])}'
            })
    
    def _check_overlay_data(self, ds: pydicom.Dataset) -> None:
        """Verify no overlay data is present (PixelBlackout implies overlays removed)."""
        overlay_count = 0
        for tag in ds.keys():
            # Overlay data is in the 60xx range
            if tag.group >= 0x6000 and tag.group <= 0x60FF:
                overlay_count += 1
        
        if overlay_count > 0:
            self.validation_errors.append({
                'code': 'overlay_data_present',
                'field': 'overlay',
                'message': f'Overlay data must be removed (found {overlay_count} overlay tags)'
            })
    
    def _check_curve_data(self, ds: pydicom.Dataset) -> None:
        """Verify no curve data is present."""
        curve_count = 0
        for tag in ds.keys():
            # Curve data is in the 50xx range
            if tag.group >= 0x5000 and tag.group <= 0x50FF:
                curve_count += 1
        
        if curve_count > 0:
            self.validation_errors.append({
                'code': 'curve_data_present',
                'field': 'curve',
                'message': f'Curve data must be removed (found {curve_count} curve tags)'
            })
    
    def _check_audio_data(self, ds: pydicom.Dataset) -> None:
        """Verify no audio/waveform data is present."""
        audio_tags = [0x5400, 0x5402, 0x5409]  # Audio tags
        audio_count = 0
        
        for tag in ds.keys():
            if tag.group in audio_tags:
                audio_count += 1
        
        if audio_count > 0:
            self.validation_errors.append({
                'code': 'audio_data_present',
                'field': 'audio',
                'message': f'Audio/waveform data must be removed (found {audio_count} tags)'
            })
    
    def _check_temporal_tags(self, ds: pydicom.Dataset) -> None:
        """Verify temporal information is removed (RetainStudyDate: false)."""
        temporal_tags = [
            'StudyDate',
            'SeriesDate',
            'ContentDate',
            'AcquisitionDate',
            'CurveDate',
        ]
        
        found_temporal = []
        for tag_name in temporal_tags:
            if hasattr(ds, tag_name):
                tag_value = getattr(ds, tag_name, None)
                if tag_value and str(tag_value).strip():
                    found_temporal.append(f'{tag_name}={tag_value}')
        
        if found_temporal:
            self.validation_errors.append({
                'code': 'temporal_tags_present',
                'field': 'temporal',
                'message': f'Temporal tags must be removed: {", ".join(found_temporal)}'
            })


def validate_gdpr_anonymization(
    file_path: str,
    pseudo_id: Optional[str] = None
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Convenience function to validate a DICOM file.
    
    Args:
        file_path: Path to DICOM file
        pseudo_id: Expected pseudo_id for patient validation
    
    Returns:
        Tuple of (is_valid, error_list)
    """
    try:
        validator = GDPRAnonymizationValidator(pseudo_id=pseudo_id)
        return validator.validate_file(file_path, pseudo_id)
    except Exception as e:
        logger.error(f"GDPR validation failed for {file_path}: {e}", exc_info=True)
        return False, [{'code': 'validation_error', 'message': str(e)}]
