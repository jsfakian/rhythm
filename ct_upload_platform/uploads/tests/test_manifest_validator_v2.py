"""
Unit tests for the v2 (server-assigned batch) manifest schema.

The v2 shape is produced by the partner-side
`create_rhythm_server_assigned_manifest_gui[_with_uid].py` tools: one
manifest per batch, each `items[]` entry describing one ZIP archive
(one already-anonymized CT studyset) plus inline dose/quality metadata.
"""

import unittest

from uploads.manifest_schema import (
    validate_manifest_v2,
    validate_manifest_auto,
    is_v2_batch_manifest,
)


class ManifestV2ValidatorTestCase(unittest.TestCase):

    def setUp(self):
        self.valid_manifest = {
            "v": "1.0",
            "type": "rhythm_server_assigned_upload_manifest",
            "server_assigns_repo_id": True,
            "site": "S001",
            "batch": "S001-BATCH001",
            "items": [
                {
                    "ref": "ROW0001",
                    "filename": "Input_volume1.zip",
                    "site_code": "S001",
                    "clinical_indication_code": "HEADTRAUMA",
                    "anatomical_region": "Head",
                    "contrast_code": "NC",
                    "patient_group_code": "PH-G4",
                    "scanner_id": "CT01",
                    "protocol_name": "Pediatric head trauma non-contrast",
                    "patient_weight_kg": 28.0,
                    "patient_age_years": 8.0,
                    "ctdivol_mgy": 18.4,
                    "dlp_mgy_cm": 320.5,
                    "image_quality": "Acceptable",
                    "size_bytes": 13695187,
                    "sha256": "bc5bd2fb66736779c6f33d23dfa865680f97cb6e6755b2bae98da0996413bbd3",
                }
            ],
        }

    def test_valid_manifest_passes(self):
        errors = validate_manifest_v2(self.valid_manifest)
        self.assertEqual(errors, [])

    def test_missing_required_top_level_field(self):
        manifest = dict(self.valid_manifest)
        del manifest["site"]
        errors = validate_manifest_v2(manifest)
        self.assertTrue(any(e["code"] == "required" for e in errors))

    def test_missing_required_item_field(self):
        manifest = {**self.valid_manifest, "items": [dict(self.valid_manifest["items"][0])]}
        del manifest["items"][0]["clinical_indication_code"]
        errors = validate_manifest_v2(manifest)
        self.assertTrue(any(e["code"] == "required" for e in errors))

    def test_wrong_type_discriminator_rejected(self):
        manifest = {**self.valid_manifest, "type": "something_else"}
        errors = validate_manifest_v2(manifest)
        self.assertTrue(any(e["code"] == "const" for e in errors))

    def test_duplicate_filename_across_items(self):
        item = dict(self.valid_manifest["items"][0])
        item2 = {**item, "ref": "ROW0002"}
        manifest = {**self.valid_manifest, "items": [item, item2]}
        errors = validate_manifest_v2(manifest)
        self.assertTrue(any(e["code"] == "duplicate_filename" for e in errors))

    def test_duplicate_ref_across_items(self):
        item = dict(self.valid_manifest["items"][0])
        item2 = {**item, "filename": "other.zip"}
        manifest = {**self.valid_manifest, "items": [item, item2]}
        errors = validate_manifest_v2(manifest)
        self.assertTrue(any(e["code"] == "duplicate_ref" for e in errors))

    def test_invalid_sha256_pattern(self):
        manifest = {**self.valid_manifest, "items": [dict(self.valid_manifest["items"][0])]}
        manifest["items"][0]["sha256"] = "not-a-valid-hash"
        errors = validate_manifest_v2(manifest)
        self.assertTrue(any(e["code"] == "pattern" for e in errors))

    def test_empty_items_array_rejected(self):
        manifest = {**self.valid_manifest, "items": []}
        errors = validate_manifest_v2(manifest)
        self.assertTrue(any(e["code"] == "minItems" for e in errors))


class ManifestAutoDetectTestCase(unittest.TestCase):

    def test_v2_manifest_detected_by_type(self):
        manifest = {"type": "rhythm_server_assigned_upload_manifest", "items": []}
        self.assertTrue(is_v2_batch_manifest(manifest))

    def test_v2_manifest_detected_by_items_key(self):
        manifest = {"items": [], "site": "S001"}
        self.assertTrue(is_v2_batch_manifest(manifest))

    def test_v1_manifest_not_detected_as_v2(self):
        manifest = {"manifest_version": "1.0", "patient": {}, "study": {}, "images": []}
        self.assertFalse(is_v2_batch_manifest(manifest))

    def test_auto_validates_v2_manifest_as_v2(self):
        manifest = {
            "v": "1.0",
            "type": "rhythm_server_assigned_upload_manifest",
            "site": "S001",
            "items": [],
        }
        version, errors = validate_manifest_auto(manifest)
        self.assertEqual(version, "v2")
        # Empty items array is invalid, but we're only checking dispatch here.
        self.assertTrue(any(e["code"] == "minItems" for e in errors))

    def test_auto_validates_v1_manifest_as_v1(self):
        manifest = {"manifest_version": "1.0"}
        version, errors = validate_manifest_auto(manifest)
        self.assertEqual(version, "v1")
        self.assertTrue(len(errors) > 0)


if __name__ == "__main__":
    unittest.main()
