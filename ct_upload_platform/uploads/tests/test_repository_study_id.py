"""
Tests for uploads/repository_study_id.py.

Covers:
  - generate_repository_study_id_from_codes (low-level, code-based)
  - generate_repository_study_id (human-readable wrapper)
  - sequence numbers shared correctly between the two entry points
"""

from django.test import TestCase

from uploads.repository_study_id import (
    generate_repository_study_id,
    generate_repository_study_id_from_codes,
    is_repository_study_id,
)


class GenerateFromCodesTests(TestCase):

    def test_first_id_has_sequence_one(self) -> None:
        study_id = generate_repository_study_id_from_codes("S001", "HEADTRAUMA", "NC", "PH-G4")
        self.assertEqual(study_id, "RHY-S001-HEADTRAUMA-NC-PH-G4-000001")

    def test_sequence_increments_for_same_prefix(self) -> None:
        first = generate_repository_study_id_from_codes("S001", "HEADTRAUMA", "NC", "PH-G4")
        second = generate_repository_study_id_from_codes("S001", "HEADTRAUMA", "NC", "PH-G4")
        self.assertEqual(first, "RHY-S001-HEADTRAUMA-NC-PH-G4-000001")
        self.assertEqual(second, "RHY-S001-HEADTRAUMA-NC-PH-G4-000002")

    def test_different_prefixes_have_independent_sequences(self) -> None:
        a = generate_repository_study_id_from_codes("S001", "HEADTRAUMA", "NC", "PH-G4")
        b = generate_repository_study_id_from_codes("S002", "HEADTRAUMA", "NC", "PH-G4")
        self.assertTrue(a.endswith("-000001"))
        self.assertTrue(b.endswith("-000001"))

    def test_result_matches_canonical_format(self) -> None:
        study_id = generate_repository_study_id_from_codes("S001", "HEADTRAUMA", "NC", "PH-G4")
        self.assertTrue(is_repository_study_id(study_id))


class GenerateFromHumanReadableTests(TestCase):

    def test_resolves_codes_correctly(self) -> None:
        study_id = generate_repository_study_id(
            site_code="S001",
            clinical_indication="Head / Trauma",
            contrast="Non-contrast",
            protocol_type="PEDIATRIC_HEAD",
            examination_group="Group 4 – Childhood",
        )
        self.assertEqual(study_id, "RHY-S001-HEADTRAUMA-NC-PH-G4-000001")

    def test_shares_sequence_counter_with_code_based_entry_point(self) -> None:
        """The two entry points must never produce colliding IDs for the same
        prefix — they resolve to the same underlying counter row."""
        from_human = generate_repository_study_id(
            site_code="S001",
            clinical_indication="Head / Trauma",
            contrast="Non-contrast",
            protocol_type="PEDIATRIC_HEAD",
            examination_group="Group 4 – Childhood",
        )
        from_codes = generate_repository_study_id_from_codes("S001", "HEADTRAUMA", "NC", "PH-G4")
        self.assertEqual(from_human, "RHY-S001-HEADTRAUMA-NC-PH-G4-000001")
        self.assertEqual(from_codes, "RHY-S001-HEADTRAUMA-NC-PH-G4-000002")

    def test_unknown_indication_falls_back_to_other(self) -> None:
        study_id = generate_repository_study_id(
            site_code="S001",
            clinical_indication="Some unmapped indication",
            contrast="Non-contrast",
            protocol_type="PEDIATRIC_HEAD",
            examination_group="Group 4 – Childhood",
        )
        self.assertIn("-OTHER-", study_id)
