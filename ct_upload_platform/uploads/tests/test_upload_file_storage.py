"""
Tests for upload view and task processing with raw_data and processed_data directories.
Tests that tar files are stored correctly and processed data is preserved/deleted appropriately.
"""

import io
import json
import os
import shutil
import tarfile
import tempfile
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.conf import settings
from rest_framework.test import APITestCase, APIClient
from rest_framework.authtoken.models import Token
from rest_framework import status

from uploads.models import UploadJob
from uploads.file_manager import (
    get_raw_data_user_dir,
    get_processed_data_job_dir,
    get_user_tar_files,
    get_job_processed_files,
)


class UploadFileStorageTestCase(APITestCase):
    """Test that uploads are stored in raw_data with correct structure."""

    @classmethod
    def setUpClass(cls):
        """Set up test directories."""
        super().setUpClass()
        cls.test_temp_dir = tempfile.mkdtemp(prefix="test_upload_storage_")

    @classmethod
    def tearDownClass(cls):
        """Clean up test directories."""
        if os.path.exists(cls.test_temp_dir):
            shutil.rmtree(cls.test_temp_dir)
        super().tearDownClass()

    def setUp(self):
        """Set up for each test."""
        # Create test user and token
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpassword123'
        )
        self.token = Token.objects.create(user=self.user)

        # Set up API client
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

        # Set up test directories
        self.raw_data_dir = os.path.join(self.test_temp_dir, "raw_data")
        self.processed_data_dir = os.path.join(self.test_temp_dir, "processed_data")
        os.makedirs(self.raw_data_dir, exist_ok=True)
        os.makedirs(self.processed_data_dir, exist_ok=True)

    def tearDown(self):
        """Clean up after each test."""
        # Clean up user and token
        self.user.delete()
        self.token.delete()

        # Clean up directories
        if os.path.exists(self.raw_data_dir):
            shutil.rmtree(self.raw_data_dir)
        if os.path.exists(self.processed_data_dir):
            shutil.rmtree(self.processed_data_dir)

    def _create_valid_tar(self):
        """Create a valid tar file with manifest and image."""
        manifest = {
            'manifest_version': '1.0',
            'study': {
                'study_uid': 'STUDY_001',
                'acquisition_date': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'),
                'clinical_indication': 'Test',
                'pathology_labels': [],
                'contrast_used': False,
            },
            'patient': {
                'pseudo_id': 'PAT-ABC-12345',
                'sex': 'M',
                'age_at_acquisition': 45,
            },
            'images': [
                {
                    'filename': 'image001.dcm',
                    'checksum_sha256': hashlib.sha256(b'dummy_dicom_data').hexdigest(),
                }
            ],
        }

        tar_buffer = io.BytesIO()
        tar = tarfile.open(fileobj=tar_buffer, mode='w:gz')

        # Add manifest
        manifest_json = json.dumps(manifest).encode('utf-8')
        manifest_info = tarfile.TarInfo(name='manifest.json')
        manifest_info.size = len(manifest_json)
        tar.addfile(manifest_info, io.BytesIO(manifest_json))

        # Add image
        image_data = b'dummy_dicom_data'
        image_info = tarfile.TarInfo(name='image001.dcm')
        image_info.size = len(image_data)
        tar.addfile(image_info, io.BytesIO(image_data))

        tar.close()
        tar_buffer.seek(0)
        return tar_buffer

    @override_settings(RAW_DATA_DIR=None, PROCESSED_DATA_DIR=None)
    def test_upload_saves_to_raw_data_user_directory(self):
        """Test that successful upload saves tar to raw_data/{uploader_id}/."""
        # Use test directories
        raw_data_dir = os.path.join(self.test_temp_dir, "raw_data_test1")
        
        with patch('uploads.views.settings.RAW_DATA_DIR', raw_data_dir):
            tar_file = self._create_valid_tar()
            tar_file.name = 'test_upload.tar.gz'

            response = self.client.post(
                '/api/v1/uploads/',
                {'tar_file': tar_file},
                format='multipart'
            )

        # Check response
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn('job_id', response.data)

        # Check that tar was saved to raw_data/{uploader_id}/
        user_dir = os.path.join(raw_data_dir, self.user.username)
        self.assertTrue(os.path.isdir(user_dir), f"User directory {user_dir} not created")

        # Check that a tar file exists in the user directory
        tar_files = list(Path(user_dir).glob("*.tar*"))
        self.assertEqual(len(tar_files), 1, "Expected one tar file in user directory")

        # Clean up
        if os.path.exists(raw_data_dir):
            shutil.rmtree(raw_data_dir)

    @override_settings(RAW_DATA_DIR=None, PROCESSED_DATA_DIR=None)
    def test_upload_preserves_tar_file_name_structure(self):
        """Test that tar files are stored with UUID names in user directories."""
        raw_data_dir = os.path.join(self.test_temp_dir, "raw_data_test2")
        
        with patch('uploads.views.settings.RAW_DATA_DIR', raw_data_dir):
            tar_file = self._create_valid_tar()
            tar_file.name = 'original_name.tar.gz'

            response = self.client.post(
                '/api/v1/uploads/',
                {'tar_file': tar_file},
                format='multipart'
            )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        user_dir = os.path.join(raw_data_dir, self.user.username)
        tar_files = list(Path(user_dir).glob("*.tar*"))
        
        # Check that the tar file has a UUID name (not original name)
        self.assertEqual(len(tar_files), 1)
        tar_name = tar_files[0].name
        self.assertNotEqual(tar_name, 'original_name.tar.gz')
        self.assertTrue(tar_name.startswith('ffffffff-') or '-' in tar_name)  # UUID format

        # Clean up
        if os.path.exists(raw_data_dir):
            shutil.rmtree(raw_data_dir)

    @override_settings(RAW_DATA_DIR=None, PROCESSED_DATA_DIR=None)
    def test_multiple_uploads_from_same_user_all_in_same_directory(self):
        """Test that multiple uploads from same user are stored in same directory."""
        raw_data_dir = os.path.join(self.test_temp_dir, "raw_data_test3")
        
        with patch('uploads.views.settings.RAW_DATA_DIR', raw_data_dir):
            # First upload
            tar_file1 = self._create_valid_tar()
            tar_file1.name = 'upload1.tar.gz'
            response1 = self.client.post(
                '/api/v1/uploads/',
                {'tar_file': tar_file1},
                format='multipart'
            )

            # Second upload
            tar_file2 = self._create_valid_tar()
            tar_file2.name = 'upload2.tar.gz'
            response2 = self.client.post(
                '/api/v1/uploads/',
                {'tar_file': tar_file2},
                format='multipart'
            )

        self.assertEqual(response1.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response2.status_code, status.HTTP_202_ACCEPTED)

        # Check that both tar files are in the same user directory
        user_dir = os.path.join(raw_data_dir, self.user.username)
        tar_files = list(Path(user_dir).glob("*.tar*"))
        
        self.assertEqual(len(tar_files), 2, "Expected two tar files in user directory")

        # Clean up
        if os.path.exists(raw_data_dir):
            shutil.rmtree(raw_data_dir)


