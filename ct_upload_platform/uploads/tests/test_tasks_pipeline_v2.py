"""
Tests for the v2 (server-assigned batch) pipeline in uploads/tasks.py.

Covers process_v2_batch_item(), reached via process_upload_job() when
job.manifest_raw looks like a v2 manifest item (produced by the
create_rhythm_server_assigned_manifest_gui[_with_uid].py partner tools).
"""

import os
import shutil
import tempfile
import zipfile
from unittest.mock import patch, MagicMock

from django.test import TestCase

from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian

from uploads.models import (
    UploadJob,
    Patient,
    StudyMapping,
    CTExamination,
    CTManufacturer,
    CTProtocol,
    CTScannerModel,
    CTScannerProfile,
    Image,
)
from uploads.orthanc_client import OrthancPushError
from uploads.tasks import process_upload_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_dicom_file(path: str, patient_id: str = "PARTNERPAT001", study_uid: str = None) -> str:
    meta = Dataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientID = patient_id
    ds.StudyDate = "20240115"
    ds.save_as(path)
    return path


def _build_v2_zip(tmpdir: str, patient_id: str = "PARTNERPAT001", n_files: int = 1, study_uid: str = None) -> str:
    """Build a ZIP archive containing n_files DICOM instances of one study,
    matching the shape of an already-anonymized partner-supplied studyset."""
    src = tempfile.mkdtemp()
    study_uid = study_uid or generate_uid()
    for i in range(n_files):
        _create_dicom_file(os.path.join(src, f"slice_{i:03d}.dcm"), patient_id=patient_id, study_uid=study_uid)

    zip_path = os.path.join(tmpdir, "Input_volume1.zip")
    with zipfile.ZipFile(zip_path, "w") as z:
        for i in range(n_files):
            z.write(os.path.join(src, f"slice_{i:03d}.dcm"), arcname=f"slice_{i:03d}.dcm")

    shutil.rmtree(src)
    return zip_path


def _make_default_protocol(**overrides) -> CTProtocol:
    """A registered CTProtocol matching the RHY-S001-HEADTRAUMA-NC-PH-G4-
    prefix _v2_item()'s defaults expect: site S001, "Head / Trauma" (->
    HEADTRAUMA), "Non-contrast" (-> NC), PEDIATRIC_HEAD + "Group 4" (-> PH-G4)."""
    mfr, _ = CTManufacturer.objects.get_or_create(
        name="GE Healthcare", defaults={"is_active": True, "sort_order": 0},
    )
    model, _ = CTScannerModel.objects.get_or_create(
        manufacturer=mfr, name="Revolution CT", defaults={"is_active": True, "sort_order": 0},
    )
    scanner, _ = CTScannerProfile.objects.get_or_create(
        manufacturer=mfr, scanner_model=model, defaults={"detector_rows": "256"},
    )
    fields = {
        "scanner": scanner,
        "site_code": "S001",
        "protocol_type": "PEDIATRIC_HEAD",
        "anatomical_region": "Head",
        "clinical_indication": "Trauma",
        "contrast": "Non-contrast",
        "examination_group": "Group 4",
        "age_group": "30 kg – 50 kg",
        "protocol_name": "Pediatric head trauma non-contrast",
    }
    fields.update(overrides)
    return CTProtocol.objects.create(**fields)


def _v2_item(protocol: CTProtocol | None = None, **overrides) -> dict:
    if protocol is None and "protocol_id" not in overrides:
        protocol = _make_default_protocol()
    item = {
        "ref": "ROW0001",
        "filename": "Input_volume1.zip",
        "site_code": "S001",
        "protocol_id": str(protocol.pk) if protocol else None,
        "patient_weight_kg": 28.0,
        "patient_age_years": 8.0,
        "ctdivol_mgy": 18.4,
        "dlp_mgy_cm": 320.5,
        "image_quality": "Acceptable",
    }
    item.update(overrides)
    return item


