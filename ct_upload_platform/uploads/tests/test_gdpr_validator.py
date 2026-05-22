"""
Tests for uploads/gdpr_validator.py.

Covers GDPRConfig loading, GDPRAnonymizationValidator tag checks, and the
validate_gdpr_anonymization convenience function.

All tests are self-contained: DICOM datasets are built in-memory using
pydicom.Dataset and injected via mock; no actual DICOM files are required
for the validator tests (file-based tests in test_gdpr_anonymizer.py).
"""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings

import pydicom
from pydicom.dataset import Dataset
from pydicom.dataelem import DataElement
from pydicom.tag import Tag
from pydicom.uid import generate_uid

from uploads.gdpr_validator import (
    GDPRConfig,
    GDPRAnonymizationValidator,
    GDPRValidationError,
    validate_gdpr_anonymization,
)

# Minimal GDPR config matching the real GDPR-strict.json structure.
_GDPR_CONFIG_DICT = {
    "PatientName": "ANON",
    "PatientID": "PSEUDO",
    "PatientBirthDate": None,
    "PatientSex": None,
    "InstitutionName": None,
    "ReferringPhysicianName": None,
    "AccessionNumber": None,
    "StudyID": "STUDY",
    "StudyInstanceUID": "NEWUID",
    "SeriesInstanceUID": "NEWUID",
    "FrameOfReferenceUID": "NEWUID",
    "KeepPrivateTags": False,
    "PixelBlackout": True,
    "RetainStudyDate": False,
}


def _write_gdpr_config(data=None) -> str:
    """Write a GDPR config JSON to a temp file, return its path."""
    cfg = data if data is not None else _GDPR_CONFIG_DICT
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(cfg, f)
    f.close()
    return f.name


def _make_clean_ds(pseudo_id: str = "PAT001_CHT01") -> Dataset:
    """
    Return a minimal GDPR-compliant in-memory pydicom Dataset.

    Has PatientID, StudyInstanceUID, SeriesInstanceUID.
    No PHI tags, no private tags, no overlay/curve/temporal data.
    """
    ds = Dataset()
    ds.PatientID = pseudo_id
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    return ds


def _make_validator(pseudo_id: str = None) -> GDPRAnonymizationValidator:
    """Create a validator backed by the in-memory GDPR config."""
    cfg_path = _write_gdpr_config()
    try:
        cfg = GDPRConfig(config_path=cfg_path)
    finally:
        os.unlink(cfg_path)
    return GDPRAnonymizationValidator(gdpr_config=cfg, pseudo_id=pseudo_id)


# ---------------------------------------------------------------------------
# GDPRConfig
# ---------------------------------------------------------------------------

class GDPRConfigTests(TestCase):

    def test_load_from_path(self):
        path = _write_gdpr_config()
        try:
            cfg = GDPRConfig(config_path=path)
            self.assertEqual(cfg["PatientID"], "PSEUDO")
            self.assertFalse(cfg["KeepPrivateTags"])
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            GDPRConfig(config_path="/nonexistent/path/gdpr.json")

    def test_getitem_returns_none_for_missing_key(self):
        path = _write_gdpr_config()
        try:
            cfg = GDPRConfig(config_path=path)
            self.assertIsNone(cfg["NoSuchKey"])
        finally:
            os.unlink(path)

    def test_get_with_default(self):
        path = _write_gdpr_config()
        try:
            cfg = GDPRConfig(config_path=path)
            self.assertEqual(cfg.get("NoSuchKey", "fallback"), "fallback")
        finally:
            os.unlink(path)

    def test_null_value_loaded_as_none(self):
        path = _write_gdpr_config()
        try:
            cfg = GDPRConfig(config_path=path)
            self.assertIsNone(cfg["PatientSex"])
        finally:
            os.unlink(path)

    def test_gdpr_validation_error_stores_code_and_details(self):
        err = GDPRValidationError("test_code", "test message", details={"foo": "bar"})
        self.assertEqual(err.code, "test_code")
        self.assertEqual(err.details, {"foo": "bar"})
        self.assertIn("test message", str(err))


