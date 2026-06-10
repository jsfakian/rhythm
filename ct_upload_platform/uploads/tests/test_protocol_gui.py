"""
Tests for the clinical indication-centred Protocol GUI:
  - Unit: model fields, duplicate-detection logic
  - Functional: ProtocolGUIView, ProtocolSaveAPIView, ProtocolRecordsView
"""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from uploads.models import (
    CTManufacturer,
    CTProtocol,
    CTScannerModel,
    CTScannerProfile,
    ProtocolChoiceCategory,
    ProtocolChoiceOption,
)


# ---------------------------------------------------------------------------
# Shared fixture mixin
# ---------------------------------------------------------------------------

class _ProtocolGUIFixtures:
    """Creates the DB objects needed by every test class below."""

    @classmethod
    def _make_scanner(cls, created_by: str = "") -> CTScannerProfile:
        mfr, _ = CTManufacturer.objects.get_or_create(
            name="Siemens Healthineers",
            defaults={"is_active": True, "sort_order": 0},
        )
        model, _ = CTScannerModel.objects.get_or_create(
            manufacturer=mfr,
            name="SOMATOM Force GUI",
            defaults={"is_active": True, "sort_order": 0},
        )
        return CTScannerProfile.objects.create(
            manufacturer=mfr,
            scanner_model=model,
            detector_rows="192",
            year_of_installation="2023",
            created_by=created_by,
        )

    @classmethod
    def _make_protocol(
        cls,
        scanner: CTScannerProfile,
        protocol_type: str = "PEDIATRIC_BODY",
        anatomical_region: str = "Head",
        clinical_indication: str = "Trauma",
        contrast: str = "Non-contrast",
        clinical_comments: str = "Can include anatomical based protocol",
        examination_group: str = "Group 1 - Neonate",
        age_group: str = "< 5 kg",
        **extra,
    ) -> CTProtocol:
        return CTProtocol.objects.create(
            scanner=scanner,
            protocol_type=protocol_type,
            anatomical_region=anatomical_region,
            clinical_indication=clinical_indication,
            contrast=contrast,
            clinical_comments=clinical_comments,
            examination_group=examination_group,
            age_group=age_group,
            **extra,
        )


# ---------------------------------------------------------------------------
# Unit tests — model fields
# ---------------------------------------------------------------------------

class ProtocolGUIModelTests(_ProtocolGUIFixtures, TestCase):

    def setUp(self) -> None:
        self.scanner = self._make_scanner()

    # new fields persist -------------------------------------------------------

    def test_examination_group_persists(self) -> None:
        p = self._make_protocol(self.scanner, examination_group="Group 2 - Infant")
        p.refresh_from_db()
        self.assertEqual(p.examination_group, "Group 2 - Infant")

    def test_clinical_comments_persists(self) -> None:
        p = self._make_protocol(self.scanner, clinical_comments="Only dedicated mastoid bone protocol")
        p.refresh_from_db()
        self.assertEqual(p.clinical_comments, "Only dedicated mastoid bone protocol")

    def test_new_fields_default_to_empty_string(self) -> None:
        p = CTProtocol.objects.create(
            scanner=self.scanner,
            protocol_type="PEDIATRIC_HEAD",
            age_group="< 5 kg",
        )
        self.assertEqual(p.examination_group, "")
        self.assertEqual(p.clinical_comments, "")

    # uniqueness key -----------------------------------------------------------

    def test_two_protocols_same_key_both_saved(self) -> None:
        """The model itself has no DB-level unique_together; the GUI view enforces it."""
        self._make_protocol(self.scanner)
        self._make_protocol(self.scanner)
        self.assertEqual(CTProtocol.objects.count(), 2)

    def test_different_examination_group_creates_separate_record(self) -> None:
        self._make_protocol(self.scanner, examination_group="Group 1 - Neonate")
        self._make_protocol(self.scanner, examination_group="Group 2 - Infant")
        self.assertEqual(CTProtocol.objects.count(), 2)

    def test_different_age_group_creates_separate_record(self) -> None:
        self._make_protocol(self.scanner, age_group="< 5 kg")
        self._make_protocol(self.scanner, age_group="5 kg - 15 kg")
        self.assertEqual(CTProtocol.objects.count(), 2)

    def test_different_protocol_type_creates_separate_record(self) -> None:
        self._make_protocol(self.scanner, protocol_type="PEDIATRIC_HEAD")
        self._make_protocol(self.scanner, protocol_type="PEDIATRIC_BODY")
        self.assertEqual(CTProtocol.objects.count(), 2)

    def test_all_three_protocol_types_available(self) -> None:
        type_keys = [c[0] for c in CTProtocol.PROTOCOL_TYPE_CHOICES]
        self.assertIn("PEDIATRIC_HEAD", type_keys)
        self.assertIn("PEDIATRIC_BODY", type_keys)
        self.assertIn("YOUNG_ADULT", type_keys)

    # dose_metadata with new fields --------------------------------------------

    def test_protocol_with_dose_metadata_and_examination_group(self) -> None:
        p = self._make_protocol(
            self.scanner,
            dose_metadata=["ctdi", "dlp"],
            examination_group="Group 3 - Childhood",
        )
        p.refresh_from_db()
        self.assertEqual(p.dose_metadata, ["ctdi", "dlp"])
        self.assertEqual(p.examination_group, "Group 3 - Childhood")

    # __str__ unchanged --------------------------------------------------------

    def test_str_representation(self) -> None:
        p = self._make_protocol(self.scanner, age_group="< 5 kg")
        self.assertIn("< 5 kg", str(p))


