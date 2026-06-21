"""
Unit tests for automatic chunk verification during upload.
Tests automatic verification, corruption detection, and resume capability.
"""

import io
import uuid
import hashlib
from datetime import timedelta

from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework.authtoken.models import Token
from rest_framework import status

from uploads.models import ChunkedUpload, UploadChunk
from uploads.chunk_manager import store_chunk, calculate_bytes_crc32, calculate_file_crc32


@override_settings(RAW_DATA_DIR='/tmp/eutempe_test_auto_verify')
class AutomaticVerificationDuringUploadTest(APITestCase):
    """Test automatic chunk verification during upload."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

        # Create upload session
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id=self.user.username,
            filename='test_auto_verify.tar.gz',
            total_size=50 * 1024 * 1024,  # 50 MB
            total_chunks=5,
            chunk_size=10 * 1024 * 1024,  # 10 MB chunks
            expires_at=timezone.now() + timedelta(days=7)
        )

    def test_chunk_upload_returns_verification_status(self):
        """Test that chunk upload returns verification status."""
        chunk_data = b"Test chunk data for verification"
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()

        response = self.client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/chunk/?chunk_number=0&chunk_hash={chunk_hash}',
            data=chunk_data,
            content_type='application/octet-stream'
        )

        self.assertEqual(response.status_code, 202)
        data = response.json()
        
        # Check that verification info is included in response
        self.assertIn('verification_status', data)
        self.assertIn('verification_success', data)
        self.assertIn('needs_reupload', data)
        self.assertIn('verified_chunks', data)
        self.assertIn('corrupted_chunks', data)

    def test_chunk_marked_verified_on_successful_upload(self):
        """Test that chunk is marked VERIFIED after successful upload."""
        chunk_data = b"Test chunk for verification success"
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()

        response = self.client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/chunk/?chunk_number=0&chunk_hash={chunk_hash}',
            data=chunk_data,
            content_type='application/octet-stream'
        )

        self.assertEqual(response.status_code, 202)
        data = response.json()
        
        # Check response indicates success
        self.assertTrue(data['verification_success'])
        self.assertEqual(data['verification_status'], UploadChunk.VERIFICATION_VERIFIED)
        self.assertFalse(data['needs_reupload'])

        # Check database has correct status
        chunk = UploadChunk.objects.get(chunked_upload=self.upload, chunk_number=0)
        self.assertEqual(chunk.verification_status, UploadChunk.VERIFICATION_VERIFIED)
        self.assertIsNotNone(chunk.verification_timestamp)

    def test_multiple_chunks_verified_on_upload(self):
        """Test that multiple chunks are verified as they're uploaded."""
        for chunk_num in range(3):
            chunk_data = f"Chunk {chunk_num}".encode()
            chunk_hash = hashlib.sha256(chunk_data).hexdigest()

            response = self.client.post(
                f'/api/v1/uploads/chunked/{self.session_id}/chunk/?chunk_number={chunk_num}&chunk_hash={chunk_hash}',
                data=chunk_data,
                content_type='application/octet-stream'
            )

            self.assertEqual(response.status_code, 202)
            data = response.json()
            self.assertEqual(data['verified_chunks'], chunk_num + 1)

        # Verify all chunks are marked as verified
        verified = UploadChunk.objects.filter(
            chunked_upload=self.upload,
            verification_status=UploadChunk.VERIFICATION_VERIFIED
        ).count()
        self.assertEqual(verified, 3)

    def test_chunk_verification_with_crc32(self):
        """Test that CRC32 is also verified during upload."""
        chunk_data = b"Test CRC32 verification"
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()

        response = self.client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/chunk/?chunk_number=0&chunk_hash={chunk_hash}',
            data=chunk_data,
            content_type='application/octet-stream'
        )

        self.assertEqual(response.status_code, 202)
        
        # Check chunk record has CRC32
        chunk = UploadChunk.objects.get(chunked_upload=self.upload, chunk_number=0)
        self.assertIsNotNone(chunk.chunk_crc32)
        # CRC32 should be 8-character hex string
        self.assertEqual(len(chunk.chunk_crc32), 8)

    def test_response_summary_with_mixed_chunks(self):
        """Test response includes summary of verified/corrupted chunks."""
        # Upload first chunk (clean)
        chunk_data = b"Clean chunk"
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()

        self.client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/chunk/?chunk_number=0&chunk_hash={chunk_hash}',
            data=chunk_data,
            content_type='application/octet-stream'
        )

        # Upload second chunk (clean)
        chunk_data = b"Another clean chunk"
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()

        response = self.client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/chunk/?chunk_number=1&chunk_hash={chunk_hash}',
            data=chunk_data,
            content_type='application/octet-stream'
        )

        data = response.json()
        self.assertEqual(data['verified_chunks'], 2)
        self.assertEqual(data['corrupted_chunks'], 0)


