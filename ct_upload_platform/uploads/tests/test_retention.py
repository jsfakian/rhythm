"""
Tests for retention consent and end-of-project deletion:
  - parse_retention_consent / will_be_deleted_at_project_end
  - v2 manifest field retain_after_project (schema + pipeline mapping)
  - Manual Exam Entry save API stores the declaration
  - ExaminationRetentionView: change, audit log, institution scoping, redirects
  - Examinations list: summary counts and filter
  - OrthancClient.delete_study
  - purge_non_retained_examinations: dry run, safety checks, full deletion,
    Orthanc failure handling, retained studies untouched
"""
import csv
import json
import tempfile
import uuid
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from uploads.manifest_schema import validate_manifest_v2_item
from uploads.models import (
    RETENTION_DELETE,
    RETENTION_RETAIN,
    AuditLog,
    CTExamination,
    CTManufacturer,
    CTScannerModel,
    CTScannerProfile,
    Image,
    Patient,
    StudyMapping,
    UploadJob,
    UserProfile,
    parse_retention_consent,
)
from uploads.orthanc_client import OrthancClient, OrthancQueryError
from uploads.tasks import _retention_fields_from_item


def _user(username: str, site_code: str = "S001") -> User:
    user = User.objects.create_user(username, f"{username}@example.com", "pass12345")
    UserProfile.objects.create(
        user=user, institution="Test Hospital", professional_role="radiologist",
        terms_accepted=True, site_code=site_code,
    )
    return user


def _scanner() -> CTScannerProfile:
    mfr, _ = CTManufacturer.objects.get_or_create(name="GE Healthcare", defaults={"sort_order": 0})
    model, _ = CTScannerModel.objects.get_or_create(manufacturer=mfr, name="Revolution CT Ret")
    return CTScannerProfile.objects.create(manufacturer=mfr, scanner_model=model, site_code="S001")


def _exam(rid: str, consent: str = "", site_code: str = "S001", **kwargs) -> CTExamination:
    return CTExamination.objects.create(
        rhythm_pseudo_id=rid, retention_consent=consent, site_code=site_code,
        anatomical_region="Head", clinical_indication="Trauma", image_quality="GOOD",
        created_by="someone", **kwargs,
    )


def _v2_item(**overrides) -> dict:
    item = {
        "ref": "ROW0001",
        "filename": "study.zip",
        "site_code": "S001",
        "protocol_id": str(uuid.uuid4()),
        "image_quality": "GOOD",
    }
    item.update(overrides)
    return item


# ---------------------------------------------------------------------------
# Parsing and model semantics
# ---------------------------------------------------------------------------

class ParseRetentionConsentTests(TestCase):

    def test_booleans_map_to_codes(self) -> None:
        self.assertEqual(parse_retention_consent(True), RETENTION_RETAIN)
        self.assertEqual(parse_retention_consent(False), RETENTION_DELETE)

    def test_strings_map_to_codes(self) -> None:
        for value in ("RETAIN", "retain", "yes", "true", "1"):
            self.assertEqual(parse_retention_consent(value), RETENTION_RETAIN, value)
        for value in ("DELETE", "no", "false", "0"):
            self.assertEqual(parse_retention_consent(value), RETENTION_DELETE, value)

    def test_empty_means_default_retain(self) -> None:
        for value in (None, "", "   "):
            self.assertEqual(parse_retention_consent(value), RETENTION_RETAIN)

    def test_new_examination_defaults_to_retain(self) -> None:
        exam = CTExamination.objects.create(rhythm_pseudo_id="RHY-NEW", anatomical_region="Head")
        self.assertEqual(exam.retention_consent, RETENTION_RETAIN)
        self.assertFalse(exam.will_be_deleted_at_project_end)

    def test_unknown_value_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_retention_consent("maybe")

    def test_only_retain_survives_project_end(self) -> None:  # blank = legacy row
        self.assertFalse(_exam("RHY-A", RETENTION_RETAIN).will_be_deleted_at_project_end)
        self.assertTrue(_exam("RHY-B", RETENTION_DELETE).will_be_deleted_at_project_end)
        self.assertTrue(_exam("RHY-C", "").will_be_deleted_at_project_end)