def _make_v2_job(zip_path: str, item: dict) -> UploadJob:
    return UploadJob.objects.create(
        uploader_id="test_user",
        site_code="S001",
        tar_temp_path=zip_path,
        manifest_raw=item,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class ProcessV2BatchItemSuccessTests(TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.extract_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.extract_dir, ignore_errors=True)

    def _run(self, job):
        mock_orthanc = MagicMock()
        mock_orthanc.push_dicom_file.return_value = {"orthanc_study_id": "orthanc-1", "orthanc_instance_id": "orthanc-inst-1"}
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir), \
             patch("uploads.tasks.validate_gdpr_anonymization", return_value=(True, [])), \
             patch("uploads.tasks.get_client", return_value=mock_orthanc):
            process_upload_job.apply(args=[str(job.pk)])
        return mock_orthanc

    def test_job_status_complete(self):
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item())
        self._run(job)
        job.refresh_from_db()
        self.assertEqual(job.status, "COMPLETE")

    def test_patient_created_with_repository_study_id_not_dicom_patient_id(self):
        """Regression: Patient identity is keyed by the platform's own
        repository_study_id, never by the partner-supplied DICOM
        PatientID — a real partner tool once wrote the same literal
        placeholder ("PID1") for every patient, which would have merged
        distinct real patients into one Patient record under the old
        scheme. The DICOM's own PatientID (here "PARTNERPAT001") must not
        become a Patient record at all."""
        zip_path = _build_v2_zip(self.tmpdir, patient_id="PARTNERPAT001")
        job = _make_v2_job(zip_path, _v2_item())
        self._run(job)
        exam = CTExamination.objects.first()
        self.assertIsNotNone(exam)
        self.assertTrue(Patient.objects.filter(pseudo_id=exam.rhythm_pseudo_id).exists())
        self.assertFalse(Patient.objects.filter(pseudo_id="PARTNERPAT001").exists())

    def test_study_mapping_created(self):
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item())
        self._run(job)
        self.assertEqual(StudyMapping.objects.count(), 1)
        mapping = StudyMapping.objects.first()
        self.assertEqual(mapping.upload_job_id, job.id)
        self.assertEqual(mapping.contrast_used, False)

    def test_ctexamination_created_with_manifest_fields(self):
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item())
        self._run(job)
        exam = CTExamination.objects.first()
        self.assertIsNotNone(exam)
        self.assertEqual(exam.upload_job_id, job.id)
        self.assertEqual(float(exam.patient_weight), 28.0)
        self.assertEqual(float(exam.patient_age), 8.0)
        self.assertEqual(exam.dlp_per_phase, [320.5])
        self.assertEqual(exam.ctdi_vol_per_phase, [18.4])
        self.assertEqual(exam.protocol_type, "PEDIATRIC_HEAD")
        self.assertTrue(exam.rhythm_pseudo_id.startswith("RHY-S001-HEADTRAUMA-NC-PH-G4-"))

    def test_ctexamination_linked_to_resolved_protocol_and_scanner(self):
        """The manifest carries only protocol_id — anatomical region,
        clinical indication, contrast, examination group, and the scanner
        must all come from the resolved CTProtocol, exactly as they would
        from Manual Exam Entry's own "Protocol used" selection."""
        protocol = _make_default_protocol()
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item(protocol=protocol))
        self._run(job)
        exam = CTExamination.objects.first()
        self.assertEqual(exam.protocol_id, protocol.pk)
        self.assertEqual(exam.scanner_id, protocol.scanner_id)
        self.assertEqual(exam.anatomical_region, "Head")
        self.assertEqual(exam.clinical_indication, "Trauma")
        self.assertEqual(exam.contrast, "Non-contrast")
        self.assertEqual(exam.examination_group, "Group 4")

    def test_site_code_matches_protocol_site_case_insensitively(self):
        """The manifest's site_code and the protocol's own site_code are
        compared case-insensitively — differing case alone must not fail
        the item."""
        protocol = _make_default_protocol(site_code="S001")
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item(protocol=protocol, site_code="s001"))
        self._run(job)
        job.refresh_from_db()
        self.assertEqual(job.status, "COMPLETE", job.error_report)

    def test_image_quality_normalized(self):
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item(image_quality="Acceptable"))
        self._run(job)
        exam = CTExamination.objects.first()
        self.assertEqual(exam.image_quality, "MODERATE")

    def test_dicom_pushed_to_orthanc(self):
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item())
        mock_orthanc = self._run(job)
        mock_orthanc.push_dicom_file.assert_called_once()

    def test_image_record_and_study_mapping_orthanc_id_created(self):
        """Regression: the v2 pipeline never created Image rows, and never
        captured push_dicom_file's return value at all (so
        StudyMapping.orthanc_study_id was always left unset)."""
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item())
        self._run(job)
        mapping = StudyMapping.objects.first()
        self.assertEqual(mapping.orthanc_study_id, "orthanc-1")
        image = Image.objects.filter(study_mapping=mapping).first()
        self.assertIsNotNone(image)
        self.assertEqual(image.orthanc_instance_id, "orthanc-inst-1")

    def test_repository_study_id_override_reused(self):
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item(repository_study_id_override="RHY-S001-HEADTRAUMA-NC-PH-G4-000042"))
        self._run(job)
        exam = CTExamination.objects.first()
        self.assertEqual(exam.rhythm_pseudo_id, "RHY-S001-HEADTRAUMA-NC-PH-G4-000042")

    def test_multi_instance_study_all_pushed(self):
        zip_path = _build_v2_zip(self.tmpdir, n_files=3)
        job = _make_v2_job(zip_path, _v2_item())
        mock_orthanc = self._run(job)
        self.assertEqual(mock_orthanc.push_dicom_file.call_count, 3)
        job.refresh_from_db()
        self.assertEqual(job.status, "COMPLETE")


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------

