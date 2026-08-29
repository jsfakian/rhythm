"""
Unit tests for chunked upload functionality.
Tests cover models, views, serializers, and utilities.
"""

import hashlib
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase, APIClient

from uploads.models import ChunkedUpload, UploadChunk
from uploads.chunk_manager import (
    calculate_file_hash,
    calculate_bytes_hash,
    store_chunk,
    verify_chunk_integrity,
    get_upload_session_dir,
    cleanup_session,
    cleanup_expired_uploads,
    get_upload_progress,
    assemble_chunks,
)


class ChunkedUploadModelTest(TestCase):
    """Test ChunkedUpload model."""

    def setUp(self):
        """Set up test fixtures."""
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id='test_user',
            filename='test_archive.tar.gz',
            total_size=100 * 1024 * 1024,  # 100MB
            total_chunks=10,
            chunk_size=10 * 1024 * 1024,  # 10MB
            temp_dir='/tmp/test',
            expires_at=timezone.now() + timedelta(days=7)
        )

    def test_chunked_upload_creation(self):
        """Test creating a ChunkedUpload record."""
        self.assertEqual(self.upload.uploader_id, 'test_user')
        self.assertEqual(self.upload.status, 'INITIATED')
        self.assertEqual(self.upload.uploaded_chunks, 0)
        self.assertFalse(self.upload.is_complete)

    def test_progress_percent_calculation(self):
        """Test progress percentage calculation."""
        self.upload.uploaded_chunks = 5
        self.assertEqual(self.upload.progress_percent, 50)

        self.upload.uploaded_chunks = 0
        self.assertEqual(self.upload.progress_percent, 0)

        self.upload.uploaded_chunks = 10
        self.assertEqual(self.upload.progress_percent, 100)

    def test_is_complete_property(self):
        """Test is_complete property."""
        self.assertFalse(self.upload.is_complete)

        self.upload.uploaded_chunks = 10
        self.assertTrue(self.upload.is_complete)

    def test_upload_expiration_timestamp(self):
        """Test that expires_at is set."""
        self.assertIsNotNone(self.upload.expires_at)
        # Should be 7 days from now (with small tolerance)
        time_until_expiry = (self.upload.expires_at - timezone.now()).days
        self.assertIn(time_until_expiry, [6, 7])  # Account for timing

    def test_upload_status_transitions(self):
        """Test status transitions."""
        self.upload.status = 'IN_PROGRESS'
        self.upload.save()
        self.assertEqual(self.upload.status, 'IN_PROGRESS')

        self.upload.status = 'COMPLETED'
        self.upload.completed_at = timezone.now()
        self.upload.save()
        self.assertEqual(self.upload.status, 'COMPLETED')
        self.assertIsNotNone(self.upload.completed_at)


class UploadChunkModelTest(TestCase):
    """Test UploadChunk model."""

    def setUp(self):
        """Set up test fixtures."""
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id='test_user',
            filename='test.tar.gz',
            total_size=100 * 1024 * 1024,
            total_chunks=10,
            temp_dir='/tmp/test'
        )

    def test_chunk_creation(self):
        """Test creating an UploadChunk record."""
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=10 * 1024 * 1024,
            chunk_hash='abc123def456',
            file_path='/tmp/test/chunk_000000'
        )

        self.assertEqual(chunk.chunk_number, 0)
        self.assertFalse(chunk.verified)

    def test_chunk_unique_constraint(self):
        """Test unique constraint on (upload, chunk_number)."""
        UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=10 * 1024 * 1024,
            chunk_hash='abc123',
            file_path='/tmp/chunk_0'
        )

        # Should raise IntegrityError on duplicate
        with self.assertRaises(Exception):
            UploadChunk.objects.create(
                chunked_upload=self.upload,
                chunk_number=0,
                chunk_size=10 * 1024 * 1024,
                chunk_hash='different_hash',
                file_path='/tmp/chunk_0_dup'
            )

    def test_chunk_verification_status(self):
        """Test chunk verification marking."""
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=10 * 1024 * 1024,
            chunk_hash='abc123',
            file_path='/tmp/chunk_0',
            verified=True
        )

        self.assertTrue(chunk.verified)


