"""
Tests for CT Examination Data Entry:
  - Unit: CTExamination model fields and total_dlp property
  - Functional: ExaminationEntryView, ExaminationSaveAPIView,
                ExaminationListView, ExaminationDeleteView
"""

import json
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from uploads.models import (
    CTExamination,
    CTManufacturer,
    CTProtocol,
    CTScannerModel,
    CTScannerProfile,
)


# ---------------------------------------------------------------------------
# Shared fixture mixin
# ---------------------------------------------------------------------------

class _ExamFixtures:
    """Creates DB objects needed by all test classes below."""

    @classmethod
    def _make_scanner(cls, created_by: str = "") -> CTScannerProfile:
        mfr, _ = CTManufacturer.objects.get_or_create(
            name="GE Healthcare",
            defaults={"is_active": True, "sort_order": 0},
        )
        model, _ = CTScannerModel.objects.get_or_create(
            manufacturer=mfr,
            name="Revolution CT Exam",
            defaults={"is_active": True, "sort_order": 0},
        )
        return CTScannerProfile.objects.create(
            manufacturer=mfr,
            scanner_model=model,
            detector_rows="256",
            year_of_installation="2022",
            created_by=created_by,
        )

    @classmethod
    def _make_protocol(cls, scanner: CTScannerProfile) -> CTProtocol:
        return CTProtocol.objects.create(
            scanner=scanner,
            protocol_type="PEDIATRIC_BODY",
            anatomical_region="Head",
            clinical_indication="Trauma",
            contrast="Non-contrast",
            examination_group="Group 1 - Neonate",
            age_group="< 5 kg",
        )

    @classmethod
    def _make_examination(
        cls,
        scanner: CTScannerProfile | None = None,
        protocol: CTProtocol | None = None,
        **kwargs,
    ) -> CTExamination:
        defaults = {
            "anatomical_region": "Head",
            "clinical_indication": "Trauma",
            "patient_weight": "12.5",
            "patient_age": 4,
            "number_of_phases": 2,
            "ctdi_vol_per_phase": [3.1, 4.2],
            "dlp_per_phase": [50.0, 60.0],
            "image_quality": "GOOD",
            "created_by": "testuser",
        }
        defaults.update(kwargs)
        return CTExamination.objects.create(
            scanner=scanner,
            protocol=protocol,
            **defaults,
        )


# ---------------------------------------------------------------------------
# Unit tests — CTExamination model
# ---------------------------------------------------------------------------

class CTExaminationModelTests(_ExamFixtures, TestCase):

    def setUp(self) -> None:
        self.scanner = self._make_scanner()
        self.protocol = self._make_protocol(self.scanner)

    def test_create_with_required_fields(self) -> None:
        exam = CTExamination.objects.create(
            anatomical_region="Chest",
            clinical_indication="Lymphoma",
            number_of_phases=1,
            ctdi_vol_per_phase=[5.0],
            dlp_per_phase=[80.0],
            image_quality="EXCELLENT",
        )
        self.assertIsNotNone(exam.pk)
        self.assertIsInstance(exam.pk, uuid.UUID)

    def test_pk_is_uuid(self) -> None:
        exam = self._make_examination(self.scanner)
        self.assertIsInstance(exam.pk, uuid.UUID)

    def test_scanner_fk_nullable(self) -> None:
        exam = self._make_examination(scanner=None)
        self.assertIsNone(exam.scanner)

    def test_protocol_fk_nullable(self) -> None:
        exam = self._make_examination(self.scanner, protocol=None)
        self.assertIsNone(exam.protocol)

    def test_protocol_fk_links_correctly(self) -> None:
        exam = self._make_examination(self.scanner, self.protocol)
        self.assertEqual(exam.protocol.pk, self.protocol.pk)

    def test_patient_weight_nullable(self) -> None:
        exam = CTExamination.objects.create(
            anatomical_region="Abdomen",
            clinical_indication="Acute abdomen",
            number_of_phases=1,
            ctdi_vol_per_phase=[4.0],
            dlp_per_phase=[70.0],
            patient_weight=None,
            water_equivalent_diameter="18.5",
        )
        self.assertIsNone(exam.patient_weight)
        self.assertAlmostEqual(float(exam.water_equivalent_diameter), 18.5)

    def test_total_dlp_property_sum(self) -> None:
        exam = self._make_examination(self.scanner, dlp_per_phase=[50.0, 60.0])
        self.assertAlmostEqual(exam.total_dlp, 110.0)

    def test_total_dlp_single_phase(self) -> None:
        exam = CTExamination.objects.create(
            number_of_phases=1,
            ctdi_vol_per_phase=[3.5],
            dlp_per_phase=[42.0],
        )
        self.assertAlmostEqual(exam.total_dlp, 42.0)

    def test_total_dlp_empty_list(self) -> None:
        exam = CTExamination.objects.create(
            number_of_phases=1,
            ctdi_vol_per_phase=[],
            dlp_per_phase=[],
        )
        self.assertAlmostEqual(exam.total_dlp, 0.0)

    def test_image_quality_choices_stored(self) -> None:
        for code, _ in CTExamination.IMAGE_QUALITY_CHOICES:
            exam = CTExamination.objects.create(
                number_of_phases=1,
                ctdi_vol_per_phase=[1.0],
                dlp_per_phase=[10.0],
                image_quality=code,
            )
            self.assertEqual(exam.image_quality, code)

    def test_ctdi_and_dlp_stored_as_list(self) -> None:
        exam = self._make_examination(self.scanner, ctdi_vol_per_phase=[1.1, 2.2, 3.3], dlp_per_phase=[10.0, 20.0, 30.0], number_of_phases=3)
        self.assertEqual(exam.ctdi_vol_per_phase, [1.1, 2.2, 3.3])
        self.assertEqual(exam.dlp_per_phase, [10.0, 20.0, 30.0])

    def test_auto_timestamps(self) -> None:
        exam = self._make_examination(self.scanner)
        self.assertIsNotNone(exam.created_at)
        self.assertIsNotNone(exam.updated_at)

    def test_created_by_stored(self) -> None:
        exam = self._make_examination(self.scanner, created_by="alice")
        self.assertEqual(exam.created_by, "alice")

    def test_multiple_examinations_independent(self) -> None:
        e1 = self._make_examination(self.scanner, patient_age=3)
        e2 = self._make_examination(self.scanner, patient_age=7)
        self.assertNotEqual(e1.pk, e2.pk)
        self.assertNotEqual(e1.patient_age, e2.patient_age)


