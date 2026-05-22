"""
Unit tests for manifest schema validation.
"""

import json
import unittest
from datetime import date, timedelta
from uploads.manifest_schema import validate_manifest, MANIFEST_SCHEMA_V1


class ManifestValidatorTestCase(unittest.TestCase):
    """Test suite for manifest schema validator."""

    def setUp(self):
        """Create a valid base manifest for testing."""
        self.valid_manifest = {
            "manifest_version": "1.0",
            "upload_id": "550e8400-e29b-41d4-a716-446655440000",
            "created_at": "2026-02-26T10:30:00Z",
            "study": {
                "study_uid": "1.2.3.4.5",
                "acquisition_date": "2026-02-20",
                "clinical_indication": "Routine chest X-ray",
                "contrast_used": False,
            },
            "patient": {
                "pseudo_id": "PAT_001_ABC",
                "sex": "M",
                "age_at_acquisition": 45,
                "cohort_tag": "control",
            },
            "images": [
                {
                    "filename": "image_001.dcm",
                    "checksum_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "series_uid": "1.2.3.4.5.1",
                    "body_part": "CHEST",
                    "instance_number": 1,
                }
            ],
        }

    def test_valid_manifest(self):
        """Test that a valid manifest passes validation."""
        errors = validate_manifest(self.valid_manifest)
        self.assertEqual(errors, [])

    def test_valid_manifest_with_all_fields(self):
        """Test validation with all optional fields populated."""
        manifest = self.valid_manifest.copy()
        manifest["source_institution"] = "General Hospital"
        manifest["study"] = {
            "study_uid": "1.2.3.4.5",
            "acquisition_date": "2026-02-20",
            "clinical_indication": "Routine chest X-ray",
            "pathology_labels": ["pneumonia", "infiltrate"],
            "contrast_used": True,
            "contrast_agent": "Omnipaque",
            "notes": "Post-contrast imaging",
        }
        manifest["images"][0].update({
            "series_number": 1,
            "laterality": "NA",
            "view_plane": "AXIAL",
            "slice_thickness_mm": 2.5,
            "pixel_spacing_mm": [0.5, 0.5],
            "image_dimensions": {"rows": 512, "cols": 512},
            "scanner_manufacturer": "Siemens",
            "scanner_model": "SOMATOM Definition",
            "kvp": 120.0,
            "processing_status": "RAW",
            "annotations": [
                {
                    "annotation_uid": "ANN_001",
                    "type": "SEGMENTATION",
                    "label": "lung_region",
                    "annotator_id": "DR_SMITH",
                    "annotation_date": "2026-02-21",
                }
            ],
        })
        manifest["pipeline"] = {
            "uploader_id": "user_123",
            "upload_client_version": "1.0.0",
        }
        errors = validate_manifest(manifest)
        self.assertEqual(errors, [])

    def test_missing_manifest_version(self):
        """Test validation fails when manifest_version is missing."""
        manifest = self.valid_manifest.copy()
        del manifest["manifest_version"]
        errors = validate_manifest(manifest)
        self.assertTrue(any(e["code"] == "required" for e in errors))

    def test_missing_upload_id(self):
        """Test validation fails when upload_id is missing."""
        manifest = self.valid_manifest.copy()
        del manifest["upload_id"]
        errors = validate_manifest(manifest)
        self.assertTrue(any(e["code"] == "required" for e in errors))

    def test_missing_created_at(self):
        """Test validation fails when created_at is missing."""
        manifest = self.valid_manifest.copy()
        del manifest["created_at"]
        errors = validate_manifest(manifest)
        self.assertTrue(any(e["code"] == "required" for e in errors))

    def test_missing_patient(self):
        """Test validation fails when patient object is missing."""
        manifest = self.valid_manifest.copy()
        del manifest["patient"]
        errors = validate_manifest(manifest)
        self.assertTrue(any(e["code"] == "required" for e in errors))

    def test_missing_study(self):
        """Test validation fails when study object is missing."""
        manifest = self.valid_manifest.copy()
        del manifest["study"]
        errors = validate_manifest(manifest)
        self.assertTrue(any(e["code"] == "required" for e in errors))

    def test_missing_images(self):
        """Test validation fails when images array is missing."""
        manifest = self.valid_manifest.copy()
        del manifest["images"]
        errors = validate_manifest(manifest)
        self.assertTrue(any(e["code"] == "required" for e in errors))

    def test_missing_pseudo_id(self):
        """Test validation fails when patient.pseudo_id is missing."""
        manifest = self.valid_manifest.copy()
        del manifest["patient"]["pseudo_id"]
        errors = validate_manifest(manifest)
        self.assertTrue(any(e["code"] == "required" for e in errors))

    def test_bad_pseudo_id_pattern_too_short(self):
        """Test validation fails for pseudo_id that is too short."""
        manifest = self.valid_manifest.copy()
        manifest["patient"]["pseudo_id"] = "PAT001"  # Only 6 chars, need 8+
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "pseudo_id too short should fail validation")

    def test_bad_pseudo_id_pattern_invalid_chars(self):
        """Test validation fails for pseudo_id with invalid characters."""
        manifest = self.valid_manifest.copy()
        manifest["patient"]["pseudo_id"] = "PAT@001ABC"  # @ is not allowed
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "pseudo_id with invalid chars should fail validation")

    def test_good_pseudo_id_patterns(self):
        """Test validation passes for valid pseudo_id patterns."""
        valid_patterns = [
            "PAT_001_ABC",
            "pat001abc00",  # 11 chars
            "PAT-001-ABCD",  # 12 chars
            "a" * 8,  # min length
            "a" * 64,  # max length
            "P1_A-2B_C",  # 9 chars with valid chars
        ]
        for pattern in valid_patterns:
            manifest = self.valid_manifest.copy()
            manifest["patient"]["pseudo_id"] = pattern
            errors = validate_manifest(manifest)
            pseudo_id_errors = [
                e for e in errors if e["field"] == "$.patient.pseudo_id"
            ]
            self.assertEqual(
                pseudo_id_errors,
                [],
                f"pseudo_id '{pattern}' should be valid",
            )

    def test_future_acquisition_date(self):
        """Test validation fails when acquisition_date is in the future."""
        manifest = self.valid_manifest.copy()
        future_date = (date.today() + timedelta(days=1)).isoformat()
        manifest["study"]["acquisition_date"] = future_date
        errors = validate_manifest(manifest)
        self.assertTrue(any(e["code"] == "future_date" for e in errors))

    def test_today_acquisition_date(self):
        """Test validation passes when acquisition_date is today."""
        manifest = self.valid_manifest.copy()
        manifest["study"]["acquisition_date"] = date.today().isoformat()
        errors = validate_manifest(manifest)
        # Should not have future_date errors
        future_errors = [e for e in errors if e["code"] == "future_date"]
        self.assertEqual(future_errors, [])

    def test_past_acquisition_date(self):
        """Test validation passes when acquisition_date is in the past."""
        manifest = self.valid_manifest.copy()
        past_date = (date.today() - timedelta(days=365)).isoformat()
        manifest["study"]["acquisition_date"] = past_date
        errors = validate_manifest(manifest)
        # Should not have future_date errors
        future_errors = [e for e in errors if e["code"] == "future_date"]
        self.assertEqual(future_errors, [])

    def test_duplicate_filenames(self):
        """Test validation fails when images have duplicate filenames."""
        manifest = self.valid_manifest.copy()
        manifest["images"] = [
            {
                "filename": "image_001.dcm",
                "checksum_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "series_uid": "1.2.3.4.5.1",
                "body_part": "CHEST",
            },
            {
                "filename": "image_001.dcm",  # Duplicate
                "checksum_sha256": "a1b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b856",
                "series_uid": "1.2.3.4.5.1",
                "body_part": "CHEST",
            },
        ]
        errors = validate_manifest(manifest)
        self.assertTrue(any(e["code"] == "duplicate_filename" for e in errors))

    def test_no_duplicate_filenames_with_different_names(self):
        """Test validation passes when all filenames are unique."""
        manifest = self.valid_manifest.copy()
        manifest["images"] = [
            {
                "filename": "image_001.dcm",
                "checksum_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "series_uid": "1.2.3.4.5.1",
                "body_part": "CHEST",
            },
            {
                "filename": "image_002.dcm",
                "checksum_sha256": "a1b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b856",
                "series_uid": "1.2.3.4.5.1",
                "body_part": "CHEST",
            },
        ]
        errors = [e for e in validate_manifest(manifest) if e["code"] == "duplicate_filename"]
        self.assertEqual(errors, [])

    def test_bad_checksum_format_too_short(self):
        """Test validation fails for checksum that is too short."""
        manifest = self.valid_manifest.copy()
        manifest["images"][0]["checksum_sha256"] = "abcdef"  # Too short
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Checksum too short should cause validation error")

    def test_bad_checksum_format_invalid_chars(self):
        """Test validation fails for checksum with invalid characters."""
        manifest = self.valid_manifest.copy()
        manifest["images"][0]["checksum_sha256"] = "X" * 64  # Uppercase X not in hex
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Invalid checksum format should cause validation error")

    def test_good_checksum_format(self):
        """Test validation passes for valid SHA-256 checksum format."""
        manifest = self.valid_manifest.copy()
        # Valid hex, lowercase, exactly 64 chars
        manifest["images"][0]["checksum_sha256"] = "a" * 64
        errors = [
            e for e in validate_manifest(manifest)
            if "checksum" in e["field"].lower()
        ]
        self.assertEqual(errors, [])

    def test_invalid_sex_enum(self):
        """Test validation fails for invalid sex value."""
        manifest = self.valid_manifest.copy()
        manifest["patient"]["sex"] = "X"  # Not in enum
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Invalid sex value should cause validation error")

    def test_age_out_of_range_negative(self):
        """Test validation fails for negative age."""
        manifest = self.valid_manifest.copy()
        manifest["patient"]["age_at_acquisition"] = -5
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Negative age should cause validation error")

    def test_age_out_of_range_too_high(self):
        """Test validation fails for age over 130."""
        manifest = self.valid_manifest.copy()
        manifest["patient"]["age_at_acquisition"] = 150
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Age over 130 should cause validation error")

    def test_age_boundary_valid_zero(self):
        """Test validation passes for age 0."""
        manifest = self.valid_manifest.copy()
        manifest["patient"]["age_at_acquisition"] = 0
        errors = [
            e for e in validate_manifest(manifest)
            if "age" in e["field"].lower()
        ]
        self.assertEqual(errors, [])

    def test_age_boundary_valid_130(self):
        """Test validation passes for age 130."""
        manifest = self.valid_manifest.copy()
        manifest["patient"]["age_at_acquisition"] = 130
        errors = [
            e for e in validate_manifest(manifest)
            if "age" in e["field"].lower()
        ]
        self.assertEqual(errors, [])

    def test_invalid_body_part(self):
        """Test validation fails for invalid body_part."""
        manifest = self.valid_manifest.copy()
        manifest["images"][0]["body_part"] = "INVALID"
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Invalid body_part should cause validation error")

    def test_valid_body_parts(self):
        """Test validation passes for all valid body_part values."""
        valid_body_parts = ["CHEST", "ABDOMEN", "PELVIS", "HEAD", "NECK", "SPINE", "EXTREMITY", "WHOLE_BODY", "OTHER"]
        for body_part in valid_body_parts:
            manifest = self.valid_manifest.copy()
            manifest["images"][0]["body_part"] = body_part
            errors = [
                e for e in validate_manifest(manifest)
                if "body_part" in e["field"].lower()
            ]
            self.assertEqual(errors, [], f"body_part '{body_part}' should be valid")

    def test_invalid_view_plane(self):
        """Test validation fails for invalid view_plane."""
        manifest = self.valid_manifest.copy()
        manifest["images"][0]["view_plane"] = "INVALID"
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Invalid view_plane should cause validation error")

    def test_empty_images_array(self):
        """Test validation fails when images array is empty."""
        manifest = self.valid_manifest.copy()
        manifest["images"] = []
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Empty images array should cause validation error")

    def test_pixel_spacing_wrong_length(self):
        """Test validation fails for pixel_spacing with wrong array length."""
        manifest = self.valid_manifest.copy()
        manifest["images"][0]["pixel_spacing_mm"] = [0.5]  # Should be exactly 2 items
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Wrong pixel_spacing array length should cause validation error")

    def test_pixel_spacing_valid(self):
        """Test validation passes for valid pixel_spacing."""
        manifest = self.valid_manifest.copy()
        manifest["images"][0]["pixel_spacing_mm"] = [0.5, 0.5]
        errors = [
            e for e in validate_manifest(manifest)
            if "pixel_spacing" in e["field"].lower()
        ]
        self.assertEqual(errors, [])

    def test_image_dimensions_missing_cols(self):
        """Test validation fails when image_dimensions is missing cols."""
        manifest = self.valid_manifest.copy()
        manifest["images"][0]["image_dimensions"] = {"rows": 512}
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Missing cols in image_dimensions should cause validation error")

    def test_image_dimensions_valid(self):
        """Test validation passes for valid image_dimensions."""
        manifest = self.valid_manifest.copy()
        manifest["images"][0]["image_dimensions"] = {"rows": 512, "cols": 512}
        errors = [
            e for e in validate_manifest(manifest)
            if "image_dimensions" in e["field"].lower()
        ]
        self.assertEqual(errors, [])

    def test_missing_required_image_fields(self):
        """Test validation fails when required image fields are missing."""
        required_fields = ["filename", "checksum_sha256", "series_uid", "body_part"]
        for field in required_fields:
            manifest = self.valid_manifest.copy()
            del manifest["images"][0][field]
            errors = validate_manifest(manifest)
            self.assertTrue(any(e["code"] == "required" for e in errors),
                          f"Missing {field} should cause validation error")

    def test_invalid_contrast_agent_type(self):
        """Test validation fails when contrast_agent is not string or null."""
        manifest = self.valid_manifest.copy()
        manifest["study"]["contrast_agent"] = 123  # Should be string or null
        errors = validate_manifest(manifest)
        self.assertTrue(len(errors) > 0, "Invalid contrast_agent type should cause validation error")

    def test_contrast_agent_null(self):
        """Test validation passes when contrast_agent is explicitly null."""
        manifest = self.valid_manifest.copy()
        manifest["study"]["contrast_agent"] = None
        errors = validate_manifest(manifest)
        # Should not have type errors for contrast_agent
        contrast_errors = [
            e for e in errors
            if "contrast_agent" in e["field"].lower()
            and e["code"] == "schema_validation_error"
        ]
        self.assertEqual(contrast_errors, [])
