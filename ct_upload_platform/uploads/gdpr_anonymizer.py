"""
GDPR Anonymizer for DICOM files.

Handles pseudo patient ID generation with organ information and insertion
into DICOM files to ensure GDPR compliance.
"""

import hashlib
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset, FileDataset
from datetime import datetime
import os

logger = logging.getLogger(__name__)


# Organ/body part abbreviations for pseudo ID generation
ORGAN_ABBREVIATIONS = {
    "CHEST": "CHT",
    "ABDOMEN": "ABD",
    "PELVIS": "PLS",
    "HEAD": "HED",
    "NECK": "NCK",
    "SPINE": "SPN",
    "EXTREMITY": "EXR",
    "WHOLE_BODY": "WHB",
    "OTHER": "OTH",
}


class PseudoIDGenerator:
    """Generates organ-aware pseudo patient IDs."""
    
    @staticmethod
    def generate_organ_specific_pseudo_id(
        base_pseudo_id: str,
        body_part: str,
        image_index: int
    ) -> str:
        """
        Generate a pseudo patient ID that includes organ information.
        
        Format: {base_pseudo_id}_{organ_abbr}{image_index:02d}
        Example: PAT12345678_CHT01, PAT12345678_CHT02, PAT12345678_ABD01
        
        This allows tracking which organ/body_part was imaged while maintaining
        de-identification and supporting multi-organ studies.
        
        Args:
            base_pseudo_id: Base patient pseudo ID (e.g., PAT12345678)
            body_part: Body part from manifest (CHEST, ABDOMEN, etc.)
            image_index: Sequential image index within this body part
        
        Returns:
            Organ-specific pseudo patient ID
        """
        organ_abbr = ORGAN_ABBREVIATIONS.get(body_part, "OTH")
        
        # Format: base_pseudo_id_ORGNN where ORG is organ code and NN is image counter
        pseudo_id = f"{base_pseudo_id}_{organ_abbr}{image_index:02d}"
        
        return pseudo_id
    
    @staticmethod
    def generate_study_pseudo_id_with_organ(
        base_pseudo_id: str,
        primary_body_part: str
    ) -> str:
        """
        Generate a study-level pseudo ID that includes primary organ.
        
        Format: {base_pseudo_id}_{organ_abbr}
        Example: PAT12345678_CHT
        
        Use this if you want one ID for the entire study.
        
        Args:
            base_pseudo_id: Base patient pseudo ID
            primary_body_part: Primary body part being studied
        
        Returns:
            Study-level pseudo patient ID with organ
        """
        organ_abbr = ORGAN_ABBREVIATIONS.get(primary_body_part, "OTH")
        return f"{base_pseudo_id}_{organ_abbr}"


class DICOMAnonymizer:
    """Modifies DICOM files to insert anonymized patient IDs."""
    
    @staticmethod
    def set_pseudo_patient_id(
        file_path: str,
        pseudo_patient_id: str,
        backup: bool = False
    ) -> bool:
        """
        Set the PatientID field in a DICOM file to a pseudo ID.
        
        This modifies the DICOM file in-place. Medical Record Number (MRN),
        Patient Name, and other PHI are expected to be already removed.
        
        Args:
            file_path: Path to DICOM file
            pseudo_patient_id: Pseudo patient ID to insert
            backup: If True, create .bak backup before modification
        
        Returns:
            True if successful, False on error
        """
        try:
            # Read DICOM file
            ds = pydicom.dcmread(file_path)
            
            # Create backup if requested
            if backup:
                backup_path = f"{file_path}.bak"
                if not os.path.exists(backup_path):
                    ds.save_as(backup_path)
                    logger.info(f"Created backup: {backup_path}")
            
            # Set the pseudo patient ID
            ds.PatientID = pseudo_patient_id
            
            # Save modified file back
            ds.save_as(file_path, write_like_original=False)
            logger.info(f"Set PatientID to '{pseudo_patient_id}' in {file_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to set pseudo patient ID in {file_path}: {e}")
            return False
    
    @staticmethod
    def verify_patient_id_set(file_path: str, expected_id: str) -> bool:
        """
        Verify that PatientID was set correctly in DICOM file.
        
        Args:
            file_path: Path to DICOM file
            expected_id: Expected PatientID value
        
        Returns:
            True if PatientID matches expected value
        """
        try:
            ds = pydicom.dcmread(file_path, stop_before_pixels=True)
            actual_id = str(ds.get('PatientID', '')).strip()
            
            if actual_id == expected_id:
                logger.debug(f"PatientID verified in {file_path}")
                return True
            else:
                logger.warning(
                    f"PatientID mismatch in {file_path}: "
                    f"expected '{expected_id}', got '{actual_id}'"
                )
                return False
                
        except Exception as e:
            logger.error(f"Failed to verify PatientID in {file_path}: {e}")
            return False
    
    @staticmethod
    def extract_organ_info_from_manifest(
        manifest: Dict
    ) -> Dict[str, List[str]]:
        """
        Extract organ/body_part information from manifest and map to filenames.
        
        Returns a dict mapping filename → body_part for easy lookup.
        
        Args:
            manifest: Parsed manifest.json dictionary
        
        Returns:
            Dict of {filename: body_part}
        """
        organ_mapping = {}
        
        for image_entry in manifest.get("images", []):
            filename = image_entry.get("filename")
            body_part = image_entry.get("body_part", "OTHER")
            
            if filename:
                organ_mapping[filename] = body_part
        
        logger.info(f"Extracted organ info for {len(organ_mapping)} images")
        return organ_mapping