class ProcessV2BatchItemFailureTests(TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.extract_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.extract_dir, ignore_errors=True)

    def test_unknown_protocol_id_fails_before_extracting_archive(self):
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item(protocol_id="00000000-0000-0000-0000-000000000000"))
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir):
            process_upload_job.apply(args=[str(job.pk)])
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.error_report[0]["code"], "protocol_not_found")
        self.assertFalse(CTExamination.objects.exists())

    def test_malformed_protocol_id_fails(self):
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item(protocol_id="not-a-uuid"))
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir):
            process_upload_job.apply(args=[str(job.pk)])
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.error_report[0]["code"], "protocol_not_found")

    def test_site_code_mismatch_with_protocol_fails(self):
        """A protocol_id pasted from another site's records must be
        rejected, not silently attributed to the wrong institution."""
        protocol = _make_default_protocol(site_code="S002")
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item(protocol=protocol, site_code="S001"))
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir):
            process_upload_job.apply(args=[str(job.pk)])
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.error_report[0]["code"], "protocol_site_mismatch")
        self.assertFalse(CTExamination.objects.exists())

    def test_multiple_study_uids_fails(self):
        src = tempfile.mkdtemp()
        _create_dicom_file(os.path.join(src, "a.dcm"), patient_id="PARTNERPAT001", study_uid=generate_uid())
        _create_dicom_file(os.path.join(src, "b.dcm"), patient_id="PARTNERPAT001", study_uid=generate_uid())
        zip_path = os.path.join(self.tmpdir, "bad.zip")
        with zipfile.ZipFile(zip_path, "w") as z:
            z.write(os.path.join(src, "a.dcm"), arcname="a.dcm")
            z.write(os.path.join(src, "b.dcm"), arcname="b.dcm")
        shutil.rmtree(src)

        job = _make_v2_job(zip_path, _v2_item())
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir):
            process_upload_job.apply(args=[str(job.pk)])
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.error_report[0]["code"], "multiple_study_uids")

    def test_absent_patient_id_does_not_fail_archive_scan(self):
        """Regression: an archive where no file carries a PatientID at all
        used to hard-fail with missing_patient_id — but that's exactly
        what a properly-anonymized archive looks like per the
        authoritative anonymization tool (PatientID's directive is null/
        "remove", not a pseudonym to preserve). The archive-level scan
        must not reject on absence; per-file GDPR validation is what
        actually enforces this now (see
        ProcessV2BatchItemRealGdprValidationTests)."""
        src = tempfile.mkdtemp()
        path = os.path.join(src, "slice.dcm")
        _create_compliant_dicom_file(path)  # no patient_id at all
        zip_path = os.path.join(self.tmpdir, "Input_volume1.zip")
        with zipfile.ZipFile(zip_path, "w") as z:
            z.write(path, arcname="slice.dcm")
        shutil.rmtree(src)

        job = _make_v2_job(zip_path, _v2_item())
        mock_orthanc = MagicMock()
        mock_orthanc.push_dicom_file.return_value = {"orthanc_study_id": "orthanc-1"}
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir), \
             patch("uploads.tasks.get_client", return_value=mock_orthanc):
            process_upload_job.apply(args=[str(job.pk)])
        job.refresh_from_db()
        self.assertNotEqual(job.status, "FAILED", job.error_report)
        if job.error_report:
            self.assertNotIn("missing_patient_id", [e.get("code") for e in job.error_report])

    def test_no_dicom_files_fails(self):
        zip_path = os.path.join(self.tmpdir, "empty.zip")
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("readme.txt", "not a dicom file")
        job = _make_v2_job(zip_path, _v2_item())
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir):
            process_upload_job.apply(args=[str(job.pk)])
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.error_report[0]["code"], "no_dicom_files")

    def test_gdpr_validation_failure_all_images_marks_failed(self):
        zip_path = _build_v2_zip(self.tmpdir)
        job = _make_v2_job(zip_path, _v2_item())
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir), \
             patch("uploads.tasks.validate_gdpr_anonymization",
                   return_value=(False, [{"code": "phi_tag_present", "message": "PHI"}])):
            process_upload_job.apply(args=[str(job.pk)])
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertFalse(CTExamination.objects.exists())

    def test_orthanc_push_failure_partial(self):
        zip_path = _build_v2_zip(self.tmpdir, n_files=2)
        job = _make_v2_job(zip_path, _v2_item())
        mock_orthanc = MagicMock()
        mock_orthanc.push_dicom_file.side_effect = [
            {"orthanc_study_id": "s1"},
            OrthancPushError("boom", 500, "server error"),
        ]
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir), \
             patch("uploads.tasks.validate_gdpr_anonymization", return_value=(True, [])), \
             patch("uploads.tasks.get_client", return_value=mock_orthanc):
            process_upload_job.apply(args=[str(job.pk)])
        job.refresh_from_db()
        self.assertEqual(job.status, "PARTIAL")
        # Still creates the CTExamination/StudyMapping since at least one image succeeded.
        self.assertTrue(CTExamination.objects.exists())