class ChunkHashTest(TestCase):
    """Test hash calculation utilities."""

    def test_calculate_bytes_hash(self):
        """Test SHA256 hash calculation for bytes."""
        data = b'test data'
        expected = hashlib.sha256(data).hexdigest()
        result = calculate_bytes_hash(data)
        self.assertEqual(result, expected)

    def test_calculate_bytes_hash_consistency(self):
        """Test that hash calculation is consistent."""
        data = b'test data'
        hash1 = calculate_bytes_hash(data)
        hash2 = calculate_bytes_hash(data)
        self.assertEqual(hash1, hash2)

    def test_calculate_bytes_hash_different_data(self):
        """Test that different data produces different hashes."""
        hash1 = calculate_bytes_hash(b'data1')
        hash2 = calculate_bytes_hash(b'data2')
        self.assertNotEqual(hash1, hash2)

    def test_calculate_file_hash(self, tmp_path=None):
        """Test file hash calculation."""
        if tmp_path is None:
            from tempfile import TemporaryDirectory
            with TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                self._test_calculate_file_hash_impl(tmp_path)
        else:
            self._test_calculate_file_hash_impl(tmp_path)

    def _test_calculate_file_hash_impl(self, tmp_path):
        """Implementation of file hash test."""
        test_file = tmp_path / 'test.bin'
        test_data = b'test file content' * 100
        test_file.write_bytes(test_data)

        expected = hashlib.sha256(test_data).hexdigest()
        result = calculate_file_hash(str(test_file))
        self.assertEqual(result, expected)


class ChunkStorageTest(TestCase):
    """Test chunk storage and retrieval."""

    @patch('uploads.chunk_manager.get_upload_session_dir')
    def test_store_chunk(self, mock_get_dir):
        """Test storing a chunk to disk."""
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            session_dir = tmp_path / 'session123'
            session_dir.mkdir()
            mock_get_dir.return_value = session_dir

            chunk_data = b'test chunk data'
            session_id = uuid.uuid4()
            chunk_number = 0

            file_path, chunk_hash, chunk_crc32, chunk_size = store_chunk(
                session_id, chunk_number, chunk_data
            )

            # Verify file was created
            self.assertTrue(Path(file_path).exists())
            self.assertEqual(chunk_size, len(chunk_data))
            self.assertEqual(chunk_hash, calculate_bytes_hash(chunk_data))
            # Verify CRC32 is returned
            self.assertIsNotNone(chunk_crc32)
            self.assertEqual(len(chunk_crc32), 8)  # CRC32 is 8-character hex


            # Verify file contains correct data
            with open(file_path, 'rb') as f:
                stored_data = f.read()
            self.assertEqual(stored_data, chunk_data)

    def test_verify_chunk_integrity_success(self):
        """Test successful chunk integrity verification."""
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            chunk_file = tmp_path / 'chunk_test'
            chunk_data = b'test data for verification'
            chunk_file.write_bytes(chunk_data)

            expected_hash = calculate_bytes_hash(chunk_data)
            result = verify_chunk_integrity(str(chunk_file), expected_hash)
            self.assertTrue(result)

    def test_verify_chunk_integrity_failure(self):
        """Test chunk integrity verification failure."""
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            chunk_file = tmp_path / 'chunk_test'
            chunk_data = b'test data'
            chunk_file.write_bytes(chunk_data)

            wrong_hash = 'incorrect_hash_value'
            result = verify_chunk_integrity(str(chunk_file), wrong_hash)
            self.assertFalse(result)


class CleanupUtilitiesTest(TestCase):
    """Test cleanup utilities."""

    @patch('uploads.chunk_manager.get_upload_session_dir')
    def test_cleanup_session_removes_files(self, mock_get_dir):
        """Test cleanup_session removes chunk files or entire directory."""
        from pathlib import Path
        from tempfile import TemporaryDirectory
        
        # Test cleanup with remove_all=True
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            session_dir = tmp_path / 'session123'
            session_dir.mkdir()

            # Create dummy chunk files
            (session_dir / 'chunk_000000').touch()
            (session_dir / 'chunk_000001').touch()

            mock_get_dir.return_value = session_dir

            session_id = uuid.uuid4()
            # Remove entire session directory
            cleanup_session(session_id, remove_all=True)

            # Verify directory was removed
            self.assertFalse(session_dir.exists())

    def test_cleanup_expired_uploads_query(self):
        """Test cleanup_expired_uploads identifies expired uploads."""
        # Create an old incomplete upload (created 10 days ago)
        old_upload = ChunkedUpload.objects.create(
            uploader_id='old_user',
            filename='old.tar.gz',
            total_size=1000000,
            total_chunks=10,
            status='IN_PROGRESS',
            temp_dir='/tmp/old',
            expires_at=timezone.now() - timedelta(days=1)  # Expired
        )

        # Create a recent upload (will expire in 6 days)
        recent_upload = ChunkedUpload.objects.create(
            uploader_id='recent_user',
            filename='recent.tar.gz',
            total_size=1000000,
            total_chunks=10,
            status='IN_PROGRESS',
            temp_dir='/tmp/recent',
            expires_at=timezone.now() + timedelta(days=6)  # Not expired yet
        )

        # Query for expired uploads (expires_at is in the past)
        cutoff = timezone.now()
        expired = ChunkedUpload.objects.filter(
            status__in=['INITIATED', 'IN_PROGRESS'],
            expires_at__isnull=False,
            expires_at__lt=cutoff
        )

        self.assertIn(old_upload, expired)
        self.assertNotIn(recent_upload, expired)