# ---------------------------------------------------------------------------
# v2 manifest field
# ---------------------------------------------------------------------------

class ManifestRetentionFieldTests(TestCase):

    def test_schema_accepts_true_false_null_and_absent(self) -> None:
        for value in (True, False, None):
            self.assertEqual(validate_manifest_v2_item(_v2_item(retain_after_project=value)), [], value)
        self.assertEqual(validate_manifest_v2_item(_v2_item()), [])

    def test_schema_rejects_non_boolean(self) -> None:
        errors = validate_manifest_v2_item(_v2_item(retain_after_project="maybe"))
        self.assertTrue(errors)

    def test_pipeline_maps_item_to_fields(self) -> None:
        fields = _retention_fields_from_item({"retain_after_project": True}, "uploader")
        self.assertEqual(fields["retention_consent"], RETENTION_RETAIN)
        self.assertEqual(fields["retention_updated_by"], "uploader")
        self.assertIsNotNone(fields["retention_updated_at"])
        self.assertEqual(_retention_fields_from_item({"retain_after_project": False}, "u")["retention_consent"], RETENTION_DELETE)

    def test_pipeline_defaults_missing_or_bad_to_retain(self) -> None:
        for item in ({}, {"retain_after_project": None}, {"retain_after_project": "weird"}):
            # Default applied: RETAIN, and no "set by" (nobody declared it).
            self.assertEqual(_retention_fields_from_item(item, "u"), {"retention_consent": RETENTION_RETAIN}, item)


# ---------------------------------------------------------------------------
# Manual Exam Entry
# ---------------------------------------------------------------------------

class ManualEntryRetentionTests(TestCase):

    def setUp(self) -> None:
        self.user = _user("entryuser")
        self.client.force_login(self.user)
        self.scanner = _scanner()

    def _post(self, **extra):
        payload = {
            "scanner_id": str(self.scanner.pk), "protocol_type": "PEDIATRIC_BODY",
            "examination_group": "Group 1 - Neonate", "anatomical_region": "Head",
            "clinical_indication": "Trauma", "patient_weight": 12.5, "patient_age": 5,
            "number_of_phases": 1, "ctdi_vol_per_phase": [3.1], "dlp_per_phase": [50.0],
            "image_quality": "GOOD",
        }
        payload.update(extra)
        return self.client.post(reverse("examination-save-api"), data=json.dumps(payload),
                                content_type="application/json")

    def test_stores_declared_retention(self) -> None:
        resp = self._post(retention_consent="RETAIN")
        self.assertEqual(resp.status_code, 200, resp.content)
        exam = CTExamination.objects.get()
        self.assertEqual(exam.retention_consent, RETENTION_RETAIN)
        self.assertEqual(exam.retention_updated_by, "entryuser")
        self.assertIsNotNone(exam.retention_updated_at)

    def test_missing_retention_defaults_to_retain(self) -> None:
        resp = self._post()
        self.assertEqual(resp.status_code, 200, resp.content)
        exam = CTExamination.objects.get()
        self.assertEqual(exam.retention_consent, RETENTION_RETAIN)
        self.assertIsNone(exam.retention_updated_at)
        self.assertEqual(exam.retention_updated_by, "")

    def test_stores_explicit_delete(self) -> None:
        resp = self._post(retention_consent="DELETE")
        self.assertEqual(resp.status_code, 200, resp.content)
        exam = CTExamination.objects.get()
        self.assertEqual(exam.retention_consent, RETENTION_DELETE)
        self.assertEqual(exam.retention_updated_by, "entryuser")

    def test_rejects_unknown_retention_value(self) -> None:
        resp = self._post(retention_consent="perhaps")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(CTExamination.objects.exists())

    def test_entry_page_offers_retention_choice(self) -> None:
        resp = self.client.get(reverse("examination-entry"))
        self.assertContains(resp, 'id="sel_retention"')


# ---------------------------------------------------------------------------
# Changing retention from the Examinations list
# ---------------------------------------------------------------------------

