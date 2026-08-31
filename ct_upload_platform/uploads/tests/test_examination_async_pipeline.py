"""
Tests for the Manual Exam Entry -> async GDPR/Orthanc pipeline retrofit.

When a study_set_file is attached to a manually-entered examination, it
must be queued through the same process_upload_job() pipeline used by
the automated/bulk upload route (instead of sitting on local disk with
no GDPR validation), reusing the examination's already-assigned
repository_study_id.
"""

import json
import zipfile
from io import BytesIO
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian

from uploads.models import CTExamination, UploadJob
from uploads.tasks import process_upload_job
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


def _build_compliant_zip_bytes(patient_id: str = None) -> bytes:
    """A GDPR-strict-compliant DICOM, zipped, as raw bytes — suitable as a
    study_set_file upload that the real async pipeline can actually
    process. `patient_id` is accepted for call-site compatibility but
    ignored: per the authoritative anonymization tool
    (github.com/jsfakian/dicom_anonymization), a properly-anonymized file
    has no PatientID at all — it isn't preserved as a pseudonym."""
    meta = Dataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset("slice.dcm", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()

    dcm_buf = BytesIO()
    ds.save_as(dcm_buf, enforce_file_format=True)
    dcm_bytes = dcm_buf.getvalue()

    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("slice.dcm", dcm_bytes)
    return zip_buf.getvalue()


class ManualEntryRealAsyncPipelineTests(_ExamFixtures, TestCase):
    """Runs the REAL process_upload_job (only Orthanc mocked) after a
    manual-entry save — every test above mocks process_upload_job.delay
    entirely, so the async task body (and this exact duplicate-creation
    bug) was never actually exercised by them."""

    def setUp(self) -> None:
        self.user = User.objects.create_user("realasyncuser", password="pass")
        self.client.force_login(self.user)
        self.scanner = self._make_scanner(created_by="realasyncuser")

    def test_real_pipeline_does_not_create_a_duplicate_examination(self) -> None:
        study_set_file = SimpleUploadedFile(
            "study.zip", _build_compliant_zip_bytes(), content_type="application/zip"
        )
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
            "study_set_file": study_set_file,
        }

        mock_orthanc = MagicMock()
        mock_orthanc.push_dicom_file.return_value = {"orthanc_study_id": "s1", "orthanc_instance_id": "i1"}

        with patch("uploads.tasks.get_client", return_value=mock_orthanc):
            resp = self.client.post(reverse("examination-save-api"), data=payload)
            self.assertEqual(resp.status_code, 200, resp.content)
            exam = CTExamination.objects.first()
            job_id = str(exam.upload_job.id)
            # Run the real Celery task body synchronously — this is exactly
            # what the worker does, just inline for the test.
            process_upload_job.apply(args=[job_id])

        # Regression: process_v2_batch_item used to unconditionally create
        # a second CTExamination for this same job, duplicating the one
        # ExaminationSaveAPIView already created synchronously.
        self.assertEqual(CTExamination.objects.filter(upload_job_id=job_id).count(), 1)

        exam.refresh_from_db()
        self.assertEqual(exam.pipeline_status, "COMPLETE")