# ---------------------------------------------------------------------------
# Real (unmocked) GDPR-strict validation
#
# Every test above mocks validate_gdpr_anonymization, so it never exercises
# the actual GDPR-strict.json rule set against a real DICOM file. These
# tests intentionally do NOT mock it — only Orthanc (external infra) is
# mocked, matching the v1 pipeline's own test conventions.
# ---------------------------------------------------------------------------

def _create_compliant_dicom_file(path: str, patient_id: str = None, study_uid: str = None) -> str:
    """Build a DICOM file that satisfies GDPR-strict.json for real: no PHI
    tags, no temporal tags (RetainStudyDate: false), no private/overlay/
    curve/audio tags, and — per the authoritative anonymization tool
    (github.com/jsfakian/dicom_anonymization) — no PatientID at all
    (its directive is null/"remove", not a pseudonym to preserve).
    `patient_id` is accepted for call-site compatibility but ignored: a
    partner-supplied value is never written into a "compliant" fixture,
    since the platform doesn't use or trust it either way."""
    meta = Dataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    # Deliberately no PatientID/StudyDate/PatientName/PatientBirthDate/etc.
    ds.save_as(path)
    return path


class ProcessV2BatchItemRealGdprValidationTests(TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.extract_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.extract_dir, ignore_errors=True)

    def test_compliant_dicom_passes_real_validation_and_completes(self):
        src = tempfile.mkdtemp()
        study_uid = generate_uid()
        _create_compliant_dicom_file(os.path.join(src, "slice.dcm"), patient_id="PARTNERPAT001", study_uid=study_uid)
        zip_path = os.path.join(self.tmpdir, "Input_volume1.zip")
        with zipfile.ZipFile(zip_path, "w") as z:
            z.write(os.path.join(src, "slice.dcm"), arcname="slice.dcm")
        shutil.rmtree(src)

        job = _make_v2_job(zip_path, _v2_item())
        mock_orthanc = MagicMock()
        mock_orthanc.push_dicom_file.return_value = {"orthanc_study_id": "orthanc-1"}
        # No patch of validate_gdpr_anonymization — exercises the real
        # GDPR-strict.json rule set end to end.
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir), \
             patch("uploads.tasks.get_client", return_value=mock_orthanc):
            process_upload_job.apply(args=[str(job.pk)])

        job.refresh_from_db()
        self.assertEqual(job.status, "COMPLETE", job.error_report)
        exam = CTExamination.objects.first()
        self.assertIsNotNone(exam)
        # No StudyDate on the DICOM (GDPR-strict requires it absent) — the
        # pipeline must fall back to today's date rather than erroring.
        mapping = StudyMapping.objects.first()
        self.assertIsNotNone(mapping.acquisition_date)

    def test_leftover_phi_tag_fails_real_validation(self):
        """A DICOM that still carries a PHI tag (PatientBirthDate here) must
        be rejected by the real validator, not silently accepted."""
        src = tempfile.mkdtemp()
        path = os.path.join(src, "slice.dcm")
        _create_compliant_dicom_file(path, patient_id="PARTNERPAT001")
        # Re-open and add a leftover PHI tag the partner's anonymizer missed.
        import pydicom
        ds = pydicom.dcmread(path)
        ds.PatientBirthDate = "19800101"
        ds.save_as(path)

        zip_path = os.path.join(self.tmpdir, "Input_volume1.zip")
        with zipfile.ZipFile(zip_path, "w") as z:
            z.write(path, arcname="slice.dcm")
        shutil.rmtree(src)

        job = _make_v2_job(zip_path, _v2_item())
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir), \
             patch("uploads.tasks.get_client", return_value=MagicMock()):
            process_upload_job.apply(args=[str(job.pk)])

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertFalse(CTExamination.objects.exists())
