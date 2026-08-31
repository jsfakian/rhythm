"""
Tests for uploads/gdpr_validator.py.

Covers GDPRConfig loading, GDPRAnonymizationValidator tag checks, and the
validate_gdpr_anonymization convenience function.

GDPR-strict.json's source of truth is the authoritative anonymization tool
at github.com/jsfakian/dicom_anonymization — its own validator diffs an
original DICOM against the anonymized one using a salted deterministic
derivation, which this platform can't replicate (we only ever receive the
already-anonymized file). So the fixture config below uses the same three
directives the real file uses (null / "KEEP" / "PSEUDOUID") and tests only
what GDPRAnonymizationValidator can actually check from one file alone —
see its module docstring for the exact per-directive semantics.

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

# Minimal GDPR config matching GDPR-strict.json's real directive vocabulary
# (null / "KEEP" / "PSEUDOUID" only — no more "ANON"/"PSEUDO"/"STUDY"/
# "NEWUID", which the old, pre-dicom_anonymization-aligned config used).
_GDPR_CONFIG_DICT = {
    "PatientName": None,
    "PatientID": None,
    "PatientBirthDate": None,
    "PatientSex": None,
    "InstitutionName": None,
    "ReferringPhysicianName": None,
    "AccessionNumber": None,
    "StudyDate": None,
    "SeriesDate": None,
    "StudyInstanceUID": "PSEUDOUID",
    "SeriesInstanceUID": "PSEUDOUID",
    "FrameOfReferenceUID": "PSEUDOUID",
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


def _make_clean_ds() -> Dataset:
    """
    Return a minimal GDPR-compliant in-memory pydicom Dataset.

    Has StudyInstanceUID and SeriesInstanceUID (the only two tags this
    validator requires present). No PatientID (its directive is null —
    a compliant file has it removed entirely, per the authoritative
    anonymization tool), no PHI tags, no private tags, no overlay/curve
    data, no temporal tags.
    """
    ds = Dataset()
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
            self.assertIsNone(cfg["PatientID"])
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
        ds = _make_clean_ds()
        is_valid, errors = self._validate(ds)
        self.assertTrue(is_valid, errors)
        self.assertEqual(errors, [])

    def test_no_pseudo_id_given_absent_patient_id_passes(self):
        """v2 / Manual Entry's call pattern: pseudo_id=None, PatientID's
        configured directive (null — must be absent) applies as-is."""
        ds = _make_clean_ds()
        is_valid, errors = self._validate(ds, pseudo_id=None)
        self.assertTrue(is_valid, errors)

    def test_pseudo_id_given_and_matching_passes(self):
        """v1's call pattern: it writes its own organ-specific pseudo-ID
        into PatientID during anonymization, then passes that same value
        here to verify the write succeeded — presence-and-match, not
        absence, is what "properly anonymized" means for this caller."""
        ds = _make_clean_ds()
        ds.PatientID = "PAT001_CHT01"
        is_valid, errors = self._validate(ds, pseudo_id="PAT001_CHT01")
        self.assertTrue(is_valid, errors)

    def test_pseudo_id_given_but_mismatched_fails(self):
        ds = _make_clean_ds()
        ds.PatientID = "WRONG_ID"
        is_valid, errors = self._validate(ds, pseudo_id="PAT001_CHT01")
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "patient_id_mismatch" for e in errors))

    def test_pseudo_id_given_but_patient_id_absent_fails(self):
        ds = _make_clean_ds()
        is_valid, errors = self._validate(ds, pseudo_id="PAT001_CHT01")
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "patient_id_mismatch" for e in errors))


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

    def test_patient_id_present_raises_error(self):
        """Regression: PatientID's directive is null (must be absent) —
        aligned with the authoritative anonymization tool
        (github.com/jsfakian/dicom_anonymization), which removes PatientID
        entirely rather than writing a pseudonym into it. A real partner's
        tool once used the same literal placeholder ("PID1") for every
        patient — trusting/requiring a partner-supplied PatientID value
        was never safe, so the platform no longer looks at it at all."""
        ds = _make_clean_ds()
        ds.PatientID = "PID1"
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "patient_id_present" for e in errors))

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

    def test_frame_of_reference_uid_absent_passes(self):
        """FrameOfReferenceUID is PSEUDOUID but not in the small
        always-required set (unlike Study/SeriesInstanceUID) — plenty of
        legitimate CT files won't have it. Absence alone must not fail."""
        ds = _make_clean_ds()
        is_valid, errors = self._validate(ds)
        self.assertTrue(is_valid, errors)

    def test_frame_of_reference_uid_present_but_blank_raises_error(self):
        ds = _make_clean_ds()
        ds.FrameOfReferenceUID = ""
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "pseudo_tag_blank" for e in errors))

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
        self.assertTrue(any(e["field"] == "StudyDate" for e in errors))

    def test_temporal_series_date_detected(self):
        ds = _make_clean_ds()
        ds.SeriesDate = "20200101"
        is_valid, errors = self._validate(ds)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["field"] == "SeriesDate" for e in errors))

    def test_clean_ds_has_no_structural_errors(self):
        ds = _make_clean_ds()
        is_valid, errors = self._validate(ds)
        self.assertTrue(is_valid, errors)


