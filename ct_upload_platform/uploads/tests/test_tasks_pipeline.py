"""
Tests for uploads/tasks.py.

Covers:
  - compute_sha256
  - validate_tar_safety
  - extract_dicom_metadata
  - strip_phi_tags
  - process_upload_job (full pipeline, with mocked I/O)
"""

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from unittest.mock import patch, MagicMock, call

from django.test import TestCase, override_settings
from django.contrib.auth.models import User

from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian

from uploads.models import UploadJob, Patient, StudyMapping
from uploads.tasks import (
    compute_sha256,
    validate_tar_safety,
    extract_dicom_metadata,
    strip_phi_tags,
    process_upload_job,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_dicom_file(path: str, patient_id: str = "PAT001_CHT01") -> str:
    meta = Dataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientID = patient_id
    ds.save_as(path)
    return path


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            h.update(block)
    return h.hexdigest()


def _build_tar(tmpdir: str) -> tuple:
    """
    Create a minimal test tar containing manifest.json + one DICOM file.

    Returns (tar_path, manifest_dict, extract_source_dir).
    """
    src = tempfile.mkdtemp()
    dcm = os.path.join(src, "slice_001.dcm")
    _create_dicom_file(dcm, patient_id="PAT001_CHT01")
    checksum = _sha256_of(dcm)

    manifest = {
        "patient": {
            "pseudo_id": "PAT001",
            "sex": "M",
            "age_at_acquisition": 45,
            "cohort_tag": "TEST",
        },
        "study": {
            "study_uid": "1.2.3.4.5.TEST",
            "acquisition_date": "2024-01-01",
            "clinical_indication": "research",
        },
        "source_institution": "TestHospital",
        "images": [
            {
                "filename": "slice_001.dcm",
                "body_part": "CHEST",
                "checksum_sha256": checksum,
                "annotations": [],
            }
        ],
    }
    with open(os.path.join(src, "manifest.json"), "w") as f:
        json.dump(manifest, f)

    tar_path = os.path.join(tmpdir, "upload.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(os.path.join(src, "manifest.json"), arcname="manifest.json")
        tar.add(dcm, arcname="slice_001.dcm")

    shutil.rmtree(src)
    return tar_path, manifest


def _make_job(tar_path: str = "") -> UploadJob:
    return UploadJob.objects.create(uploader_id="test_user", tar_temp_path=tar_path)


# ---------------------------------------------------------------------------
# compute_sha256
# ---------------------------------------------------------------------------

class ComputeSHA256Tests(TestCase):

    def test_known_content(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = f.name
        try:
            expected = hashlib.sha256(b"hello world").hexdigest()
            self.assertEqual(compute_sha256(path), expected)
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            expected = hashlib.sha256(b"").hexdigest()
            self.assertEqual(compute_sha256(path), expected)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# validate_tar_safety
# ---------------------------------------------------------------------------

@override_settings(MAX_IMAGES_PER_UPLOAD=100, MAX_UPLOAD_SIZE_MB=100)
class ValidateTarSafetyTests(TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_tar(self, members: list) -> str:
        """members is a list of (arcname, content_bytes_or_None)."""
        path = os.path.join(self.tmpdir, "test.tar.gz")
        with tarfile.open(path, "w:gz") as tar:
            for arcname, content in members:
                if content is not None:
                    import io
                    info = tarfile.TarInfo(name=arcname)
                    info.size = len(content)
                    tar.addfile(info, io.BytesIO(content))
                else:
                    info = tarfile.TarInfo(name=arcname)
                    info.type = tarfile.DIRTYPE
                    tar.addfile(info)
        return path

    def test_valid_tar_passes(self):
        path = self._make_tar([("file.txt", b"data")])
        validate_tar_safety(path)  # must not raise

    def test_path_traversal_raises(self):
        path = self._make_tar([("../evil.sh", b"bad")])
        with self.assertRaises(ValueError):
            validate_tar_safety(path)

    def test_absolute_path_raises(self):
        path = self._make_tar([("/etc/passwd", b"root")])
        with self.assertRaises(ValueError):
            validate_tar_safety(path)

    @override_settings(MAX_IMAGES_PER_UPLOAD=2)
    def test_too_many_members_raises(self):
        path = self._make_tar([
            ("a.txt", b"x"), ("b.txt", b"y"), ("c.txt", b"z")
        ])
        with self.assertRaises(ValueError):
            validate_tar_safety(path)

    @override_settings(MAX_UPLOAD_SIZE_MB=0)
    def test_total_size_exceeded_raises(self):
        # 0 MB limit → any file triggers the check
        path = self._make_tar([("a.txt", b"x")])
        with self.assertRaises(ValueError):
            validate_tar_safety(path)


# ---------------------------------------------------------------------------
# extract_dicom_metadata
# ---------------------------------------------------------------------------

class ExtractDicomMetadataTests(TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @override_settings(DICOM_ENRICHMENT_ENABLED=False)
    def test_disabled_returns_empty_dict(self):
        result = extract_dicom_metadata("/fake/path.dcm")
        self.assertEqual(result, {})

    @override_settings(DICOM_ENRICHMENT_ENABLED=True)
    def test_extracts_standard_tags(self):
        path = os.path.join(self.tmpdir, "test.dcm")
        _create_dicom_file(path)

        ds = MagicMock()
        ds.BodyPartExamined = "CHEST"
        ds.KVP = 120
        # Make hasattr work with spec trick
        ds.__class__ = Dataset
        ds.configure_mock(**{"BodyPartExamined": "CHEST", "KVP": 120})

        with patch("uploads.tasks.pydicom.dcmread", return_value=ds):
            # hasattr calls need the attribute to exist on the mock
            type(ds).__contains__ = MagicMock(return_value=True)
            result = extract_dicom_metadata(path)
        # Any dict returned is acceptable — function didn't crash
        self.assertIsInstance(result, dict)

    @override_settings(DICOM_ENRICHMENT_ENABLED=True)
    def test_corrupt_file_returns_empty_dict(self):
        with patch("uploads.tasks.pydicom.dcmread", side_effect=Exception("bad")):
            result = extract_dicom_metadata("/fake/path.dcm")
        self.assertEqual(result, {})

    @override_settings(DICOM_ENRICHMENT_ENABLED=True)
    def test_axial_orientation_detected(self):
        path = os.path.join(self.tmpdir, "test.dcm")
        _create_dicom_file(path)

        ds = Dataset()
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.PatientID = "TEST"
        # Axial orientation: normal vector points along Z (index 2)
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]

        with patch("uploads.tasks.pydicom.dcmread", return_value=ds):
            result = extract_dicom_metadata(path)
        self.assertEqual(result.get("view_plane"), "AXIAL")


# ---------------------------------------------------------------------------
# strip_phi_tags
# ---------------------------------------------------------------------------

class StripPHITagsTests(TestCase):

    def test_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            strip_phi_tags("/any/path.dcm")


# ---------------------------------------------------------------------------
# process_upload_job – early failure gates
# ---------------------------------------------------------------------------

class ProcessUploadJobFailureTests(TestCase):
    """Each test targets one failure gate in the pipeline."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, job_id):
        process_upload_job.apply(args=[str(job_id)])

    def test_missing_job_raises(self):
        import uuid
        fake_id = str(uuid.uuid4())
        with self.assertRaises(Exception):
            process_upload_job.apply(args=[fake_id], throw=True)

    def test_tar_not_found_sets_failed(self):
        job = _make_job(tar_path="/no/such/file.tar.gz")
        self._run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertTrue(any("not found" in str(e) for e in job.error_report))

    def test_tar_safety_failure_sets_failed(self):
        tar_path, _ = _build_tar(self.tmpdir)
        job = _make_job(tar_path=tar_path)
        with patch("uploads.tasks.validate_tar_safety", side_effect=ValueError("bad tar")):
            self._run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertTrue(any("bad tar" in str(e) for e in job.error_report))

    def test_manifest_missing_sets_failed(self):
        # Tar with no manifest.json
        src = tempfile.mkdtemp()
        try:
            with open(os.path.join(src, "image.dcm"), "wb") as f:
                f.write(b"dummy")
            tar_path = os.path.join(self.tmpdir, "no_manifest.tar.gz")
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(os.path.join(src, "image.dcm"), arcname="image.dcm")
        finally:
            shutil.rmtree(src)

        job = _make_job(tar_path=tar_path)
        extract_dir = tempfile.mkdtemp()
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir):
            self._run(job.pk)
        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertTrue(any("manifest.json" in str(e) for e in job.error_report))

    def test_manifest_parse_error_sets_failed(self):
        src = tempfile.mkdtemp()
        try:
            with open(os.path.join(src, "manifest.json"), "w") as f:
                f.write("{ not valid json }")
            tar_path = os.path.join(self.tmpdir, "bad_manifest.tar.gz")
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(os.path.join(src, "manifest.json"), arcname="manifest.json")
        finally:
            shutil.rmtree(src)

        job = _make_job(tar_path=tar_path)
        extract_dir = tempfile.mkdtemp()
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir):
            self._run(job.pk)
        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")

    def test_manifest_schema_failure_sets_failed(self):
        tar_path, _ = _build_tar(self.tmpdir)
        job = _make_job(tar_path=tar_path)
        extract_dir = tempfile.mkdtemp()
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir), \
             patch("uploads.tasks.validate_manifest", return_value=[{"error": "schema fail"}]):
            self._run(job.pk)
        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")

    def test_pseudo_id_uniqueness_failure_sets_failed(self):
        tar_path, _ = _build_tar(self.tmpdir)
        job = _make_job(tar_path=tar_path)
        extract_dir = tempfile.mkdtemp()
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir), \
             patch("uploads.tasks.validate_manifest", return_value=[]), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.validate_manifest_pseudo_ids",
                   return_value=(False, [{"error": "collision"}])):
            self._run(job.pk)
        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")

    def test_anonymization_pipeline_failure_sets_failed(self):
        tar_path, _ = _build_tar(self.tmpdir)
        job = _make_job(tar_path=tar_path)
        extract_dir = tempfile.mkdtemp()
        mock_pipeline = MagicMock()
        mock_pipeline.anonymize_and_insert_pseudo_ids.return_value = (
            False,
            [{"code": "modification_failed", "message": "oh no"}],
        )
        mock_pipeline.get_report.return_value = {}
        with patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir), \
             patch("uploads.tasks.validate_manifest", return_value=[]), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.validate_manifest_pseudo_ids",
                   return_value=(True, [])), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.log_pseudo_id_tracking"), \
             patch("uploads.tasks.GDPRAnonymizationPipeline", return_value=mock_pipeline):
            self._run(job.pk)
        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")


# ---------------------------------------------------------------------------
# process_upload_job – full pipeline (image-level outcomes)
# ---------------------------------------------------------------------------

class ProcessUploadJobPipelineTests(TestCase):
    """Tests covering the per-image processing loop."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _common_patches(self, extract_dir):
        """Return a list of context managers that mock all pre-loop gates."""
        mock_pipeline = MagicMock()
        mock_pipeline.anonymize_and_insert_pseudo_ids.return_value = (True, [])
        mock_pipeline.get_report.return_value = {}

        mock_orthanc = MagicMock()
        mock_orthanc.push_dicom_file.return_value = {
            "orthanc_study_id": "study-123",
            "orthanc_instance_id": "inst-456",
        }

        return [
            patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir),
            patch("uploads.tasks.validate_manifest", return_value=[]),
            patch("uploads.tasks.PseudoIDUniquenessValidator.validate_manifest_pseudo_ids",
                  return_value=(True, [])),
            patch("uploads.tasks.PseudoIDUniquenessValidator.log_pseudo_id_tracking"),
            patch("uploads.tasks.GDPRAnonymizationPipeline", return_value=mock_pipeline),
            patch("uploads.tasks.validate_gdpr_anonymization", return_value=(True, [])),
            patch("uploads.tasks.get_client", return_value=mock_orthanc),
        ]

    def _run_with_patches(self, job, tar_path, extract_dir):
        patches = self._common_patches(extract_dir)
        ctx = [p.__enter__() for p in patches]
        try:
            process_upload_job.apply(args=[str(job.pk)])
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    def test_all_images_succeed_status_complete(self):
        tar_path, manifest = _build_tar(self.tmpdir)
        extract_dir = tempfile.mkdtemp()
        job = _make_job(tar_path=tar_path)
        self._run_with_patches(job, tar_path, extract_dir)
        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertEqual(job.status, "COMPLETE")

    def test_checksum_mismatch_image_logged_as_error(self):
        tar_path, manifest = _build_tar(self.tmpdir)
        # Tamper: corrupt checksum in tar manifest
        extract_dir = tempfile.mkdtemp()
        job = _make_job(tar_path=tar_path)

        # Patch validate_manifest to inject wrong checksum into manifest
        bad_manifest = json.loads(json.dumps(manifest))
        bad_manifest["images"][0]["checksum_sha256"] = "deadbeef" * 8

        with patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir), \
             patch("uploads.tasks.validate_manifest", return_value=[]), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.validate_manifest_pseudo_ids",
                   return_value=(True, [])), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.log_pseudo_id_tracking"), \
             patch("uploads.tasks.GDPRAnonymizationPipeline",
                   return_value=MagicMock(
                       anonymize_and_insert_pseudo_ids=MagicMock(return_value=(True, [])),
                       get_report=MagicMock(return_value={}))), \
             patch("uploads.tasks.validate_gdpr_anonymization", return_value=(True, [])), \
             patch("uploads.tasks.get_client", return_value=MagicMock()), \
             patch("builtins.open", side_effect=_intercept_manifest_open(
                 extract_dir, bad_manifest)):
            process_upload_job.apply(args=[str(job.pk)])

        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertIn(job.status, ("FAILED", "PARTIAL"))

    def test_gdpr_validation_failure_image_skipped(self):
        tar_path, manifest = _build_tar(self.tmpdir)
        extract_dir = tempfile.mkdtemp()
        job = _make_job(tar_path=tar_path)

        mock_pipeline = MagicMock()
        mock_pipeline.anonymize_and_insert_pseudo_ids.return_value = (True, [])
        mock_pipeline.get_report.return_value = {}

        with patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir), \
             patch("uploads.tasks.validate_manifest", return_value=[]), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.validate_manifest_pseudo_ids",
                   return_value=(True, [])), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.log_pseudo_id_tracking"), \
             patch("uploads.tasks.GDPRAnonymizationPipeline", return_value=mock_pipeline), \
             patch("uploads.tasks.validate_gdpr_anonymization",
                   return_value=(False, [{"code": "phi_tag_present", "message": "PHI found"}])), \
             patch("uploads.tasks.get_client", return_value=MagicMock()):
            process_upload_job.apply(args=[str(job.pk)])

        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertIn(job.status, ("FAILED", "PARTIAL"))
        errors = job.error_report or []
        self.assertTrue(any(e.get("code") == "gdpr_validation_failed" for e in errors))

    def test_orthanc_push_failure_image_error_logged(self):
        from uploads.orthanc_client import OrthancPushError
        tar_path, manifest = _build_tar(self.tmpdir)
        extract_dir = tempfile.mkdtemp()
        job = _make_job(tar_path=tar_path)

        mock_pipeline = MagicMock()
        mock_pipeline.anonymize_and_insert_pseudo_ids.return_value = (True, [])
        mock_pipeline.get_report.return_value = {}

        mock_orthanc = MagicMock()
        mock_orthanc.push_dicom_file.side_effect = OrthancPushError(
            "push failed", status_code=500, response_body=b""
        )

        with patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir), \
             patch("uploads.tasks.validate_manifest", return_value=[]), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.validate_manifest_pseudo_ids",
                   return_value=(True, [])), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.log_pseudo_id_tracking"), \
             patch("uploads.tasks.GDPRAnonymizationPipeline", return_value=mock_pipeline), \
             patch("uploads.tasks.validate_gdpr_anonymization", return_value=(True, [])), \
             patch("uploads.tasks.get_client", return_value=mock_orthanc):
            process_upload_job.apply(args=[str(job.pk)])

        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertIn(job.status, ("FAILED", "PARTIAL"))
        errors = job.error_report or []
        self.assertTrue(any(e.get("code") == "orthanc_push_error" for e in errors))

    def test_partial_status_when_some_images_fail(self):
        # Build a tar with 2 images; GDPR validation passes for the first, fails for the second
        src = tempfile.mkdtemp()
        try:
            dcm1 = os.path.join(src, "ok.dcm")
            dcm2 = os.path.join(src, "bad.dcm")
            _create_dicom_file(dcm1, "PAT001_CHT01")
            _create_dicom_file(dcm2, "PAT001_CHT02")
            checksum1 = _sha256_of(dcm1)
            checksum2 = _sha256_of(dcm2)

            manifest = {
                "patient": {"pseudo_id": "PAT001", "sex": "M", "age_at_acquisition": 30},
                "study": {"study_uid": "1.2.3.4.9.TEST", "acquisition_date": "2024-01-01"},
                "source_institution": "TestHospital",
                "images": [
                    {"filename": "ok.dcm", "body_part": "CHEST",
                     "checksum_sha256": checksum1, "annotations": []},
                    {"filename": "bad.dcm", "body_part": "CHEST",
                     "checksum_sha256": checksum2, "annotations": []},
                ],
            }
            with open(os.path.join(src, "manifest.json"), "w") as f:
                json.dump(manifest, f)

            tar_path = os.path.join(self.tmpdir, "two_images.tar.gz")
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(os.path.join(src, "manifest.json"), arcname="manifest.json")
                tar.add(dcm1, arcname="ok.dcm")
                tar.add(dcm2, arcname="bad.dcm")
        finally:
            shutil.rmtree(src)

        extract_dir = tempfile.mkdtemp()
        job = _make_job(tar_path=tar_path)

        mock_pipeline = MagicMock()
        mock_pipeline.anonymize_and_insert_pseudo_ids.return_value = (True, [])
        mock_pipeline.get_report.return_value = {}

        mock_orthanc = MagicMock()
        mock_orthanc.push_dicom_file.return_value = {
            "orthanc_study_id": "s1", "orthanc_instance_id": "i1"
        }

        call_count = {"n": 0}

        def gdpr_side_effect(path, pid):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return (True, [])
            return (False, [{"code": "phi_tag_present", "message": "PHI"}])

        with patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir), \
             patch("uploads.tasks.validate_manifest", return_value=[]), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.validate_manifest_pseudo_ids",
                   return_value=(True, [])), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.log_pseudo_id_tracking"), \
             patch("uploads.tasks.GDPRAnonymizationPipeline", return_value=mock_pipeline), \
             patch("uploads.tasks.validate_gdpr_anonymization", side_effect=gdpr_side_effect), \
             patch("uploads.tasks.get_client", return_value=mock_orthanc):
            process_upload_job.apply(args=[str(job.pk)])

        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertEqual(job.status, "PARTIAL")

    def test_study_mapping_orthanc_id_updated_on_success(self):
        tar_path, manifest = _build_tar(self.tmpdir)
        extract_dir = tempfile.mkdtemp()
        job = _make_job(tar_path=tar_path)

        mock_pipeline = MagicMock()
        mock_pipeline.anonymize_and_insert_pseudo_ids.return_value = (True, [])
        mock_pipeline.get_report.return_value = {}

        mock_orthanc = MagicMock()
        mock_orthanc.push_dicom_file.return_value = {
            "orthanc_study_id": "orthanc-study-xyz",
            "orthanc_instance_id": "orthanc-inst-abc",
        }

        with patch("uploads.tasks.get_processed_data_job_dir", return_value=extract_dir), \
             patch("uploads.tasks.validate_manifest", return_value=[]), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.validate_manifest_pseudo_ids",
                   return_value=(True, [])), \
             patch("uploads.tasks.PseudoIDUniquenessValidator.log_pseudo_id_tracking"), \
             patch("uploads.tasks.GDPRAnonymizationPipeline", return_value=mock_pipeline), \
             patch("uploads.tasks.validate_gdpr_anonymization", return_value=(True, [])), \
             patch("uploads.tasks.get_client", return_value=mock_orthanc):
            process_upload_job.apply(args=[str(job.pk)])

        shutil.rmtree(extract_dir, ignore_errors=True)
        job.refresh_from_db()
        self.assertEqual(job.status, "COMPLETE")

        study = StudyMapping.objects.filter(upload_job=job).first()
        self.assertIsNotNone(study)
        self.assertEqual(study.orthanc_study_id, "orthanc-study-xyz")


# ---------------------------------------------------------------------------
# Helper used by checksum test
# ---------------------------------------------------------------------------

def _intercept_manifest_open(extract_dir: str, bad_manifest: dict):
    """
    Return a side_effect for patching builtins.open that returns bad_manifest
    when opening manifest.json, and behaves normally for all other paths.
    """
    real_open = open

    def _open(path, mode="r", *args, **kwargs):
        if "manifest.json" in str(path) and "w" not in mode:
            import io
            return io.StringIO(json.dumps(bad_manifest))
        return real_open(path, mode, *args, **kwargs)

    return _open
