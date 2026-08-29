"""
Tests for the Manual Exam Entry -> async GDPR/Orthanc pipeline retrofit.

When a study_set_file is attached to a manually-entered examination, it
must be queued through the same process_upload_job() pipeline used by
the automated/bulk upload route (instead of sitting on local disk with
no GDPR validation), reusing the examination's already-assigned
repository_study_id.
"""

import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from uploads.models import CTExamination, UploadJob
from uploads.tests.test_examination import _ExamFixtures


class ManualEntryAsyncPipelineTests(_ExamFixtures, TestCase):

    def setUp(self) -> None:
        self.user = User.objects.create_user("asyncuser", password="pass")
        self.client.force_login(self.user)
        self.scanner = self._make_scanner(created_by="asyncuser")

    def _post_multipart(self, **overrides) -> "django.test.Response":  # type: ignore[name-defined]
        payload = {
            "scanner_id": str(self.scanner.pk),
            "protocol_type": "PEDIATRIC_BODY",
            "examination_group": "Group 1 - Neonate",
            "anatomical_region": "Head",
            "clinical_indication": "Trauma",
            "patient_weight": "12.5",
            "patient_age": "5",
            "number_of_phases": "1",
            "ctdi_vol_per_phase": json.dumps([3.1]),
            "dlp_per_phase": json.dumps([50.0]),
            "image_quality": "GOOD",
        }
        payload.update(overrides)
        return self.client.post(reverse("examination-save-api"), data=payload)

    def test_no_file_does_not_create_upload_job(self) -> None:
        with patch("uploads.protocol_views.process_upload_job.delay") as mock_delay:
            resp = self._post_multipart()
        self.assertEqual(resp.status_code, 400)  # study_set_file is required
        mock_delay.assert_not_called()

    def test_attached_file_queues_upload_job(self) -> None:
        study_set_file = SimpleUploadedFile("study.zip", b"dummy zip bytes", content_type="application/zip")
        with patch("uploads.protocol_views.process_upload_job.delay") as mock_delay:
            resp = self._post_multipart(study_set_file=study_set_file)
        self.assertEqual(resp.status_code, 200)
        exam = CTExamination.objects.first()
        self.assertIsNotNone(exam.upload_job)
        mock_delay.assert_called_once_with(str(exam.upload_job.id))

    def test_upload_job_manifest_reuses_repository_study_id(self) -> None:
        study_set_file = SimpleUploadedFile("study.zip", b"dummy zip bytes", content_type="application/zip")
        with patch("uploads.protocol_views.process_upload_job.delay"):
            self._post_multipart(study_set_file=study_set_file)
        exam = CTExamination.objects.first()
        job = exam.upload_job
        self.assertEqual(job.manifest_raw["repository_study_id_override"], exam.rhythm_pseudo_id)
        self.assertEqual(job.manifest_raw["patient_weight_kg"], 12.5)
        self.assertEqual(job.manifest_raw["patient_age_years"], 5.0)

    def test_upload_job_status_starts_pending(self) -> None:
        study_set_file = SimpleUploadedFile("study.zip", b"dummy zip bytes", content_type="application/zip")
        with patch("uploads.protocol_views.process_upload_job.delay"):
            self._post_multipart(study_set_file=study_set_file)
        exam = CTExamination.objects.first()
        self.assertEqual(exam.upload_job.status, "PENDING")

    def test_pipeline_status_property_reflects_job(self) -> None:
        study_set_file = SimpleUploadedFile("study.zip", b"dummy zip bytes", content_type="application/zip")
        with patch("uploads.protocol_views.process_upload_job.delay"):
            self._post_multipart(study_set_file=study_set_file)
        exam = CTExamination.objects.first()
        self.assertEqual(exam.pipeline_status, "PENDING")
        exam.upload_job.status = "COMPLETE"
        exam.upload_job.save()
        exam.refresh_from_db()
        self.assertEqual(exam.pipeline_status, "COMPLETE")

    def test_no_upload_job_pipeline_status_is_dash(self) -> None:
        exam = self._make_examination(self.scanner)
        self.assertEqual(exam.pipeline_status, "—")

    def test_queueing_failure_does_not_break_save(self) -> None:
        """If Celery/queuing fails for any reason, the examination save
        itself must still succeed — ingestion queuing is best-effort."""
        study_set_file = SimpleUploadedFile("study.zip", b"dummy zip bytes", content_type="application/zip")
        with patch("uploads.protocol_views.process_upload_job.delay", side_effect=RuntimeError("broker down")):
            resp = self._post_multipart(study_set_file=study_set_file)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(CTExamination.objects.count(), 1)