@override_settings(RAW_DATA_DIR='/tmp/eutempe_test_auto_verify')
class ResumeUploadCapabilityTest(APITestCase):
    """Test resuming uploads after detecting corruption."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

        # Create upload session
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id=self.user.username,
            filename='test_resume.tar.gz',
            total_size=50 * 1024 * 1024,
            total_chunks=5,
            chunk_size=10 * 1024 * 1024,
            expires_at=timezone.now() + timedelta(days=7)
        )

    def test_upload_status_endpoint_exists(self):
        """Test that upload status endpoint exists and returns data."""
        response = self.client.get(
            f'/api/v1/uploads/chunked/{self.session_id}/status/'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check expected fields
        self.assertIn('total_chunks', data)
        self.assertIn('verified_chunks', data)
        self.assertIn('corrupted_chunks', data)
        self.assertIn('needs_reupload', data)
        self.assertIn('chunks_status', data)

    def test_status_shows_which_chunks_need_reupload(self):
        """Test that status endpoint shows which chunks need to be re-uploaded."""
        # Upload some chunks
        for chunk_num in range(3):
            chunk_data = f"Chunk {chunk_num}".encode()
            chunk_hash = hashlib.sha256(chunk_data).hexdigest()

            self.client.post(
                f'/api/v1/uploads/chunked/{self.session_id}/chunk/?chunk_number={chunk_num}&chunk_hash={chunk_hash}',
                data=chunk_data,
                content_type='application/octet-stream'
            )

        # Manually corrupt one chunk to simulate corruption detection
        corrupted_chunk = UploadChunk.objects.get(chunked_upload=self.upload, chunk_number=1)
        corrupted_chunk.verification_status = UploadChunk.VERIFICATION_CORRUPTED
        corrupted_chunk.verification_error = "CRC32 mismatch during automatic verification"
        corrupted_chunk.save()

        # Get status
        response = self.client.get(
            f'/api/v1/uploads/chunked/{self.session_id}/status/'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check that the corrupted chunk is listed
        self.assertIn(1, data['needs_reupload'])
        self.assertEqual(data['corrupted_chunks'], 1)
        self.assertEqual(data['verified_chunks'], 2)
        
        # Check detailed status includes the error
        chunk_statuses = {c['chunk_number']: c for c in data['chunks_status']}
        self.assertEqual(chunk_statuses[1]['status'], UploadChunk.VERIFICATION_CORRUPTED)
        self.assertIn('error', chunk_statuses[1])

    def test_upload_can_resume_flag(self):
        """Test that upload_can_resume flag indicates if resumption is possible."""
        # Upload some chunks
        for chunk_num in range(2):
            chunk_data = f"Chunk {chunk_num}".encode()
            chunk_hash = hashlib.sha256(chunk_data).hexdigest()

            self.client.post(
                f'/api/v1/uploads/chunked/{self.session_id}/chunk/?chunk_number={chunk_num}&chunk_hash={chunk_hash}',
                data=chunk_data,
                content_type='application/octet-stream'
            )

        response = self.client.get(
            f'/api/v1/uploads/chunked/{self.session_id}/status/'
        )

        data = response.json()
        # With 2 good chunks out of 5, we can resume
        self.assertTrue(data['upload_can_resume'])
        self.assertEqual(data['estimated_remaining_uploads'], 0)  # None corrupted yet

    def test_permission_check_on_status_endpoint(self):
        """Test that only the uploader can view status."""
        # Create another user
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123'
        )
        other_token = Token.objects.create(user=other_user)
        other_client = APIClient()
        other_client.credentials(HTTP_AUTHORIZATION=f'Token {other_token.key}')

        # Try to get status with other user
        response = other_client.get(
            f'/api/v1/uploads/chunked/{self.session_id}/status/'
        )

        self.assertEqual(response.status_code, 403)

    def test_nonexistent_session_returns_404(self):
        """Test that nonexistent session returns 404."""
        fake_session_id = uuid.uuid4()

        response = self.client.get(
            f'/api/v1/uploads/chunked/{fake_session_id}/status/'
        )

        self.assertEqual(response.status_code, 404)


class UploadChunkVerificationStateTest(TestCase):
    """Test UploadChunk verification state transitions."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id=self.user.username,
            filename='test.tar.gz',
            total_size=10 * 1024 * 1024,
            total_chunks=1,
            chunk_size=10 * 1024 * 1024,
            expires_at=timezone.now() + timedelta(days=7)
        )

    def test_chunk_created_with_pending_status(self):
        """Test that new chunks can be created with PENDING status."""
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=1024,
            chunk_hash='abc123',
            file_path='/tmp/chunk_0',
            verification_status=UploadChunk.VERIFICATION_PENDING
        )

        self.assertEqual(chunk.verification_status, UploadChunk.VERIFICATION_PENDING)
        self.assertFalse(chunk.is_verified())
        self.assertFalse(chunk.needs_reupload())

    def test_is_verified_check(self):
        """Test is_verified() method."""
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=1024,
            chunk_hash='abc123',
            file_path='/tmp/chunk_0',
            verification_status=UploadChunk.VERIFICATION_VERIFIED
        )

        self.assertTrue(chunk.is_verified())
        self.assertFalse(chunk.needs_reupload())

    def test_needs_reupload_check(self):
        """Test needs_reupload() method."""
        # Test CORRUPTED status
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=1024,
            chunk_hash='abc123',
            file_path='/tmp/chunk_0',
            verification_status=UploadChunk.VERIFICATION_CORRUPTED
        )

        self.assertFalse(chunk.is_verified())
        self.assertTrue(chunk.needs_reupload())

    def test_verification_error_storage(self):
        """Test that verification errors are stored."""
        error_msg = "SHA256 mismatch: expected abc..., got def..."
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=1024,
            chunk_hash='abc123',
            file_path='/tmp/chunk_0',
            verification_status=UploadChunk.VERIFICATION_CORRUPTED,
            verification_error=error_msg
        )

        self.assertEqual(chunk.verification_error, error_msg)

    def test_verification_timestamp_recorded(self):
        """Test that verification timestamp is recorded."""
        now = timezone.now()
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=1024,
            chunk_hash='abc123',
            file_path='/tmp/chunk_0',
            verification_status=UploadChunk.VERIFICATION_VERIFIED,
            verification_timestamp=now
        )

        self.assertEqual(chunk.verification_timestamp, now)

    def test_backward_compatibility_verified_field(self):
        """Test that verified field still works for backward compatibility."""
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=1024,
            chunk_hash='abc123',
            file_path='/tmp/chunk_0',
            verified=True,
            verification_status=UploadChunk.VERIFICATION_VERIFIED
        )

        self.assertTrue(chunk.verified)
        self.assertTrue(chunk.is_verified())