class GDPRAnonymizationPipeline:
    """
    Complete pipeline for GDPR anonymization and pseudo ID insertion.
    
    Orchestrates validation, ID generation, and DICOM modification.
    """
    
    def __init__(self, manifest: Dict, extract_dir: str, base_pseudo_id: str):
        """
        Initialize the pipeline.
        
        Args:
            manifest: Parsed manifest.json
            extract_dir: Directory containing extracted DICOM files
            base_pseudo_id: Base pseudo patient ID from manifest
        """
        self.manifest = manifest
        self.extract_dir = extract_dir
        self.base_pseudo_id = base_pseudo_id
        self.organ_mapping = DICOMAnonymizer.extract_organ_info_from_manifest(manifest)
        self.anonymization_errors = []
        self.anonymization_report = []
    
    def generate_organ_specific_ids(self) -> Dict[str, str]:
        """
        Generate organ-specific pseudo IDs for all images in manifest.
        
        Returns mapping of filename → organ_specific_pseudo_id
        
        Returns:
            Dict of {filename: pseudo_patient_id}
        """
        pseudo_id_mapping = {}
        organ_counters = {}  # Track image count per organ
        
        for image_entry in self.manifest.get("images", []):
            filename = image_entry.get("filename")
            body_part = image_entry.get("body_part", "OTHER")
            
            if not filename:
                continue
            
            # Increment counter for this organ
            organ_counters[body_part] = organ_counters.get(body_part, 0) + 1
            image_index = organ_counters[body_part]
            
            # Generate organ-specific pseudo ID
            pseudo_id = PseudoIDGenerator.generate_organ_specific_pseudo_id(
                self.base_pseudo_id,
                body_part,
                image_index
            )
            
            pseudo_id_mapping[filename] = pseudo_id
            logger.info(
                f"Generated pseudo ID for {filename}: {pseudo_id} ({body_part})"
            )
        
        return pseudo_id_mapping
    
    def anonymize_and_insert_pseudo_ids(self) -> Tuple[bool, List[Dict]]:
        """
        Anonymize DICOM files and insert organ-specific pseudo patient IDs.
        
        This is called after tar extraction but before GDPR validation.
        Each image gets a pseudo ID that includes its organ/body_part info.
        
        Returns:
            Tuple of (success: bool, report: List[Dict])
            where report contains details for each image processed
        """
        pseudo_id_mapping = self.generate_organ_specific_ids()
        success_count = 0
        
        for idx, image_entry in enumerate(self.manifest.get("images", [])):
            filename = image_entry.get("filename")
            
            if not filename:
                self.anonymization_errors.append({
                    "image_index": idx,
                    "filename": "UNKNOWN",
                    "code": "no_filename",
                    "message": "Image entry has no filename"
                })
                continue
            
            image_path = os.path.join(self.extract_dir, filename)
            
            # Verify file exists
            if not os.path.exists(image_path):
                self.anonymization_errors.append({
                    "image_index": idx,
                    "filename": filename,
                    "code": "file_not_found",
                    "message": f"DICOM file not found: {image_path}"
                })
                continue
            
            # Get the organ-specific pseudo ID for this image
            pseudo_id = pseudo_id_mapping.get(filename)
            if not pseudo_id:
                self.anonymization_errors.append({
                    "image_index": idx,
                    "filename": filename,
                    "code": "no_pseudo_id",
                    "message": "Could not generate pseudo patient ID"
                })
                continue
            
            # Modify DICOM file to insert pseudo patient ID
            if DICOMAnonymizer.set_pseudo_patient_id(image_path, pseudo_id):
                # Verify the ID was set correctly
                if DICOMAnonymizer.verify_patient_id_set(image_path, pseudo_id):
                    self.anonymization_report.append({
                        "image_index": idx,
                        "filename": filename,
                        "code": "success",
                        "pseudo_patient_id": pseudo_id,
                        "body_part": self.organ_mapping.get(filename, "OTHER"),
                        "message": f"Successfully set pseudo patient ID: {pseudo_id}"
                    })
                    success_count += 1
                else:
                    self.anonymization_errors.append({
                        "image_index": idx,
                        "filename": filename,
                        "code": "verification_failed",
                        "message": f"PatientID verification failed for {filename}",
                        "pseudo_patient_id": pseudo_id
                    })
            else:
                self.anonymization_errors.append({
                    "image_index": idx,
                    "filename": filename,
                    "code": "modification_failed",
                    "message": f"Failed to modify DICOM file: {filename}",
                    "pseudo_patient_id": pseudo_id
                })
        
        total_images = len(self.manifest.get("images", []))
        is_success = len(self.anonymization_errors) == 0
        
        logger.info(
            f"Anonymization pipeline: {success_count}/{total_images} images "
            f"successfully processed with pseudo IDs"
        )
        
        return is_success, self.anonymization_errors
    
    def get_report(self) -> Dict:
        """Get a comprehensive anonymization report."""
        return {
            "base_pseudo_id": self.base_pseudo_id,
            "total_images": len(self.manifest.get("images", [])),
            "successful": len(self.anonymization_report),
            "failed": len(self.anonymization_errors),
            "anonymization_report": self.anonymization_report,
            "errors": self.anonymization_errors,
        }
