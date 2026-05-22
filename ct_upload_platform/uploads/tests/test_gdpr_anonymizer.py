"""
Tests for uploads/gdpr_anonymizer.py.

Covers PseudoIDGenerator, DICOMAnonymizer, and GDPRAnonymizationPipeline.
Real DICOM temp files are used for the DICOMAnonymizer tests; Pipeline tests
mock the DICOMAnonymizer to stay fast and file-free where possible.
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

from django.test import TestCase

from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian

from uploads.gdpr_anonymizer import (
    ORGAN_ABBREVIATIONS,
    PseudoIDGenerator,
    DICOMAnonymizer,
    GDPRAnonymizationPipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_dicom_file(path: str, patient_id: str = "OLD_PAT_001") -> str:
    """Write a minimal valid DICOM file at *path* and return path."""
    meta = Dataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientID = patient_id
    ds.save_as(path)
    return path


def _minimal_manifest(filenames=("slice.dcm",), body_parts=("CHEST",)) -> dict:
    return {
        "patient": {"pseudo_id": "PAT001", "sex": "M"},
        "study": {"study_uid": generate_uid()},
        "images": [
            {"filename": fn, "body_part": bp}
            for fn, bp in zip(filenames, body_parts)
        ],
    }


# ---------------------------------------------------------------------------
# PseudoIDGenerator
# ---------------------------------------------------------------------------

class PseudoIDGeneratorTests(TestCase):

    def test_known_chest_abbreviation(self):
        pid = PseudoIDGenerator.generate_organ_specific_pseudo_id("PAT001", "CHEST", 1)
        self.assertEqual(pid, "PAT001_CHT01")

    def test_known_abdomen_abbreviation(self):
        pid = PseudoIDGenerator.generate_organ_specific_pseudo_id("PAT001", "ABDOMEN", 1)
        self.assertEqual(pid, "PAT001_ABD01")

    def test_unknown_organ_uses_oth(self):
        pid = PseudoIDGenerator.generate_organ_specific_pseudo_id("PAT001", "LIVER", 1)
        self.assertEqual(pid, "PAT001_OTH01")

    def test_index_zero_padding(self):
        single = PseudoIDGenerator.generate_organ_specific_pseudo_id("BASE", "HEAD", 5)
        double = PseudoIDGenerator.generate_organ_specific_pseudo_id("BASE", "HEAD", 10)
        self.assertEqual(single, "BASE_HED05")
        self.assertEqual(double, "BASE_HED10")

    def test_all_known_organs_have_abbreviations(self):
        for organ in ORGAN_ABBREVIATIONS:
            pid = PseudoIDGenerator.generate_organ_specific_pseudo_id("BASE", organ, 1)
            abbr = ORGAN_ABBREVIATIONS[organ]
            self.assertIn(abbr, pid)

    def test_study_pseudo_id_format(self):
        pid = PseudoIDGenerator.generate_study_pseudo_id_with_organ("PAT001", "CHEST")
        self.assertEqual(pid, "PAT001_CHT")

    def test_study_pseudo_id_unknown_organ(self):
        pid = PseudoIDGenerator.generate_study_pseudo_id_with_organ("PAT001", "UNKNOWN")
        self.assertEqual(pid, "PAT001_OTH")


# ---------------------------------------------------------------------------
# DICOMAnonymizer
# ---------------------------------------------------------------------------

class DICOMAnonymizerTests(TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _dcm_path(self, name="test.dcm", patient_id="OLD_PAT_001"):
        path = os.path.join(self.tmpdir, name)
        return _create_dicom_file(path, patient_id=patient_id)

    # set_pseudo_patient_id

    def test_set_pseudo_patient_id_modifies_file(self):
        path = self._dcm_path()
        result = DICOMAnonymizer.set_pseudo_patient_id(path, "NEW_PSEUDO_ID")
        self.assertTrue(result)

        import pydicom
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        self.assertEqual(str(ds.PatientID), "NEW_PSEUDO_ID")

    def test_set_pseudo_patient_id_creates_backup(self):
        path = self._dcm_path()
        result = DICOMAnonymizer.set_pseudo_patient_id(path, "NEW_ID", backup=True)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(path + ".bak"))

    def test_set_pseudo_patient_id_nonexistent_file_returns_false(self):
        result = DICOMAnonymizer.set_pseudo_patient_id("/no/such/file.dcm", "ID")
        self.assertFalse(result)

    # verify_patient_id_set

    def test_verify_patient_id_correct(self):
        path = self._dcm_path(patient_id="EXPECTED_ID")
        result = DICOMAnonymizer.verify_patient_id_set(path, "EXPECTED_ID")
        self.assertTrue(result)

    def test_verify_patient_id_mismatch(self):
        path = self._dcm_path(patient_id="ACTUAL_ID")
        result = DICOMAnonymizer.verify_patient_id_set(path, "WRONG_ID")
        self.assertFalse(result)

    def test_verify_patient_id_nonexistent_file_returns_false(self):
        result = DICOMAnonymizer.verify_patient_id_set("/no/such/file.dcm", "ID")
        self.assertFalse(result)

    # extract_organ_info_from_manifest

    def test_extract_organ_info_maps_filenames(self):
        manifest = {
            "images": [
                {"filename": "a.dcm", "body_part": "CHEST"},
                {"filename": "b.dcm", "body_part": "ABDOMEN"},
            ]
        }
        mapping = DICOMAnonymizer.extract_organ_info_from_manifest(manifest)
        self.assertEqual(mapping["a.dcm"], "CHEST")
        self.assertEqual(mapping["b.dcm"], "ABDOMEN")

    def test_extract_organ_info_missing_body_part_defaults_to_other(self):
        manifest = {"images": [{"filename": "c.dcm"}]}
        mapping = DICOMAnonymizer.extract_organ_info_from_manifest(manifest)
        self.assertEqual(mapping["c.dcm"], "OTHER")

    def test_extract_organ_info_empty_images(self):
        mapping = DICOMAnonymizer.extract_organ_info_from_manifest({"images": []})
        self.assertEqual(mapping, {})


# ---------------------------------------------------------------------------
# GDPRAnonymizationPipeline
# ---------------------------------------------------------------------------

class GDPRAnonymizationPipelineTests(TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _pipeline(self, manifest, base_id="PAT001"):
        return GDPRAnonymizationPipeline(
            manifest=manifest,
            extract_dir=self.tmpdir,
            base_pseudo_id=base_id,
        )

    # generate_organ_specific_ids

    def test_generate_ids_empty_manifest(self):
        pipeline = self._pipeline({"images": []})
        mapping = pipeline.generate_organ_specific_ids()
        self.assertEqual(mapping, {})

    def test_generate_ids_single_image(self):
        manifest = _minimal_manifest(["a.dcm"], ["CHEST"])
        pipeline = self._pipeline(manifest)
        mapping = pipeline.generate_organ_specific_ids()
        self.assertEqual(mapping["a.dcm"], "PAT001_CHT01")

    def test_generate_ids_same_organ_increments_counter(self):
        manifest = _minimal_manifest(["a.dcm", "b.dcm"], ["CHEST", "CHEST"])
        pipeline = self._pipeline(manifest)
        mapping = pipeline.generate_organ_specific_ids()
        self.assertEqual(mapping["a.dcm"], "PAT001_CHT01")
        self.assertEqual(mapping["b.dcm"], "PAT001_CHT02")

    def test_generate_ids_different_organs_independent_counters(self):
        manifest = _minimal_manifest(
            ["a.dcm", "b.dcm", "c.dcm"],
            ["CHEST", "ABDOMEN", "CHEST"],
        )
        pipeline = self._pipeline(manifest)
        mapping = pipeline.generate_organ_specific_ids()
        self.assertEqual(mapping["a.dcm"], "PAT001_CHT01")
        self.assertEqual(mapping["b.dcm"], "PAT001_ABD01")
        self.assertEqual(mapping["c.dcm"], "PAT001_CHT02")

    def test_generate_ids_skips_entry_without_filename(self):
        manifest = {"images": [{"body_part": "CHEST"}]}  # no filename
        pipeline = self._pipeline(manifest)
        mapping = pipeline.generate_organ_specific_ids()
        self.assertEqual(mapping, {})

    # anonymize_and_insert_pseudo_ids – error paths

    def test_error_when_image_has_no_filename(self):
        manifest = {"images": [{"body_part": "CHEST"}]}
        pipeline = self._pipeline(manifest)
        success, errors = pipeline.anonymize_and_insert_pseudo_ids()
        self.assertFalse(success)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["code"], "no_filename")

    def test_error_when_file_not_found(self):
        manifest = _minimal_manifest(["missing.dcm"], ["CHEST"])
        pipeline = self._pipeline(manifest)
        success, errors = pipeline.anonymize_and_insert_pseudo_ids()
        self.assertFalse(success)
        self.assertEqual(errors[0]["code"], "file_not_found")

    # anonymize_and_insert_pseudo_ids – success path

    def test_success_path_sets_patient_id(self):
        # Create a real DICOM file in tmpdir
        dcm_path = os.path.join(self.tmpdir, "slice.dcm")
        _create_dicom_file(dcm_path, patient_id="OLD_ID")

        manifest = _minimal_manifest(["slice.dcm"], ["CHEST"])
        pipeline = self._pipeline(manifest)
        success, errors = pipeline.anonymize_and_insert_pseudo_ids()

        self.assertTrue(success, errors)
        self.assertEqual(errors, [])

        import pydicom
        ds = pydicom.dcmread(dcm_path, stop_before_pixels=True)
        self.assertEqual(str(ds.PatientID), "PAT001_CHT01")

    def test_error_when_set_pseudo_id_fails(self):
        dcm_path = os.path.join(self.tmpdir, "slice.dcm")
        _create_dicom_file(dcm_path)

        manifest = _minimal_manifest(["slice.dcm"], ["CHEST"])
        pipeline = self._pipeline(manifest)

        with patch.object(DICOMAnonymizer, "set_pseudo_patient_id", return_value=False):
            success, errors = pipeline.anonymize_and_insert_pseudo_ids()

        self.assertFalse(success)
        self.assertEqual(errors[0]["code"], "modification_failed")

    def test_error_when_verification_fails(self):
        dcm_path = os.path.join(self.tmpdir, "slice.dcm")
        _create_dicom_file(dcm_path)

        manifest = _minimal_manifest(["slice.dcm"], ["CHEST"])
        pipeline = self._pipeline(manifest)

        with patch.object(DICOMAnonymizer, "set_pseudo_patient_id", return_value=True), \
             patch.object(DICOMAnonymizer, "verify_patient_id_set", return_value=False):
            success, errors = pipeline.anonymize_and_insert_pseudo_ids()

        self.assertFalse(success)
        self.assertEqual(errors[0]["code"], "verification_failed")

    # get_report

    def test_get_report_structure(self):
        manifest = _minimal_manifest(["a.dcm"], ["CHEST"])
        pipeline = self._pipeline(manifest)
        report = pipeline.get_report()
        self.assertIn("base_pseudo_id", report)
        self.assertIn("total_images", report)
        self.assertIn("successful", report)
        self.assertIn("failed", report)
        self.assertIn("errors", report)
        self.assertEqual(report["total_images"], 1)
        self.assertEqual(report["base_pseudo_id"], "PAT001")