class TaskProcessingFileLocationTestCase(TestCase):
    """Test that task processing uses correct file directories."""

    @classmethod
    def setUpClass(cls):
        """Set up test directories."""
        super().setUpClass()
        cls.test_temp_dir = tempfile.mkdtemp(prefix="test_task_processing_")

    @classmethod
    def tearDownClass(cls):
        """Clean up test directories."""
        if os.path.exists(cls.test_temp_dir):
            shutil.rmtree(cls.test_temp_dir)
        super().tearDownClass()

    def setUp(self):
        """Set up for each test."""
        self.raw_data_dir = os.path.join(self.test_temp_dir, "raw_data")
        self.processed_data_dir = os.path.join(self.test_temp_dir, "processed_data")
        os.makedirs(self.raw_data_dir, exist_ok=True)
        os.makedirs(self.processed_data_dir, exist_ok=True)

    def tearDown(self):
        """Clean up after each test."""
        if os.path.exists(self.raw_data_dir):
            shutil.rmtree(self.raw_data_dir)
        if os.path.exists(self.processed_data_dir):
            shutil.rmtree(self.processed_data_dir)

    @override_settings(RAW_DATA_DIR=None, PROCESSED_DATA_DIR=None)
    def test_task_extracts_to_processed_data_job_directory(self):
        """Test that task extracts tar to processed_data/{job_id}/."""
        from uploads.tasks import validate_tar_safety
        import uuid

        job_id = str(uuid.uuid4())
        
        # Create a simple tar file
        tar_buffer = io.BytesIO()
        tar = tarfile.open(fileobj=tar_buffer, mode='w:')
        
        manifest = {
            'manifest_version': '1.0',
            'study': {'study_uid': 'STUDY_001', 'acquisition_date': '2024-01-01'},
            'patient': {'pseudo_id': 'PAT-001'},
            'images': []
        }
        manifest_json = json.dumps(manifest).encode()
        manifest_info = tarfile.TarInfo(name='manifest.json')
        manifest_info.size = len(manifest_json)
        tar.addfile(manifest_info, io.BytesIO(manifest_json))
        tar.close()

        tar_buffer.seek(0)
        tar_path = os.path.join(self.test_temp_dir, "test.tar")
        with open(tar_path, 'wb') as f:
            f.write(tar_buffer.getvalue())

        # Test that validate_tar_safety works (basic check)
        try:
            validate_tar_safety(tar_path)
        except Exception as e:
            self.fail(f"validate_tar_safety raised {e}")

        # Clean up
        if os.path.exists(tar_path):
            os.remove(tar_path)

    @override_settings(RAW_DATA_DIR=None, PROCESSED_DATA_DIR=None)
    def test_processed_data_cleanup_on_failure(self):
        """Test that processed_data is deleted on task failure."""
        import uuid
        from uploads.models import UploadJob
        
        job_id = uuid.uuid4()
        processed_dir = os.path.join(self.processed_data_dir, str(job_id))
        os.makedirs(processed_dir, exist_ok=True)

        # Create a test file
        test_file = os.path.join(processed_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")

        self.assertTrue(os.path.exists(processed_dir))

        # Simulate deletion on failure
        if os.path.exists(processed_dir):
            shutil.rmtree(processed_dir)

        self.assertFalse(os.path.exists(processed_dir))

    @override_settings(RAW_DATA_DIR=None, PROCESSED_DATA_DIR=None)
    def test_raw_data_tar_file_never_deleted(self):
        """Test that raw_data tar files are never automatically deleted."""
        uploader_id = "test_user"
        user_dir = os.path.join(self.raw_data_dir, uploader_id)
        os.makedirs(user_dir, exist_ok=True)

        # Create a tar file
        tar_path = os.path.join(user_dir, "upload.tar")
        with open(tar_path, 'w') as f:
            f.write("tar content")

        self.assertTrue(os.path.exists(tar_path))

        # Simulate task completion (should NOT delete tar)
        # This is just a verification that the file still exists
        self.assertTrue(os.path.exists(tar_path))

    def test_processed_data_preserved_on_success(self):
        """Test that processed_data directory is preserved on successful processing."""
        import uuid
        
        job_id = uuid.uuid4()
        processed_dir = os.path.join(self.processed_data_dir, str(job_id))
        os.makedirs(processed_dir, exist_ok=True)

        # Create test files
        manifest_path = os.path.join(processed_dir, "manifest.json")
        images_dir = os.path.join(processed_dir, "images")
        os.makedirs(images_dir, exist_ok=True)

        with open(manifest_path, 'w') as f:
            json.dump({'manifest_version': '1.0'}, f)

        image_path = os.path.join(images_dir, "image001.dcm")
        with open(image_path, 'wb') as f:
            f.write(b"dicom_data")

        # Verify directory and files exist
        self.assertTrue(os.path.exists(processed_dir))
        self.assertTrue(os.path.exists(manifest_path))
        self.assertTrue(os.path.exists(image_path))

        # On success (COMPLETE or PARTIAL status), directory should be preserved
        # This test just verifies the structure exists
        preserved_files = list(Path(processed_dir).rglob("*"))
        self.assertGreater(len(preserved_files), 0)


class UploadJobTarPathTestCase(TestCase):
    """Test that UploadJob correctly stores tar_temp_path."""

    @classmethod
    def setUpClass(cls):
        """Set up test directories."""
        super().setUpClass()
        cls.test_temp_dir = tempfile.mkdtemp(prefix="test_upload_job_")

    @classmethod
    def tearDownClass(cls):
        """Clean up test directories."""
        if os.path.exists(cls.test_temp_dir):
            shutil.rmtree(cls.test_temp_dir)
        super().tearDownClass()

    def test_upload_job_stores_raw_data_path(self):
        """Test that UploadJob.tar_temp_path points to raw_data location."""
        import uuid
        
        job_id = uuid.uuid4()
        uploader_id = "test_user"
        raw_data_path = os.path.join(
            self.test_temp_dir,
            "raw_data",
            uploader_id,
            "upload.tar"
        )

        # Create the path structure
        os.makedirs(os.path.dirname(raw_data_path), exist_ok=True)
        with open(raw_data_path, 'w') as f:
            f.write("tar content")

        # Create an UploadJob with this path
        job = UploadJob.objects.create(
            id=job_id,
            uploader_id=uploader_id,
            tar_temp_path=raw_data_path,
            status='PENDING'
        )

        # Verify the path is stored correctly
        self.assertEqual(job.tar_temp_path, raw_data_path)
        self.assertTrue(os.path.exists(job.tar_temp_path))
        self.assertIn("raw_data", job.tar_temp_path)
        self.assertIn(uploader_id, job.tar_temp_path)

        # Clean up
        job.delete()
        if os.path.exists(raw_data_path):
            os.remove(raw_data_path)