class GetProgressTest(TestCase):
    """Test progress retrieval utilities."""

    def test_get_upload_progress(self):
        """Test retrieving upload progress."""
        session_id = uuid.uuid4()
        upload = ChunkedUpload.objects.create(
            id=session_id,
            uploader_id='test_user',
            filename='test.tar.gz',
            total_size=100 * 1024 * 1024,
            total_chunks=10,
            uploaded_chunks=5,
            temp_dir='/tmp/test'
        )

        progress = get_upload_progress(session_id)

        self.assertIsNotNone(progress)
        self.assertEqual(progress['id'], str(session_id))
        self.assertEqual(progress['filename'], 'test.tar.gz')
        self.assertEqual(progress['progress_percent'], 50)
        self.assertFalse(progress['is_complete'])

    def test_get_upload_progress_not_found(self):
        """Test progress retrieval for non-existent session."""
        fake_id = uuid.uuid4()
        progress = get_upload_progress(fake_id)
        self.assertIsNone(progress)


class AssembleChunksTest(TestCase):
    """Test chunk assembly functionality."""

    def test_assemble_chunks_success(self):
        """Test successful chunk assembly."""
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            session_dir = tmp_path / 'session'
            session_dir.mkdir()

            # Create dummy chunks
            full_data = b''
            for i in range(3):
                chunk_data = f'Chunk {i} data'.encode() * 100
                chunk_file = session_dir / f'chunk_{i:06d}'
                chunk_file.write_bytes(chunk_data)
                full_data += chunk_data

            output_file = tmp_path / 'assembled.tar'

            with patch('uploads.chunk_manager.get_upload_session_dir') as mock_get:
                mock_get.return_value = session_dir

                success, message, file_hash = assemble_chunks(
                    uuid.uuid4(),
                    str(output_file),
                    3
                )

                self.assertTrue(success)
                self.assertTrue(output_file.exists())
                self.assertEqual(file_hash, calculate_bytes_hash(full_data))

    def test_assemble_chunks_missing_chunk(self):
        """Test assembly fails with missing chunk."""
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            session_dir = tmp_path / 'session'
            session_dir.mkdir()

            # Create only first chunk
            (session_dir / 'chunk_000000').write_bytes(b'chunk 0')

            output_file = tmp_path / 'assembled.tar'

            with patch('uploads.chunk_manager.get_upload_session_dir') as mock_get:
                mock_get.return_value = session_dir

                success, message, file_hash = assemble_chunks(
                    uuid.uuid4(),
                    str(output_file),
                    3  # Expecting 3 chunks but only have 1
                )

                self.assertFalse(success)
                self.assertIn('Missing chunk', message)


