"""
Regression tests for the v1 pipeline's checksum-vs-anonymization ordering.

GDPRAnonymizationPipeline rewrites each DICOM file in place (inserting the
organ-specific pseudo PatientID) before GDPR-strict validation runs. The
per-image checksum check must therefore happen BEFORE that rewrite —
checksumming afterward would compare against bytes the server itself just
changed, and could never match the client-supplied checksum of the original
upload. Every other v1 pipeline test mocks either GDPRAnonymizationPipeline
or validate_gdpr_anonymization, so this ordering bug was never exercised;
these tests deliberately leave both unmocked (only Orthanc, external infra,
stays mocked) to prove the real, end-to-end pipeline completes.
"""

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from unittest.mock import patch, MagicMock

from django.test import TestCase

from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian

from uploads.models import UploadJob, Patient, StudyMapping, Image
from uploads.tasks import process_upload_job


def _create_compliant_dicom_file(path: str, study_uid: str = None, series_uid: str = None) -> str:
    """A DICOM file satisfying GDPR-strict.json for real (no PHI or
    temporal tags) — PatientID is a placeholder; the server's
    GDPRAnonymizationPipeline overwrites it with the real pseudo ID."""
    meta = Dataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.PatientID = "PLACEHOLDER"
    ds.save_as(path)
    return path


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            h.update(block)
    return h.hexdigest()


def _build_compliant_tar(tmpdir: str, n_images: int = 1) -> tuple:
    """Build a v1 tar+manifest whose images are real, GDPR-strict-compliant
    DICOM files with correct (pre-anonymization) checksums."""
    src = tempfile.mkdtemp()
    study_uid = generate_uid()
    images = []
    for i in range(n_images):
        fname = f"slice_{i:03d}.dcm"
        dcm_path = os.path.join(src, fname)
        _create_compliant_dicom_file(dcm_path, study_uid=study_uid)
        images.append({
            "filename": fname,
            "checksum_sha256": _sha256_of(dcm_path),
            "series_uid": generate_uid(),
            "body_part": "HEAD",
        })

    manifest = {
        "manifest_version": "1.0",
        "upload_id": generate_uid()[:36],
        "created_at": "2026-01-01T00:00:00Z",
        "patient": {"pseudo_id": "CHECKSUMORDPAT01", "sex": "M", "age_at_acquisition": 10},
        "study": {"study_uid": str(study_uid), "acquisition_date": "2026-01-01", "contrast_used": False},
        "images": images,
    }
    with open(os.path.join(src, "manifest.json"), "w") as f:
        json.dump(manifest, f)

    tar_path = os.path.join(tmpdir, "upload.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(os.path.join(src, "manifest.json"), arcname="manifest.json")
        for img in images:
            tar.add(os.path.join(src, img["filename"]), arcname=img["filename"])

    shutil.rmtree(src)
    return tar_path, manifest


class ChecksumOrderingRealPipelineTests(TestCase):
    """Runs process_upload_job with NEITHER GDPRAnonymizationPipeline NOR
    validate_gdpr_anonymization mocked — only Orthanc is mocked."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.extract_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.extract_dir, ignore_errors=True)

    def _run(self, tar_path):
        job = UploadJob.objects.create(uploader_id="test_user", tar_temp_path=tar_path)
        mock_orthanc = MagicMock()
        mock_orthanc.push_dicom_file.return_value = {"orthanc_study_id": "orthanc-1", "orthanc_instance_id": "inst-1"}
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=self.extract_dir), \
             patch("uploads.tasks.get_client", return_value=mock_orthanc):
            process_upload_job.apply(args=[str(job.pk)])
        job.refresh_from_db()
        return job, mock_orthanc

    def test_real_anonymization_and_checksum_both_succeed(self):
        """The exact scenario that failed live before the fix: a real
        (unmocked) anonymization rewrite must not cause the checksum
        comparison — now run beforehand — to see a mismatch."""
        tar_path, manifest = _build_compliant_tar(self.tmpdir)
        job, mock_orthanc = self._run(tar_path)
        self.assertEqual(job.status, "COMPLETE", job.error_report)
        self.assertNotIn("checksum_mismatch", str(job.error_report))
        mock_orthanc.push_dicom_file.assert_called_once()

    def test_patient_and_image_records_created(self):
        tar_path, manifest = _build_compliant_tar(self.tmpdir)
        job, _ = self._run(tar_path)
        self.assertTrue(Patient.objects.filter(pseudo_id="CHECKSUMORDPAT01").exists())
        self.assertEqual(StudyMapping.objects.count(), 1)

    def test_multiple_images_all_survive_real_anonymization(self):
        tar_path, manifest = _build_compliant_tar(self.tmpdir, n_images=3)
        job, mock_orthanc = self._run(tar_path)
        self.assertEqual(job.status, "COMPLETE", job.error_report)
        self.assertEqual(mock_orthanc.push_dicom_file.call_count, 3)

    def test_genuinely_corrupted_image_still_caught_pre_anonymization(self):
        """A real checksum mismatch (e.g. transport corruption) must still
        be caught — and caught BEFORE that file is anonymized, so a
        corrupted file is never rewritten or pushed."""
        tar_path, manifest = _build_compliant_tar(self.tmpdir)
        # Corrupt the manifest's checksum for the one image after building
        # the (otherwise valid) tar, simulating a genuinely corrupted upload.
        src = tempfile.mkdtemp()
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(src)
        bad_manifest = json.loads(json.dumps(manifest))
        bad_manifest["images"][0]["checksum_sha256"] = "0" * 64
        with open(os.path.join(src, "manifest.json"), "w") as f:
            json.dump(bad_manifest, f)
        bad_tar_path = os.path.join(self.tmpdir, "bad_upload.tar.gz")
        with tarfile.open(bad_tar_path, "w:gz") as tar:
            tar.add(os.path.join(src, "manifest.json"), arcname="manifest.json")
            tar.add(os.path.join(src, "slice_000.dcm"), arcname="slice_000.dcm")
        shutil.rmtree(src, ignore_errors=True)

        job, mock_orthanc = self._run(bad_tar_path)
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.error_report[0]["code"], "checksum_mismatch")
        mock_orthanc.push_dicom_file.assert_not_called()
        self.assertFalse(Image.objects.exists())