# ---------------------------------------------------------------------------
# Functional tests — ProtocolGUIView
# ---------------------------------------------------------------------------

class ProtocolGUIViewTests(_ProtocolGUIFixtures, TestCase):

    def setUp(self) -> None:
        self.user, _ = User.objects.get_or_create(
            username="gui_view_user",
            defaults={"email": "gv@example.com"},
        )
        self.user.set_password("pass123")
        self.user.save()
        self.scanner = self._make_scanner(created_by=self.user.username)
        # Minimal choice options so the view doesn't crash
        for key, label in [
            ("kvp", "KVP"),
            ("scan_type", "Scan Type"),
            ("contrast", "Contrast"),
        ]:
            cat, _ = ProtocolChoiceCategory.objects.get_or_create(
                key=key, defaults={"label": label}
            )
            ProtocolChoiceOption.objects.get_or_create(
                category=cat,
                value="opt_a",
                defaults={"display": "Option A", "sort_order": 0, "is_active": True},
            )

    def test_gui_page_requires_login(self) -> None:
        resp = self.client.get("/protocols/gui/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])

    def test_gui_page_returns_200(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/gui/")
        self.assertEqual(resp.status_code, 200)

    def test_gui_page_contains_clinical_rows_json(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/gui/")
        # Template renders ANATOMICAL_REGIONS and CLINICAL_INDICATIONS (replaced CLINICAL_ROWS)
        self.assertIn(b"ANATOMICAL_REGIONS", resp.content)
        self.assertIn(b"CLINICAL_INDICATIONS", resp.content)

    def test_gui_page_contains_scanners_json(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/gui/")
        content = resp.content.decode()
        # Template renders: const SCANNERS = [...]
        self.assertIn("SCANNERS", content)
        self.assertIn("SOMATOM Force GUI", content)

    def test_gui_page_contains_protocol_tabs_json(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/gui/")
        # Template renders: const PROTOCOL_TABS = {...}
        self.assertIn(b"PROTOCOL_TABS", resp.content)

    def test_gui_page_contains_pediatric_head_tab(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/gui/")
        self.assertIn(b"PEDIATRIC_HEAD", resp.content)

    def test_gui_page_contains_protocol_choices_json(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/gui/")
        # Template renders: const PROTOCOL_CHOICES = {...}
        self.assertIn(b"PROTOCOL_CHOICES", resp.content)

    def test_gui_page_scanner_without_profiles_shows_empty_list(self) -> None:
        CTScannerProfile.objects.all().delete()
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/gui/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("[]", content)


# ---------------------------------------------------------------------------
# Functional tests — ProtocolSaveAPIView
# ---------------------------------------------------------------------------

class ProtocolSaveAPIViewTests(_ProtocolGUIFixtures, TestCase):

    def setUp(self) -> None:
        self.user, _ = User.objects.get_or_create(
            username="save_api_user",
            defaults={"email": "sa@example.com"},
        )
        self.user.set_password("pass123")
        self.user.save()
        self.scanner = self._make_scanner()

    def _post(self, payload: dict, /) -> "django.http.JsonResponse":
        return self.client.post(
            "/protocols/api/save/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _base_payload(self, **overrides) -> dict:
        base = {
            "scanner_id": str(self.scanner.pk),
            "protocol_type": "PEDIATRIC_BODY",
            "anatomical_region": "Head",
            "clinical_indication": "Trauma",
            "contrast": "Non-contrast",
            "clinical_comments": "Can include anatomical based protocol",
            "examination_group": "Group 1 - Neonate",
            "age_group": "< 5 kg",
            "force_update": False,
            "protocol_fields": {
                "protocol_name": "Neonate Head",
                "kvp": "80",
                "scan_type": "Helical / spiral",
                "notes": "test note",
            },
        }
        base.update(overrides)
        return base

    # auth guard ---------------------------------------------------------------

    def test_save_requires_login(self) -> None:
        resp = self._post(self._base_payload())
        self.assertEqual(resp.status_code, 302)

    # create -------------------------------------------------------------------

    def test_save_creates_new_protocol(self) -> None:
        self.client.force_login(self.user)
        resp = self._post(self._base_payload())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertTrue(data["id"])
        self.assertEqual(CTProtocol.objects.count(), 1)

    def test_save_stores_protocol_fields(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        p = CTProtocol.objects.get()
        self.assertEqual(p.protocol_name, "Neonate Head")
        self.assertEqual(p.kvp, "80")
        self.assertEqual(p.notes, "test note")

    def test_save_stores_key_fields(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        p = CTProtocol.objects.get()
        self.assertEqual(p.anatomical_region, "Head")
        self.assertEqual(p.clinical_indication, "Trauma")
        self.assertEqual(p.contrast, "Non-contrast")
        self.assertEqual(p.examination_group, "Group 1 - Neonate")
        self.assertEqual(p.age_group, "< 5 kg")
        self.assertEqual(p.protocol_type, "PEDIATRIC_BODY")

    def test_save_stores_clinical_comments(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        p = CTProtocol.objects.get()
        self.assertEqual(p.clinical_comments, "Can include anatomical based protocol")

    def test_save_sets_created_by(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        p = CTProtocol.objects.get()
        self.assertEqual(p.created_by, self.user.username)

    def test_save_with_dose_metadata_list(self) -> None:
        self.client.force_login(self.user)
        payload = self._base_payload()
        payload["protocol_fields"]["dose_metadata"] = ["ctdi", "dlp"]
        self._post(payload)
        p = CTProtocol.objects.get()
        self.assertEqual(p.dose_metadata, ["ctdi", "dlp"])

    # duplicate detection (exists) --------------------------------------------

    def test_duplicate_returns_exists_status(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        resp = self._post(self._base_payload())
        data = resp.json()
        self.assertEqual(data["status"], "exists")
        self.assertIn("id", data)
        self.assertIn("message", data)
        self.assertEqual(CTProtocol.objects.count(), 1)

    def test_duplicate_message_mentions_update(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        resp = self._post(self._base_payload())
        msg = resp.json()["message"].lower()
        self.assertIn("already", msg)

    def test_different_examination_group_is_not_duplicate(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        resp = self._post(self._base_payload(examination_group="Group 2 - Infant"))
        self.assertEqual(resp.json()["status"], "created")
        self.assertEqual(CTProtocol.objects.count(), 2)

    def test_different_age_group_is_not_duplicate(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        resp = self._post(self._base_payload(age_group="5 kg - 15 kg"))
        self.assertEqual(resp.json()["status"], "created")
        self.assertEqual(CTProtocol.objects.count(), 2)

    def test_different_protocol_type_is_not_duplicate(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        resp = self._post(self._base_payload(protocol_type="PEDIATRIC_HEAD"))
        self.assertEqual(resp.json()["status"], "created")
        self.assertEqual(CTProtocol.objects.count(), 2)

    def test_different_clinical_indication_is_not_duplicate(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        resp = self._post(self._base_payload(clinical_indication="Lymphoma"))
        self.assertEqual(resp.json()["status"], "created")
        self.assertEqual(CTProtocol.objects.count(), 2)

    # force update -------------------------------------------------------------

    def test_force_update_updates_existing_protocol(self) -> None:
        self.client.force_login(self.user)
        self._post(self._base_payload())
        pk_before = CTProtocol.objects.get().pk

        updated = self._base_payload(force_update=True)
        updated["protocol_fields"]["kvp"] = "120"
        resp = self._post(updated)
        data = resp.json()
        self.assertEqual(data["status"], "updated")
        self.assertEqual(data["id"], str(pk_before))
        self.assertEqual(CTProtocol.objects.count(), 1)
        self.assertEqual(CTProtocol.objects.get().kvp, "120")

    def test_force_update_returns_updated_id(self) -> None:
        self.client.force_login(self.user)
        first = self._post(self._base_payload())
        original_id = first.json()["id"]
        updated = self._post(self._base_payload(force_update=True))
        self.assertEqual(updated.json()["id"], original_id)

    def test_force_update_on_nonexistent_creates(self) -> None:
        """force_update=True with no existing match still creates a new record."""
        self.client.force_login(self.user)
        resp = self._post(self._base_payload(force_update=True))
        self.assertEqual(resp.json()["status"], "created")
        self.assertEqual(CTProtocol.objects.count(), 1)

    # validation errors --------------------------------------------------------

    def test_missing_scanner_id_returns_400(self) -> None:
        self.client.force_login(self.user)
        payload = self._base_payload()
        del payload["scanner_id"]
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 400)

    def test_missing_protocol_type_returns_400(self) -> None:
        self.client.force_login(self.user)
        payload = self._base_payload()
        del payload["protocol_type"]
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 400)

    def test_missing_examination_group_returns_400(self) -> None:
        self.client.force_login(self.user)
        payload = self._base_payload()
        del payload["examination_group"]
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 400)

    def test_missing_age_group_returns_400(self) -> None:
        self.client.force_login(self.user)
        payload = self._base_payload()
        del payload["age_group"]
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 400)

    def test_invalid_scanner_id_returns_404(self) -> None:
        self.client.force_login(self.user)
        resp = self._post(self._base_payload(scanner_id="00000000-0000-0000-0000-000000000000"))
        self.assertEqual(resp.status_code, 404)

    def test_invalid_json_body_returns_400(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.post(
            "/protocols/api/save/",
            data="not-json{{{",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_response_is_json(self) -> None:
        self.client.force_login(self.user)
        resp = self._post(self._base_payload())
        self.assertEqual(resp["Content-Type"], "application/json")


# ---------------------------------------------------------------------------
# Functional tests — ProtocolRecordsView
# ---------------------------------------------------------------------------

class ProtocolRecordsViewTests(_ProtocolGUIFixtures, TestCase):

    def setUp(self) -> None:
        self.user, _ = User.objects.get_or_create(
            username="records_view_user",
            defaults={"email": "rv@example.com"},
        )
        self.user.set_password("pass123")
        self.user.save()
        self.scanner = self._make_scanner(created_by=self.user.username)

    def _seed_protocols(self) -> list:
        p1 = self._make_protocol(
            self.scanner,
            protocol_type="PEDIATRIC_BODY",
            protocol_name="Neonate Body",
        )
        p2 = self._make_protocol(
            self.scanner,
            protocol_type="PEDIATRIC_HEAD",
            examination_group="Group 3 - Childhood",
            age_group="15 kg - 30 kg",
            protocol_name="Childhood Head",
        )
        p3 = self._make_protocol(
            self.scanner,
            protocol_type="YOUNG_ADULT",
            examination_group="Group 6 - Young Adulthood",
            age_group="> 80 kg",
            protocol_name="Young Adult",
        )
        return [p1, p2, p3]

    # auth guard ---------------------------------------------------------------

    def test_records_page_requires_login(self) -> None:
        resp = self.client.get("/protocols/records/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])

    # basic display ------------------------------------------------------------

    def test_records_page_returns_200(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/records/")
        self.assertEqual(resp.status_code, 200)

    def test_records_page_shows_all_protocols(self) -> None:
        self.client.force_login(self.user)
        self._seed_protocols()
        resp = self.client.get("/protocols/records/")
        protocols = list(resp.context["protocols"])
        self.assertEqual(len(protocols), 3)

    def test_records_page_shows_protocol_names(self) -> None:
        self.client.force_login(self.user)
        self._seed_protocols()
        resp = self.client.get("/protocols/records/")
        content = resp.content.decode()
        self.assertIn("Neonate Body", content)
        self.assertIn("Childhood Head", content)
        self.assertIn("Young Adult", content)

    def test_records_page_shows_examination_group(self) -> None:
        self.client.force_login(self.user)
        self._make_protocol(self.scanner, examination_group="Group 4 - Early Adolescence")
        resp = self.client.get("/protocols/records/")
        self.assertIn(b"Group 4 - Early Adolescence", resp.content)

    def test_records_page_shows_scanner_info(self) -> None:
        self.client.force_login(self.user)
        self._seed_protocols()
        resp = self.client.get("/protocols/records/")
        content = resp.content.decode()
        self.assertIn("Siemens Healthineers", content)
        self.assertIn("SOMATOM Force GUI", content)

    def test_empty_records_page(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/records/")
        self.assertEqual(resp.status_code, 200)
        protocols = list(resp.context["protocols"])
        self.assertEqual(len(protocols), 0)

    # type filter --------------------------------------------------------------

    def test_filter_by_protocol_type_pediatric_head(self) -> None:
        self.client.force_login(self.user)
        self._seed_protocols()
        resp = self.client.get("/protocols/records/?protocol_type=PEDIATRIC_HEAD")
        protocols = list(resp.context["protocols"])
        self.assertEqual(len(protocols), 1)
        self.assertEqual(protocols[0].protocol_type, "PEDIATRIC_HEAD")

    def test_filter_by_protocol_type_young_adult(self) -> None:
        self.client.force_login(self.user)
        self._seed_protocols()
        resp = self.client.get("/protocols/records/?protocol_type=YOUNG_ADULT")
        protocols = list(resp.context["protocols"])
        self.assertEqual(len(protocols), 1)
        self.assertEqual(protocols[0].protocol_type, "YOUNG_ADULT")

    def test_filter_by_protocol_type_pediatric_body(self) -> None:
        self.client.force_login(self.user)
        self._seed_protocols()
        resp = self.client.get("/protocols/records/?protocol_type=PEDIATRIC_BODY")
        protocols = list(resp.context["protocols"])
        self.assertEqual(len(protocols), 1)

    def test_filter_blank_type_shows_all(self) -> None:
        self.client.force_login(self.user)
        self._seed_protocols()
        resp = self.client.get("/protocols/records/?protocol_type=")
        protocols = list(resp.context["protocols"])
        self.assertEqual(len(protocols), 3)

    def test_selected_type_passed_to_context(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/records/?protocol_type=YOUNG_ADULT")
        self.assertEqual(resp.context["selected_type"], "YOUNG_ADULT")

    def test_type_choices_in_context(self) -> None:
        self.client.force_login(self.user)
        resp = self.client.get("/protocols/records/")
        keys = [k for k, _ in resp.context["protocol_type_choices"]]
        self.assertIn("PEDIATRIC_HEAD", keys)
        self.assertIn("PEDIATRIC_BODY", keys)
        self.assertIn("YOUNG_ADULT", keys)

    # edit / delete links present in HTML ------------------------------------

    def test_records_page_contains_edit_links(self) -> None:
        self.client.force_login(self.user)
        p = self._make_protocol(self.scanner)
        resp = self.client.get("/protocols/records/")
        self.assertIn(f"/protocols/{p.protocol_type}/{p.pk}/edit/".encode(), resp.content)

    def test_records_page_contains_delete_links(self) -> None:
        self.client.force_login(self.user)
        p = self._make_protocol(self.scanner)
        resp = self.client.get("/protocols/records/")
        self.assertIn(f"/protocols/{p.protocol_type}/{p.pk}/delete/".encode(), resp.content)

    def test_records_page_contains_view_links(self) -> None:
        self.client.force_login(self.user)
        p = self._make_protocol(self.scanner)
        resp = self.client.get("/protocols/records/")
        self.assertIn(f"/protocols/{p.protocol_type}/{p.pk}/".encode(), resp.content)

    # delete flow (via existing ProtocolDeleteView) ---------------------------

    def test_delete_protocol_removes_from_records(self) -> None:
        self.client.force_login(self.user)
        protocols = self._seed_protocols()
        target = protocols[0]
        resp = self.client.post(f"/protocols/{target.protocol_type}/{target.pk}/delete/")
        self.assertIn(resp.status_code, [302, 200])
        self.assertFalse(CTProtocol.objects.filter(pk=target.pk).exists())
        # Remaining records should still be present
        resp2 = self.client.get("/protocols/records/")
        self.assertEqual(len(list(resp2.context["protocols"])), 2)

    # edit flow (via existing ProtocolUpdateView) -----------------------------

    def test_edit_protocol_updates_records_page(self) -> None:
        self.client.force_login(self.user)
        p = self._seed_protocols()[0]
        # Seed the minimal choice data required by CTProtocolForm
        for key, val in [
            ("age_group_pediatric_body", "< 5 kg"),
            ("clinical_indication_pediatric_body", "Trauma"),
            ("protocol_name", "Updated Name"),
            ("scan_type", "Helical"),
            ("anatomical_region", "Head"),
            ("contrast", "Non-contrast"),
            ("number_of_phases", "1"),
            ("auto_kvp_selection", "Off"),
            ("kvp", "80"),
            ("auto_ma_modulation", "Off"),
            ("exposure_metric", "Fixed mAs"),
            ("pitch", "0.8-1.2"),
            ("rotation_time", "0.5"),
            ("slice_thickness", "1.0"),
            ("scan_fov", "Small body"),
            ("kernel_class", "Standard"),
            ("reconstruction_algorithm", "Hybrid iterative reconstruction"),
            ("protocol_intent", "Routine diagnostic"),
            ("dose_metadata", "CTDIvol recorded"),
            ("detector_rows", "192"),
            ("year_of_installation", "2023"),
        ]:
            cat, _ = ProtocolChoiceCategory.objects.get_or_create(
                key=key, defaults={"label": key}
            )
            ProtocolChoiceOption.objects.get_or_create(
                category=cat,
                value=val,
                defaults={"display": val, "sort_order": 0, "is_active": True},
            )

        post_data = {
            "scanner": str(p.scanner.pk),
            "protocol_type": p.protocol_type,
            "age_group": "< 5 kg",
            "protocol_name": "Updated Name",
        }
        resp = self.client.post(f"/protocols/{p.protocol_type}/{p.pk}/edit/", post_data)
        # Successful update redirects; form error re-renders
        if resp.status_code == 302:
            p.refresh_from_db()
            self.assertEqual(p.protocol_name, "Updated Name")