# ---------------------------------------------------------------------------
# Functional tests — ExaminationEntryView (GET)
# ---------------------------------------------------------------------------

class ExaminationEntryViewTests(_ExamFixtures, TestCase):

    def setUp(self) -> None:
        self.user = User.objects.create_user("examuser", password="pass")
        self.client.force_login(self.user)
        self.scanner = self._make_scanner(created_by="examuser")

    def test_redirects_when_unauthenticated(self) -> None:
        self.client.logout()
        resp = self.client.get(reverse("examination-entry"))
        self.assertIn(resp.status_code, (302, 301))

    def test_page_returns_200(self) -> None:
        resp = self.client.get(reverse("examination-entry"))
        self.assertEqual(resp.status_code, 200)

    def test_page_contains_scanners_json(self) -> None:
        resp = self.client.get(reverse("examination-entry"))
        self.assertIn(b'"scanners"', resp.content)

    def test_page_contains_clinical_rows_json(self) -> None:
        resp = self.client.get(reverse("examination-entry"))
        self.assertIn(b'"clinical_rows"', resp.content)

    def test_page_contains_manufacturer_data(self) -> None:
        resp = self.client.get(reverse("examination-entry"))
        # Manufacturer name appears inside the SCANNERS JSON constant
        self.assertIn(b"GE Healthcare", resp.content)

    def test_page_contains_indication_selector(self) -> None:
        resp = self.client.get(reverse("examination-entry"))
        self.assertIn(b"sel_indication_combo", resp.content)

    def test_scanner_name_visible_in_page(self) -> None:
        resp = self.client.get(reverse("examination-entry"))
        self.assertIn(b"GE Healthcare", resp.content)

    def test_empty_scanner_list(self) -> None:
        CTScannerProfile.objects.all().delete()
        resp = self.client.get(reverse("examination-entry"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'"scanners"', resp.content)

    def test_save_status_indicator_present(self) -> None:
        """A 'Saving…' indicator must exist so the user gets feedback while
        the (possibly large) study set upload is in flight."""
        resp = self.client.get(reverse("examination-entry"))
        self.assertIn(b'id="saveStatus"', resp.content)

    def test_result_banners_positioned_near_save_button(self) -> None:
        """The success/error banners must render near the Save button (bottom
        of the form) rather than above the fold, so the user doesn't have to
        scroll back up to see the outcome of a save."""
        resp = self.client.get(reverse("examination-entry"))
        body = resp.content.decode()
        self.assertGreater(body.index('id="successBanner"'), body.index('id="inp_study_set"'))
        self.assertGreater(body.index('id="errorBanner"'), body.index('id="inp_study_set"'))


# ---------------------------------------------------------------------------
# Functional tests — ExaminationSaveAPIView (POST)
# ---------------------------------------------------------------------------

class ExaminationSaveAPIViewTests(_ExamFixtures, TestCase):

    def setUp(self) -> None:
        self.user = User.objects.create_user("saveuser", password="pass")
        self.client.force_login(self.user)
        self.scanner = self._make_scanner(created_by="saveuser")
        self.protocol = self._make_protocol(self.scanner)

    def _post(self, payload: dict) -> "django.test.Response":  # type: ignore[name-defined]
        return self.client.post(
            reverse("examination-save-api"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _valid_payload(self, **overrides) -> dict:
        base = {
            "scanner_id": str(self.scanner.pk),
            "protocol_type": "PEDIATRIC_BODY",
            "examination_group": "Group 1 - Neonate",
            "anatomical_region": "Head",
            "clinical_indication": "Trauma",
            "patient_weight": 12.5,
            "patient_age": 5,
            "number_of_phases": 2,
            "ctdi_vol_per_phase": [3.1, 4.2],
            "dlp_per_phase": [50.0, 60.0],
            "image_quality": "GOOD",
        }
        base.update(overrides)
        return base

    def test_returns_401_json_when_unauthenticated(self) -> None:
        self.client.logout()
        resp = self._post(self._valid_payload())
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], "auth_required")

    def test_create_returns_201_or_200(self) -> None:
        resp = self._post(self._valid_payload())
        self.assertIn(resp.status_code, (200, 201))
        data = resp.json()
        self.assertEqual(data["status"], "created")

    def test_creates_db_record(self) -> None:
        self._post(self._valid_payload())
        self.assertEqual(CTExamination.objects.count(), 1)

    def test_created_by_set_to_logged_in_user(self) -> None:
        self._post(self._valid_payload())
        exam = CTExamination.objects.first()
        self.assertEqual(exam.created_by, "saveuser")

    def test_response_contains_id(self) -> None:
        resp = self._post(self._valid_payload())
        data = resp.json()
        self.assertIn("id", data)
        # must be a valid UUID string
        uuid.UUID(data["id"])

    def test_scanner_id_resolved(self) -> None:
        resp = self._post(self._valid_payload(scanner_id=str(self.scanner.pk)))
        self.assertEqual(resp.status_code, 200)
        exam = CTExamination.objects.first()
        self.assertEqual(exam.scanner_id, self.scanner.pk)

    def test_protocol_id_resolved(self) -> None:
        resp = self._post(self._valid_payload(protocol_id=str(self.protocol.pk)))
        self.assertEqual(resp.status_code, 200)
        exam = CTExamination.objects.first()
        self.assertEqual(exam.protocol_id, self.protocol.pk)

    def test_invalid_scanner_id_returns_404(self) -> None:
        resp = self._post(self._valid_payload(scanner_id=str(uuid.uuid4())))
        self.assertEqual(resp.status_code, 404)

    def test_invalid_protocol_id_returns_404(self) -> None:
        resp = self._post(self._valid_payload(protocol_id=str(uuid.uuid4())))
        self.assertEqual(resp.status_code, 404)

    def test_phase_mismatch_returns_400(self) -> None:
        resp = self._post(self._valid_payload(
            number_of_phases=3,
            ctdi_vol_per_phase=[1.0, 2.0],  # only 2, not 3
            dlp_per_phase=[10.0, 20.0, 30.0],
        ))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_dlp_mismatch_returns_400(self) -> None:
        resp = self._post(self._valid_payload(
            number_of_phases=2,
            ctdi_vol_per_phase=[1.0, 2.0],
            dlp_per_phase=[10.0],  # only 1
        ))
        self.assertEqual(resp.status_code, 400)

    def test_invalid_number_of_phases_zero_returns_400(self) -> None:
        resp = self._post(self._valid_payload(
            number_of_phases=0,
            ctdi_vol_per_phase=[],
            dlp_per_phase=[],
        ))
        self.assertEqual(resp.status_code, 400)

    def test_invalid_number_of_phases_string_returns_400(self) -> None:
        resp = self._post(self._valid_payload(
            number_of_phases="not_a_number",
        ))
        self.assertEqual(resp.status_code, 400)

    def test_decimal_patient_age_accepted(self) -> None:
        """A fractional age (e.g. 0.3 years for a newborn) must be accepted, not 500."""
        resp = self._post(self._valid_payload(patient_age=0.3))
        self.assertEqual(resp.status_code, 200)
        exam = CTExamination.objects.first()
        self.assertEqual(exam.patient_age, Decimal("0.30"))

    def test_invalid_patient_age_string_returns_400(self) -> None:
        resp = self._post(self._valid_payload(patient_age="not_a_number"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_out_of_range_patient_age_returns_400(self) -> None:
        resp = self._post(self._valid_payload(patient_age=200))
        self.assertEqual(resp.status_code, 400)

    def test_invalid_json_body_returns_400(self) -> None:
        resp = self.client.post(
            reverse("examination-save-api"),
            data="not json",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_protocol_null_by_default(self) -> None:
        resp = self._post(self._valid_payload())
        self.assertEqual(resp.status_code, 200)
        exam = CTExamination.objects.first()
        self.assertIsNone(exam.protocol)

    def test_missing_weight_returns_400(self) -> None:
        payload = self._valid_payload()
        payload.pop("patient_weight", None)
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("weight", resp.json()["error"].lower())

    def test_ctdi_and_dlp_values_persisted(self) -> None:
        self._post(self._valid_payload())
        exam = CTExamination.objects.first()
        self.assertEqual(exam.ctdi_vol_per_phase, [3.1, 4.2])
        self.assertEqual(exam.dlp_per_phase, [50.0, 60.0])

    def test_total_dlp_correct_after_save(self) -> None:
        self._post(self._valid_payload())
        exam = CTExamination.objects.first()
        self.assertAlmostEqual(exam.total_dlp, 110.0)

    def test_single_phase_save(self) -> None:
        resp = self._post(self._valid_payload(
            number_of_phases=1,
            ctdi_vol_per_phase=[5.5],
            dlp_per_phase=[88.0],
        ))
        self.assertEqual(resp.status_code, 200)
        exam = CTExamination.objects.first()
        self.assertEqual(exam.number_of_phases, 1)
        self.assertAlmostEqual(exam.total_dlp, 88.0)

    def test_image_quality_blank_returns_400(self) -> None:
        resp = self._post(self._valid_payload(image_quality=""))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("image quality", resp.json()["error"].lower())

    def test_multiple_saves_create_independent_records(self) -> None:
        self._post(self._valid_payload(patient_age=3))
        self._post(self._valid_payload(patient_age=7))
        self.assertEqual(CTExamination.objects.count(), 2)


# ---------------------------------------------------------------------------
# Functional tests — ExaminationListView (GET)
# ---------------------------------------------------------------------------

class ExaminationListViewTests(_ExamFixtures, TestCase):

    def setUp(self) -> None:
        self.user = User.objects.create_user("listuser", password="pass")
        self.client.force_login(self.user)
        self.scanner = self._make_scanner()

    def test_redirects_when_unauthenticated(self) -> None:
        self.client.logout()
        resp = self.client.get(reverse("examination-list"))
        self.assertIn(resp.status_code, (302, 301))

    def test_empty_list_returns_200(self) -> None:
        resp = self.client.get(reverse("examination-list"))
        self.assertEqual(resp.status_code, 200)

    def test_examination_region_shown(self) -> None:
        self._make_examination(self.scanner, anatomical_region="Chest", created_by="listuser")
        resp = self.client.get(reverse("examination-list"))
        self.assertIn(b"Chest", resp.content)

    def test_examination_indication_shown(self) -> None:
        self._make_examination(self.scanner, clinical_indication="Lymphoma", created_by="listuser")
        resp = self.client.get(reverse("examination-list"))
        self.assertIn(b"Lymphoma", resp.content)

    def test_image_quality_label_shown(self) -> None:
        self._make_examination(self.scanner, image_quality="EXCELLENT", created_by="listuser")
        resp = self.client.get(reverse("examination-list"))
        self.assertIn(b"Excellent", resp.content)

    def test_multiple_records_listed(self) -> None:
        self._make_examination(self.scanner, clinical_indication="Trauma", created_by="listuser")
        self._make_examination(self.scanner, clinical_indication="Lymphoma", created_by="listuser")
        resp = self.client.get(reverse("examination-list"))
        self.assertIn(b"Trauma", resp.content)
        self.assertIn(b"Lymphoma", resp.content)

    def test_filter_by_image_quality(self) -> None:
        self._make_examination(self.scanner, image_quality="EXCELLENT", clinical_indication="Trauma", created_by="listuser")
        self._make_examination(self.scanner, image_quality="POOR", clinical_indication="Lymphoma", created_by="listuser")
        resp = self.client.get(reverse("examination-list"), {"image_quality": "EXCELLENT"})
        self.assertIn(b"Excellent", resp.content)
        # "Lymphoma" appears only on the POOR record — it must be absent when filtering for EXCELLENT
        self.assertNotIn(b"Lymphoma", resp.content)

    def test_filter_returns_only_matching(self) -> None:
        self._make_examination(self.scanner, image_quality="GOOD", created_by="listuser")
        self._make_examination(self.scanner, image_quality="MODERATE", created_by="listuser")
        resp = self.client.get(reverse("examination-list"), {"image_quality": "GOOD"})
        self.assertEqual(resp.status_code, 200)
        exams = resp.context["examinations"]
        self.assertEqual(len(list(exams)), 1)

    def test_no_filter_shows_all(self) -> None:
        self._make_examination(self.scanner, image_quality="GOOD", created_by="listuser")
        self._make_examination(self.scanner, image_quality="POOR", created_by="listuser")
        resp = self.client.get(reverse("examination-list"))
        exams = resp.context["examinations"]
        self.assertEqual(len(list(exams)), 2)

    def test_delete_link_present(self) -> None:
        exam = self._make_examination(self.scanner, created_by="listuser")
        resp = self.client.get(reverse("examination-list"))
        delete_url = reverse("examination-delete", kwargs={"pk": str(exam.pk)})
        self.assertIn(delete_url.encode(), resp.content)

    def test_image_quality_choices_in_context(self) -> None:
        resp = self.client.get(reverse("examination-list"))
        choices = resp.context["image_quality_choices"]
        codes = [c[0] for c in choices]
        self.assertIn("EXCELLENT", codes)
        self.assertIn("POOR", codes)


# ---------------------------------------------------------------------------
# Functional tests — ExaminationDeleteView (GET + POST)
# ---------------------------------------------------------------------------

class ExaminationDeleteViewTests(_ExamFixtures, TestCase):

    def setUp(self) -> None:
        self.user = User.objects.create_user("deluser", password="pass")
        self.client.force_login(self.user)
        self.scanner = self._make_scanner()

    def _make_examination(self, scanner=None, protocol=None, **kwargs):
        kwargs.setdefault("created_by", "deluser")
        return super()._make_examination(scanner, protocol, **kwargs)

    def test_redirects_when_unauthenticated_get(self) -> None:
        exam = self._make_examination(self.scanner)
        self.client.logout()
        resp = self.client.get(reverse("examination-delete", kwargs={"pk": str(exam.pk)}))
        self.assertIn(resp.status_code, (302, 301))

    def test_confirm_page_returns_200(self) -> None:
        exam = self._make_examination(self.scanner)
        resp = self.client.get(reverse("examination-delete", kwargs={"pk": str(exam.pk)}))
        self.assertEqual(resp.status_code, 200)

    def test_confirm_page_shows_exam_info(self) -> None:
        exam = self._make_examination(self.scanner, anatomical_region="Pelvis")
        resp = self.client.get(reverse("examination-delete", kwargs={"pk": str(exam.pk)}))
        self.assertIn(b"Pelvis", resp.content)

    def test_get_with_invalid_pk_returns_404(self) -> None:
        resp = self.client.get(reverse("examination-delete", kwargs={"pk": str(uuid.uuid4())}))
        self.assertEqual(resp.status_code, 404)

    def test_post_deletes_record(self) -> None:
        exam = self._make_examination(self.scanner)
        pk = exam.pk
        self.client.post(reverse("examination-delete", kwargs={"pk": str(pk)}))
        self.assertFalse(CTExamination.objects.filter(pk=pk).exists())

    def test_post_redirects_to_list(self) -> None:
        exam = self._make_examination(self.scanner)
        resp = self.client.post(reverse("examination-delete", kwargs={"pk": str(exam.pk)}))
        self.assertRedirects(resp, reverse("examination-list"), fetch_redirect_response=False)

    def test_post_with_invalid_pk_returns_404(self) -> None:
        resp = self.client.post(reverse("examination-delete", kwargs={"pk": str(uuid.uuid4())}))
        self.assertEqual(resp.status_code, 404)

    def test_only_target_record_deleted(self) -> None:
        exam1 = self._make_examination(self.scanner, patient_age=3)
        exam2 = self._make_examination(self.scanner, patient_age=7)
        self.client.post(reverse("examination-delete", kwargs={"pk": str(exam1.pk)}))
        self.assertFalse(CTExamination.objects.filter(pk=exam1.pk).exists())
        self.assertTrue(CTExamination.objects.filter(pk=exam2.pk).exists())