class ExaminationRetentionViewTests(TestCase):

    def setUp(self) -> None:
        self.user = _user("colleague", "S001")
        self.client.force_login(self.user)
        self.exam = _exam("RHY-S001-HEADTRAUMA-NC-PH-G3-000001", RETENTION_RETAIN, site_code="S001")
        self.url = reverse("examination-retention", args=[self.exam.pk])

    def test_change_saves_and_audits(self) -> None:
        resp = self.client.post(self.url, {"retention_consent": "DELETE"})
        self.assertRedirects(resp, reverse("examination-list"), fetch_redirect_response=False)
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.retention_consent, RETENTION_DELETE)
        self.assertEqual(self.exam.retention_updated_by, "colleague")
        log = AuditLog.objects.get(event_type="RETENTION_SET")
        self.assertIsNone(log.upload_job)
        self.assertEqual(log.actor_id, "colleague")
        self.assertEqual(log.detail["from"], RETENTION_RETAIN)
        self.assertEqual(log.detail["to"], RETENTION_DELETE)
        self.assertEqual(log.detail["repository_study_id"], self.exam.rhythm_pseudo_id)

    def test_same_value_writes_no_audit(self) -> None:
        self.client.post(self.url, {"retention_consent": "RETAIN"})
        self.assertFalse(AuditLog.objects.filter(event_type="RETENTION_SET").exists())

    def test_unknown_value_changes_nothing(self) -> None:
        self.client.post(self.url, {"retention_consent": "nonsense"})
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.retention_consent, RETENTION_RETAIN)
        self.assertFalse(AuditLog.objects.exists())

    def test_other_institution_gets_404(self) -> None:
        self.client.force_login(_user("outsider", "S004"))
        resp = self.client.post(self.url, {"retention_consent": "DELETE"})
        self.assertEqual(resp.status_code, 404)
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.retention_consent, RETENTION_RETAIN)

    def test_get_not_allowed(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_redirects_back_to_filtered_list(self) -> None:
        nxt = reverse("examination-list") + "?retention=UNDECLARED"
        resp = self.client.post(self.url, {"retention_consent": "DELETE", "next": nxt})
        self.assertEqual(resp["Location"], nxt)

    def test_ignores_offsite_next(self) -> None:
        resp = self.client.post(self.url, {"retention_consent": "DELETE", "next": "https://evil.example/x"})
        self.assertEqual(resp["Location"], reverse("examination-list"))


class ExaminationListRetentionTests(TestCase):

    def setUp(self) -> None:
        self.client.force_login(_user("lister", "S001"))
        _exam("RHY-1", RETENTION_RETAIN)
        _exam("RHY-2", RETENTION_DELETE)
        _exam("RHY-3", "")
        _exam("RHY-4", "")
        _exam("RHY-OTHER", RETENTION_RETAIN, site_code="S004")

    def test_summary_counts_are_institution_scoped(self) -> None:
        resp = self.client.get(reverse("examination-list"))
        # Legacy blank rows count as "delete at end".
        self.assertEqual(resp.context["retention_counts"], {"retain": 1, "delete": 3})

    def test_filter_delete_includes_legacy_blank(self) -> None:
        resp = self.client.get(reverse("examination-list"), {"retention": "DELETE"})
        self.assertEqual(sorted(e.rhythm_pseudo_id for e in resp.context["examinations"]), ["RHY-2", "RHY-3", "RHY-4"])

    def test_filter_retain(self) -> None:
        resp = self.client.get(reverse("examination-list"), {"retention": "RETAIN"})
        self.assertEqual([e.rhythm_pseudo_id for e in resp.context["examinations"]], ["RHY-1"])

    def test_unknown_filter_is_ignored(self) -> None:
        resp = self.client.get(reverse("examination-list"), {"retention": "bogus"})
        self.assertEqual(len(resp.context["examinations"]), 4)
        self.assertEqual(resp.context["selected_retention"], "")


# ---------------------------------------------------------------------------
# OrthancClient.delete_study
# ---------------------------------------------------------------------------

def _response(status: int, payload=None, text: str = ""):
    r = mock.Mock(status_code=status, text=text)
    r.json.return_value = payload
    return r


class OrthancDeleteStudyTests(TestCase):

    def setUp(self) -> None:
        self.client_ = OrthancClient()
        self.client_.session = mock.Mock()

    def test_looks_up_uid_then_deletes(self) -> None:
        self.client_.session.post.return_value = _response(200, [{"Type": "Study", "ID": "abc-123"}])
        self.client_.session.delete.return_value = _response(200, {})
        self.assertTrue(self.client_.delete_study("1.2.3"))
        self.assertTrue(self.client_.session.post.call_args[0][0].endswith("/tools/lookup"))
        self.assertEqual(self.client_.session.post.call_args[1]["data"], "1.2.3")
        self.assertTrue(self.client_.session.delete.call_args[0][0].endswith("/studies/abc-123"))

    def test_unknown_study_returns_false(self) -> None:
        self.client_.session.post.return_value = _response(200, [])
        self.assertFalse(self.client_.delete_study("1.2.3"))
        self.client_.session.delete.assert_not_called()

    def test_blank_uid_does_nothing(self) -> None:
        self.assertFalse(self.client_.delete_study(""))
        self.client_.session.post.assert_not_called()

    def test_failed_delete_raises(self) -> None:
        self.client_.session.post.return_value = _response(200, [{"Type": "Study", "ID": "abc"}])
        self.client_.session.delete.return_value = _response(500, None, "boom")
        with self.assertRaises(OrthancQueryError):
            self.client_.delete_study("1.2.3")


# ---------------------------------------------------------------------------
# purge_non_retained_examinations
# ---------------------------------------------------------------------------

class PurgeCommandTests(TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.raw, self.processed, self.media, self.reports = (root / n for n in ("raw", "processed", "media", "reports"))
        for d in (self.raw, self.processed, self.media):
            d.mkdir()
        self.settings_override = override_settings(
            RAW_DATA_DIR=self.raw, PROCESSED_DATA_DIR=self.processed, MEDIA_ROOT=self.media,
        )
        self.settings_override.enable()

        self.keep = self._study("RHY-S001-KEEP-000001", RETENTION_RETAIN)
        self.drop = self._study("RHY-S001-DROP-000002", RETENTION_DELETE)
        self.undeclared = self._study("RHY-S004-UNDECL-000003", "", site_code="S004")

        self.orthanc = mock.Mock()
        self.orthanc.delete_study.return_value = True
        patcher = mock.patch(
            "uploads.management.commands.purge_non_retained_examinations.get_client",
            return_value=self.orthanc,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.settings_override.disable()
        self.tmp.cleanup()

    def _study(self, rid: str, consent: str, site_code: str = "S001") -> dict:
        archive = self.raw / f"{uuid.uuid4()}.zip"
        archive.write_bytes(b"zip")
        job = UploadJob.objects.create(uploader_id="u", site_code=site_code, status="COMPLETE",
                                       tar_temp_path=str(archive))
        extracted = self.processed / str(job.id)
        extracted.mkdir()
        (extracted / "IM0001.dcm").write_bytes(b"dcm")
        AuditLog.objects.create(upload_job=job, event_type="COMPLETE", actor_id="u")
        patient = Patient.objects.create(pseudo_id=rid)
        mapping = StudyMapping.objects.create(
            patient=patient, upload_job=job, pseudo_study_uid=f"1.2.{uuid.uuid4().int % 10**12}",
            orthanc_study_id=f"1.2.840.{uuid.uuid4().int % 10**12}", acquisition_date="2026-01-01",
            site_code=site_code,
        )
        Image.objects.create(study_mapping=mapping, filename="IM0001.dcm", orthanc_instance_id="x")
        exam = _exam(rid, consent, site_code=site_code, upload_job=job)
        return {"exam": exam, "job": job, "archive": archive, "extracted": extracted,
                "patient": patient, "mapping": mapping}

    def _run(self, *args) -> str:
        out = StringIO()
        call_command("purge_non_retained_examinations", *args, "--report-dir", str(self.reports), stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_new_default_examination_is_not_purged(self) -> None:
        fresh = CTExamination.objects.create(rhythm_pseudo_id="RHY-S001-FRESH-000009", site_code="S001")
        self._run("--execute", "--expected-count", "2")
        self.assertTrue(CTExamination.objects.filter(pk=fresh.pk).exists())

    def test_dry_run_deletes_nothing(self) -> None:
        out = self._run()
        self.assertIn("Examinations to delete: 2", out)
        self.assertIn("1 marked DELETE, 1 not declared", out)
        self.assertIn("--expected-count 2", out)
        self.assertEqual(CTExamination.objects.count(), 3)
        self.orthanc.delete_study.assert_not_called()
        self.assertTrue(self.drop["archive"].exists())

    def test_execute_requires_expected_count(self) -> None:
        with self.assertRaises(CommandError):
            self._run("--execute")
        self.assertEqual(CTExamination.objects.count(), 3)

    def test_execute_with_wrong_count_deletes_nothing(self) -> None:
        with self.assertRaises(CommandError):
            self._run("--execute", "--expected-count", "5")
        self.assertEqual(CTExamination.objects.count(), 3)
        self.orthanc.delete_study.assert_not_called()

    def test_execute_deletes_every_copy_and_keeps_retained(self) -> None:
        self._run("--execute", "--expected-count", "2", "--actor", "dpo")

        for s in (self.drop, self.undeclared):
            self.assertFalse(CTExamination.objects.filter(pk=s["exam"].pk).exists())
            self.assertFalse(UploadJob.objects.filter(pk=s["job"].pk).exists())
            self.assertFalse(StudyMapping.objects.filter(pk=s["mapping"].pk).exists())
            self.assertFalse(Patient.objects.filter(pk=s["patient"].pk).exists())
            self.assertFalse(s["archive"].exists())
            self.assertFalse(s["extracted"].exists())
            self.orthanc.delete_study.assert_any_call(s["mapping"].orthanc_study_id)

        # The retained study is untouched everywhere.
        self.assertTrue(CTExamination.objects.filter(pk=self.keep["exam"].pk).exists())
        self.assertTrue(StudyMapping.objects.filter(pk=self.keep["mapping"].pk).exists())
        self.assertTrue(self.keep["archive"].exists())
        self.assertEqual(Image.objects.count(), 1)
        self.assertNotIn(mock.call(self.keep["mapping"].orthanc_study_id), self.orthanc.delete_study.call_args_list)

        purged = AuditLog.objects.filter(event_type="STUDY_PURGED")
        self.assertEqual(purged.count(), 2)
        self.assertTrue(all(log.upload_job is None and log.actor_id == "dpo" for log in purged))
        self.assertEqual(
            sorted(log.detail["repository_study_id"] for log in purged),
            ["RHY-S001-DROP-000002", "RHY-S004-UNDECL-000003"],
        )

        with open(self.reports / "S004.csv") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows[0]["repository_study_id"], "RHY-S004-UNDECL-000003")
        self.assertEqual(rows[0]["retention_consent"], "NOT_DECLARED")
        self.assertEqual(rows[0]["result"], "DELETED")
        self.assertTrue((self.reports / "S001.csv").exists())

    def test_site_filter(self) -> None:
        self._run("--site", "S004", "--execute", "--expected-count", "1")
        self.assertFalse(CTExamination.objects.filter(pk=self.undeclared["exam"].pk).exists())
        self.assertTrue(CTExamination.objects.filter(pk=self.drop["exam"].pk).exists())

    def test_orthanc_failure_keeps_database_rows(self) -> None:
        self.orthanc.delete_study.side_effect = OrthancQueryError("down", 503, "")
        with self.assertRaises(CommandError):
            self._run("--execute", "--expected-count", "2")
        self.assertEqual(CTExamination.objects.count(), 3)
        self.assertEqual(StudyMapping.objects.count(), 3)
        self.assertTrue(self.drop["archive"].exists())
        self.assertFalse(AuditLog.objects.filter(event_type="STUDY_PURGED").exists())
        with open(self.reports / "S001.csv") as fh:
            self.assertEqual(next(csv.DictReader(fh))["result"], "FAILED")

    def test_never_deletes_files_outside_data_directories(self) -> None:
        outside = Path(self.tmp.name) / "elsewhere.zip"
        outside.write_bytes(b"precious")
        UploadJob.objects.filter(pk=self.drop["job"].pk).update(tar_temp_path=str(outside))
        self._run("--site", "S001", "--execute", "--expected-count", "1")
        self.assertTrue(outside.exists())
        self.assertFalse(CTExamination.objects.filter(pk=self.drop["exam"].pk).exists())