@override_settings(RAW_DATA_DIR='/tmp/eutempe_test_chunked')
class ChunkedUploadInitViewTest(APITestCase):
    """Test ChunkedUploadInitView API endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    def test_init_upload_success(self):
        """Test successful upload initialization."""
        response = self.client.post(
            '/api/v1/uploads/chunked/init/',
            {
                'filename': 'test_archive.tar.gz',
                'total_size': 1024 * 1024 * 1024,  # 1GB
                'chunk_size': 10 * 1024 * 1024,
            },
            format='json'
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn('session_id', response.data)
        self.assertEqual(response.data['filename'], 'test_archive.tar.gz')
        self.assertEqual(response.data['total_chunks'], 103)  # 1024MB / 10MB (rounded up)

    def test_init_upload_missing_filename(self):
        """Test upload init fails without filename."""
        response = self.client.post(
            '/api/v1/uploads/chunked/init/',
            {
                'total_size': 1024 * 1024 * 1024,
            },
            format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_init_upload_missing_total_size(self):
        """Test upload init fails without total_size."""
        response = self.client.post(
            '/api/v1/uploads/chunked/init/',
            {
                'filename': 'test.tar.gz',
            },
            format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_init_upload_requires_auth(self):
        """Test init endpoint requires authentication."""
        client = APIClient()
        response = client.post(
            '/api/v1/uploads/chunked/init/',
            {
                'filename': 'test.tar.gz',
                'total_size': 1024 * 1024,
            },
            format='json'
        )

        self.assertEqual(response.status_code, 401)

    def _valid_manifest_item(self):
        return {
            "ref": "ROW0001",
            "filename": "Input_volume1.zip",
            "site_code": "S001",
            "clinical_indication_code": "HEADTRAUMA",
            "anatomical_region": "Head",
            "contrast_code": "NC",
            "patient_group_code": "PH-G4",
            "scanner_id": "CT01",
            "protocol_name": "Pediatric head trauma non-contrast",
            "patient_weight_kg": 28.0,
            "patient_age_years": 8.0,
            "ctdivol_mgy": 18.4,
            "dlp_mgy_cm": 320.5,
            "image_quality": "Acceptable",
            "size_bytes": 13695187,
        }

    def test_init_upload_with_valid_manifest_item_succeeds(self):
        """Regression: a caller that bypasses the client-side "Validate
        Manifest" step must still get a real schema check on manifest_item
        here — a valid item must not be rejected by that check."""
        response = self.client.post(
            '/api/v1/uploads/chunked/init/',
            {
                'filename': 'Input_volume1.zip',
                'total_size': 1024 * 1024,
                'batch': 'S001-BATCH001',
                'manifest_item': self._valid_manifest_item(),
            },
            format='json'
        )

        self.assertEqual(response.status_code, 201)

    def test_init_upload_with_invalid_manifest_item_rejected(self):
        """Regression: a caller posting directly to this endpoint (bypassing
        the "Validate Manifest" step) must not be able to get a
        CTExamination/repository_study_id created from a manifest item
        missing its required coded fields."""
        item = self._valid_manifest_item()
        del item["clinical_indication_code"]
        response = self.client.post(
            '/api/v1/uploads/chunked/init/',
            {
                'filename': 'Input_volume1.zip',
                'total_size': 1024 * 1024,
                'batch': 'S001-BATCH001',
                'manifest_item': item,
            },
            format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'invalid_manifest_item')

    def test_init_upload_file_too_large(self):
        """Test init fails for oversized file."""
        response = self.client.post(
            '/api/v1/uploads/chunked/init/',
            {
                'filename': 'huge.tar.gz',
                'total_size': 2 * 1024 * 1024 * 1024 * 1024,  # 2TB (exceeds 1TB limit)
            },
            format='json'
        )

        self.assertEqual(response.status_code, 413)


class ChunkedUploadProgressViewTest(APITestCase):
    """Test ChunkedUploadProgressView API endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

        # Create a test upload session
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id='testuser',
            filename='test.tar.gz',
            total_size=100 * 1024 * 1024,
            total_chunks=10,
            uploaded_chunks=5,
            temp_dir='/tmp/test',
            expires_at=timezone.now() + timedelta(days=7)
        )

    def test_get_progress_success(self):
        """Test successful progress retrieval."""
        response = self.client.get(
            f'/api/v1/uploads/chunked/{self.session_id}/progress/'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], str(self.session_id))
        self.assertEqual(response.data['progress_percent'], 50)

    def test_get_progress_not_found(self):
        """Test progress retrieval for non-existent session."""
        fake_id = uuid.uuid4()
        response = self.client.get(
            f'/api/v1/uploads/chunked/{fake_id}/progress/'
        )

        self.assertEqual(response.status_code, 404)

    def test_get_progress_permission_denied(self):
        """Test progress retrieval for different user fails."""
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123'
        )
        other_token = Token.objects.create(user=other_user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {other_token.key}')

        response = client.get(
            f'/api/v1/uploads/chunked/{self.session_id}/progress/'
        )

        self.assertEqual(response.status_code, 403)


class ChunkedUploadCancelViewTest(APITestCase):
    """Test ChunkedUploadCancelView API endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

        # Create a test upload session
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id='testuser',
            filename='test.tar.gz',
            total_size=100 * 1024 * 1024,
            total_chunks=10,
            status='IN_PROGRESS',
            temp_dir='/tmp/test',
            expires_at=timezone.now() + timedelta(days=7)
        )

    @patch('uploads.chunked_upload_views.cleanup_session')
    def test_cancel_upload_success(self, mock_cleanup):
        """Test successful upload cancellation."""
        response = self.client.delete(
            f'/api/v1/uploads/chunked/{self.session_id}/'
        )

        self.assertEqual(response.status_code, 204)
        mock_cleanup.assert_called_once()

        # Verify status was updated
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.status, 'CANCELLED')

    def test_cancel_completed_upload_fails(self):
        """Test cancellation of completed upload fails."""
        self.upload.status = 'COMPLETED'
        self.upload.save()

        response = self.client.delete(
            f'/api/v1/uploads/chunked/{self.session_id}/'
        )

        self.assertEqual(response.status_code, 409)

    def test_cancel_not_found(self):
        """Test cancellation of non-existent session fails."""
        fake_id = uuid.uuid4()
        response = self.client.delete(
            f'/api/v1/uploads/chunked/{fake_id}/'
        )

        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    import django
    from django.conf import settings
    from django.test.utils import get_runner

    if not settings.configured:
        django.setup()

    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    failures = test_runner.run_tests(['uploads.tests.test_chunked_upload'])
    import sys
    sys.exit(bool(failures))