# ---------------------------------------------------------------------------
# GDPRAnonymizationValidator – file-read failure
# ---------------------------------------------------------------------------

class GDPRValidatorReadErrorTests(TestCase):

    def test_unreadable_file_returns_dicom_read_error(self):
        validator = _make_validator()
        with patch("uploads.gdpr_validator.pydicom.dcmread", side_effect=Exception("bad file")):
            is_valid, errors = validator.validate_file("/fake/path.dcm")
        self.assertFalse(is_valid)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["code"], "dicom_read_error")


# ---------------------------------------------------------------------------
# GDPRAnonymizationValidator – clean file passes all checks
# ---------------------------------------------------------------------------

class GDPRValidatorCleanFileTests(TestCase):

    def _validate(self, ds: Dataset, pseudo_id: str = None):
        validator = _make_validator(pseudo_id=pseudo_id)
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            return validator.validate_file("/fake/path.dcm", pseudo_id=pseudo_id)

    def test_clean_dicom_passes(self):
        ds = _make_clean_ds("PAT001_CHT01")
        is_valid, errors = self._validate(ds, pseudo_id="PAT001_CHT01")
        self.assertTrue(is_valid, errors)
        self.assertEqual(errors, [])

    def test_patient_id_matches_pseudo_id(self):
        pseudo_id = "PAT999_ABD01"
        ds = _make_clean_ds(pseudo_id)
        is_valid, errors = self._validate(ds, pseudo_id=pseudo_id)
        self.assertTrue(is_valid, errors)


# ---------------------------------------------------------------------------
# GDPRAnonymizationValidator – PHI tag checks
# ---------------------------------------------------------------------------

class GDPRValidatorPHITagTests(TestCase):

    def _validate(self, ds: Dataset, pseudo_id: str = None):
        validator = _make_validator(pseudo_id=pseudo_id)
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            return validator.validate_file("/fake/path.dcm", pseudo_id=pseudo_id)

    def test_patient_name_present_raises_error(self):
        ds = _make_clean_ds()
        ds.PatientName = "Doe^John"
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        codes = [e["code"] for e in errors]
        self.assertIn("phi_tag_present", codes)
        fields = [e["field"] for e in errors]
        self.assertIn("PatientName", fields)

    def test_patient_birthdate_present_raises_error(self):
        ds = _make_clean_ds()
        ds.PatientBirthDate = "19800101"
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["field"] == "PatientBirthDate" for e in errors))

    def test_institution_name_present_raises_error(self):
        ds = _make_clean_ds()
        ds.InstitutionName = "General Hospital"
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["field"] == "InstitutionName" for e in errors))

    def test_patient_sex_present_raises_error(self):
        # PatientSex is null in config → must be absent
        ds = _make_clean_ds()
        ds.PatientSex = "M"
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["field"] == "PatientSex" for e in errors))

    def test_patient_id_missing_raises_error(self):
        ds = _make_clean_ds()
        del ds[Tag(0x0010, 0x0020)]  # remove PatientID
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "patient_id_missing" for e in errors))

    def test_patient_id_mismatch_raises_error(self):
        ds = _make_clean_ds("WRONG_ID")
        is_valid, errors = self._validate(ds, pseudo_id="PAT001_CHT01")
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "patient_id_mismatch" for e in errors))

    def test_no_pseudo_id_given_patient_id_present_passes(self):
        ds = _make_clean_ds("ANY_ID")
        # When no pseudo_id provided, ID just needs to be present
        is_valid, errors = self._validate(ds, pseudo_id=None)
        self.assertTrue(is_valid, errors)

    def test_multiple_phi_violations_all_reported(self):
        ds = _make_clean_ds()
        ds.PatientName = "Doe^John"
        ds.PatientBirthDate = "19800101"
        ds.InstitutionName = "Hospital"
        _, errors = self._validate(ds)
        self.assertGreaterEqual(len(errors), 3)