@override_settings(RAW_DATA_DIR='/tmp/eutempe_test_auto_verify')
class UploadProgressResponseTest(APITestCase):
    """Test detailed information in chunk upload responses."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

        # Create upload session
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id=self.user.username,
            filename='test_response.tar.gz',
            total_size=30 * 1024 * 1024,
            total_chunks=3,
            chunk_size=10 * 1024 * 1024,
            expires_at=timezone.now() + timedelta(days=7)
        )

    def test_chunk_response_includes_reupload_flag(self):
        """Test that chunk upload response includes needs_reupload flag."""
        chunk_data = b"Test chunk"
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()

        response = self.client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/chunk/?chunk_number=0&chunk_hash={chunk_hash}',
            data=chunk_data,
            content_type='application/octet-stream'
        )

        data = response.json()
        self.assertIn('needs_reupload', data)
        self.assertFalse(data['needs_reupload'])  # Successful upload shouldn't need reupload

    def test_response_updates_as_chunks_uploaded(self):
        """Test that response provides cumulative status as more chunks are uploaded."""
        for chunk_num in range(2):
            chunk_data = f"Chunk {chunk_num}".encode()
            chunk_hash = hashlib.sha256(chunk_data).hexdigest()

            response = self.client.post(
                f'/api/v1/uploads/chunked/{self.session_id}/chunk/?chunk_number={chunk_num}&chunk_hash={chunk_hash}',
                data=chunk_data,
                content_type='application/octet-stream'
            )

            data = response.json()
            self.assertEqual(data['verified_chunks'], chunk_num + 1)
            self.assertEqual(data['corrupted_chunks'], 0)