# ---------------------------------------------------------------------------
# GDPRAnonymizationValidator – KeepPrivateTags flag
# ---------------------------------------------------------------------------

class GDPRValidatorKeepPrivateTagsTests(TestCase):
    """The authoritative config (github.com/jsfakian/dicom_anonymization)
    sets KeepPrivateTags: true — opposite of this platform's old default.
    _check_private_tags must honor whatever the loaded config says."""

    def _validate_with_config(self, ds: Dataset, keep_private_tags: bool):
        cfg_dict = {**_GDPR_CONFIG_DICT, "KeepPrivateTags": keep_private_tags}
        cfg_path = _write_gdpr_config(cfg_dict)
        try:
            cfg = GDPRConfig(config_path=cfg_path)
        finally:
            os.unlink(cfg_path)
        validator = GDPRAnonymizationValidator(gdpr_config=cfg)
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            return validator.validate_file("/fake/path.dcm")

    def test_private_tag_allowed_when_keep_private_tags_true(self):
        ds = _make_clean_ds()
        priv = Tag(0x0009, 0x0010)
        ds[priv] = DataElement(priv, "LO", "private_value")
        is_valid, errors = self._validate_with_config(ds, keep_private_tags=True)
        self.assertTrue(is_valid, errors)

    def test_private_tag_rejected_when_keep_private_tags_false(self):
        ds = _make_clean_ds()
        priv = Tag(0x0009, 0x0010)
        ds[priv] = DataElement(priv, "LO", "private_value")
        is_valid, errors = self._validate_with_config(ds, keep_private_tags=False)
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "private_tags_present" for e in errors))


# ---------------------------------------------------------------------------
# GDPRAnonymizationValidator – KEEP directive
# ---------------------------------------------------------------------------

class GDPRValidatorKeepDirectiveTests(TestCase):

    def test_keep_tag_present_does_not_raise(self):
        cfg_dict = {**_GDPR_CONFIG_DICT, "PatientAge": "KEEP"}
        cfg_path = _write_gdpr_config(cfg_dict)
        try:
            cfg = GDPRConfig(config_path=cfg_path)
        finally:
            os.unlink(cfg_path)
        validator = GDPRAnonymizationValidator(gdpr_config=cfg)
        ds = _make_clean_ds()
        ds.PatientAge = "008Y"
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            is_valid, errors = validator.validate_file("/fake/path.dcm")
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
        """Against the real, live GDPR-strict.json — not the test fixture
        config above — confirming a minimal compliant file (no PatientID,
        Study/SeriesInstanceUID present) passes the full ~490-tag rule
        set, not just the handful this test file's fixture covers."""
        ds = _make_clean_ds()
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            is_valid, errors = validate_gdpr_anonymization("/fake/path.dcm")
        self.assertTrue(is_valid, errors)

    @override_settings(GDPR_STRICT_CONFIG_PATH="/app/GDPR-strict.json")
    def test_phi_file_returns_false(self):
        ds = _make_clean_ds()
        ds.PatientName = "John Doe"
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            is_valid, errors = validate_gdpr_anonymization("/fake/path.dcm")
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "phi_tag_present" for e in errors))

    @override_settings(GDPR_STRICT_CONFIG_PATH="/app/GDPR-strict.json")
    def test_patient_id_present_returns_false_against_real_config(self):
        ds = _make_clean_ds()
        ds.PatientID = "PID1"
        with patch("uploads.gdpr_validator.pydicom.dcmread", return_value=ds):
            is_valid, errors = validate_gdpr_anonymization("/fake/path.dcm")
        self.assertFalse(is_valid)
        self.assertTrue(any(e["code"] == "patient_id_present" for e in errors))