# ---------------------------------------------------------------------------
# GDPRAnonymizationValidator – UID checks
# ---------------------------------------------------------------------------

class GDPRValidatorUIDTests(TestCase):

    def _validate(self, ds: Dataset):
        validator = _make_validator()
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            return validator.validate_file("/fake/path.dcm")

    def test_study_uid_missing_raises_error(self):
        ds = _make_clean_ds()
        del ds[Tag(0x0020, 0x000D)]
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "study_uid_missing" for e in errors))

    def test_series_uid_missing_raises_error(self):
        ds = _make_clean_ds()
        del ds[Tag(0x0020, 0x000E)]
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "series_uid_missing" for e in errors))

    def test_frame_of_reference_uid_empty_raises_error(self):
        ds = _make_clean_ds()
        ds.FrameOfReferenceUID = ""
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "frame_uid_empty" for e in errors))

    def test_frame_of_reference_uid_valid_passes(self):
        ds = _make_clean_ds()
        ds.FrameOfReferenceUID = generate_uid()
        is_valid, errors = self._validate(ds)
        self.assertTrue(is_valid, errors)


# ---------------------------------------------------------------------------
# GDPRAnonymizationValidator – structural data checks
# ---------------------------------------------------------------------------

class GDPRValidatorStructuralTests(TestCase):

    def _validate(self, ds: Dataset):
        validator = _make_validator()
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            return validator.validate_file("/fake/path.dcm")

    def test_private_tag_detected(self):
        ds = _make_clean_ds()
        priv = Tag(0x0009, 0x0010)
        ds[priv] = DataElement(priv, "LO", "private_value")
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "private_tags_present" for e in errors))

    def test_overlay_data_detected(self):
        ds = _make_clean_ds()
        otag = Tag(0x6000, 0x3000)
        ds[otag] = DataElement(otag, "OB", b"\x00" * 4)
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "overlay_data_present" for e in errors))

    def test_curve_data_detected(self):
        ds = _make_clean_ds()
        ctag = Tag(0x5000, 0x0005)
        ds[ctag] = DataElement(ctag, "US", 0)
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "curve_data_present" for e in errors))

    def test_temporal_study_date_detected(self):
        ds = _make_clean_ds()
        ds.StudyDate = "20200101"
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "temporal_tags_present" for e in errors))

    def test_temporal_series_date_detected(self):
        ds = _make_clean_ds()
        ds.SeriesDate = "20200101"
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "temporal_tags_present" for e in errors))

    def test_clean_ds_has_no_structural_errors(self):
        ds = _make_clean_ds()
        is_valid, errors = self._validate(ds)
        self.assertTrue(is_valid, errors)


# ---------------------------------------------------------------------------
# validate_gdpr_anonymization convenience function
# ---------------------------------------------------------------------------

class ValidateGDPRAnonymizationTests(TestCase):

    @override_settings(GDPR_STRICT_CONFIG_PATH="/app/GDPR-strict.json")
    def test_returns_false_list_on_config_missing(self):
        with override_settings(GDPR_STRICT_CONFIG_PATH="/no/such/file.json"):
            is_valid, errors = validate_gdpr_anonymization("/fake/path.dcm", "PAT001")
        self.assertFalse(is_valid)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["code"], "validation_error")

    @override_settings(GDPR_STRICT_CONFIG_PATH="/app/GDPR-strict.json")
    def test_clean_file_returns_true(self):
        ds = _make_clean_ds("PAT001_CHT01")
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            is_valid, errors = validate_gdpr_anonymization("/fake/path.dcm", "PAT001_CHT01")
        self.assertTrue(is_valid, errors)

    @override_settings(GDPR_STRICT_CONFIG_PATH="/app/GDPR-strict.json")
    def test_phi_file_returns_false(self):
        ds = _make_clean_ds()
        ds.PatientName = "John Doe"
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            is_valid, errors = validate_gdpr_anonymization("/fake/path.dcm")
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "phi_tag_present" for e in errors))
