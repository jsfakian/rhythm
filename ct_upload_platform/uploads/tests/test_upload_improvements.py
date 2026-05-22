"""
Unit tests for Upload Improvements: Early Validation & Corruption Detection.

Tests cover:
- ManifestValidationView (new endpoint for early manifest validation)
- ChunkVerificationView (new endpoint for corruption detection)
- CRC32 computation functions
- Enhanced chunk verification with dual-hash strategy
- UploadChunk model with chunk_crc32 field
"""

import hashlib
import json
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
    calculate_bytes_crc32,
    calculate_file_crc32,
    verify_chunk_with_crc32,
    verify_uploaded_chunks,
    store_chunk,
    get_upload_session_dir,
    cleanup_session,
)
from uploads.manifest_schema import validate_manifest


# ============================================================================
# CRC32 COMPUTATION TESTS
# ============================================================================

class CRC32ComputationTest(TestCase):
    """Test CRC32 checksum computation functions."""

    def test_calculate_bytes_crc32(self):
        """Test CRC32 computation for bytes."""
        test_data = b"Hello, World!"
        crc32_hash = calculate_bytes_crc32(test_data)
        
        # CRC32 should return an 8-character hex string
        self.assertEqual(len(crc32_hash), 8)
        self.assertTrue(all(c in '0123456789abcdef' for c in crc32_hash))
    
    def test_calculate_bytes_crc32_deterministic(self):
        """Test that CRC32 computation is deterministic."""
        test_data = b"Test Data"
        crc32_1 = calculate_bytes_crc32(test_data)
        crc32_2 = calculate_bytes_crc32(test_data)
        
        self.assertEqual(crc32_1, crc32_2)
    
    def test_calculate_bytes_crc32_different_data(self):
        """Test that different data produces different CRC32."""
        crc32_1 = calculate_bytes_crc32(b"Data1")
        crc32_2 = calculate_bytes_crc32(b"Data2")
        
        self.assertNotEqual(crc32_1, crc32_2)
    
    @override_settings(RAW_DATA_DIR='/tmp/test_uploads')
    def test_calculate_file_crc32(self):
        """Test CRC32 computation for files."""
        import tempfile
        import os
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"File Content")
            temp_path = f.name
        
        try:
            crc32_hash = calculate_file_crc32(temp_path)
            
            # CRC32 should return an 8-character hex string
            self.assertEqual(len(crc32_hash), 8)
            self.assertTrue(all(c in '0123456789abcdef' for c in crc32_hash))
        finally:
            os.unlink(temp_path)
    
    @override_settings(RAW_DATA_DIR='/tmp/test_uploads')
    def test_calculate_file_crc32_matches_bytes(self):
        """Test that file CRC32 matches bytes CRC32."""
        import tempfile
        import os
        
        test_data = b"Test Data Content"
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(test_data)
            temp_path = f.name
        
        try:
            crc32_file = calculate_file_crc32(temp_path)
            crc32_bytes = calculate_bytes_crc32(test_data)
            
            self.assertEqual(crc32_file, crc32_bytes)
        finally:
            os.unlink(temp_path)


# ============================================================================
# CHUNK VERIFICATION TESTS
# ============================================================================

class ChunkVerificationTest(TestCase):
    """Test chunk verification with CRC32."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id='test_user',
            filename='test_archive.tar.gz',
            total_size=100 * 1024 * 1024,
            total_chunks=10,
            chunk_size=10 * 1024 * 1024,
            temp_dir=str(get_upload_session_dir(self.session_id)),
            expires_at=timezone.now() + timedelta(days=7)
        )
    
    def test_verify_chunk_with_crc32_match(self):
        """Test CRC32 verification when checksums match."""
        import tempfile
        import os
        
        test_data = b"Test chunk data"
        expected_crc32 = calculate_bytes_crc32(test_data)
        
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(test_data)
            temp_path = f.name
        
        try:
            result = verify_chunk_with_crc32(temp_path, expected_crc32)
            self.assertTrue(result)
        finally:
            os.unlink(temp_path)
    
    def test_verify_chunk_with_crc32_mismatch(self):
        """Test CRC32 verification when checksums don't match."""
        import tempfile
        import os
        
        test_data = b"Test chunk data"
        wrong_crc32 = "deadbeef"
        
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(test_data)
            temp_path = f.name
        
        try:
            result = verify_chunk_with_crc32(temp_path, wrong_crc32)
            self.assertFalse(result)
        finally:
            os.unlink(temp_path)


# ============================================================================
# CHUNK MODEL TESTS
# ============================================================================

class UploadChunkModelTest(TestCase):
    """Test UploadChunk model with chunk_crc32 field."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id='test_user',
            filename='test.tar.gz',
            total_size=100 * 1024 * 1024,
            total_chunks=10,
            chunk_size=10 * 1024 * 1024,
            temp_dir='/tmp/test',
            expires_at=timezone.now() + timedelta(days=7)
        )
    
    def test_chunk_crc32_field_nullable(self):
        """Test that chunk_crc32 field is nullable."""
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=1024,
            chunk_hash='abc123',
            file_path='/tmp/chunk_0',
            verified=True
        )
        
        # Should save without chunk_crc32
        self.assertIsNone(chunk.chunk_crc32)
    
    def test_chunk_crc32_field_storage(self):
        """Test storing and retrieving chunk_crc32."""
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=1024,
            chunk_hash='abc123',
            chunk_crc32='deadbeef',
            file_path='/tmp/chunk_0',
            verified=True
        )
        
        # Retrieve and verify
        retrieved = UploadChunk.objects.get(chunk_number=0, chunked_upload=self.upload)
        self.assertEqual(retrieved.chunk_crc32, 'deadbeef')
    
    def test_chunk_crc32_validation(self):
        """Test that chunk_crc32 is a valid 8-character hex string."""
        # Valid CRC32 (8 hex chars)
        chunk = UploadChunk.objects.create(
            chunked_upload=self.upload,
            chunk_number=0,
            chunk_size=1024,
            chunk_hash='abc123',
            chunk_crc32='12345678',
            file_path='/tmp/chunk_0',
            verified=True
        )
        self.assertEqual(len(chunk.chunk_crc32), 8)


# ============================================================================
# STORE CHUNK WITH CRC32 TESTS
# ============================================================================

class StoreChunkWithCRC32Test(TestCase):
    """Test enhanced store_chunk function that returns CRC32."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id='test_user',
            filename='test.tar.gz',
            total_size=100 * 1024 * 1024,
            total_chunks=10,
            chunk_size=10 * 1024 * 1024,
            temp_dir=str(get_upload_session_dir(self.session_id)),
            expires_at=timezone.now() + timedelta(days=7)
        )
    
    def test_store_chunk_returns_four_values(self):
        """Test that store_chunk returns (path, sha256, crc32, size)."""
        chunk_data = b"Test chunk data"
        
        result = store_chunk(self.session_id, 0, chunk_data)
        
        self.assertEqual(len(result), 4)
        path, sha256, crc32, size = result
        
        # Verify each return value
        self.assertIsInstance(path, str)
        self.assertIsInstance(sha256, str)
        self.assertIsInstance(crc32, str)
        self.assertEqual(size, len(chunk_data))
    
    def test_store_chunk_crc32_computation(self):
        """Test that store_chunk correctly computes CRC32."""
        chunk_data = b"Test data for CRC32"
        expected_crc32 = calculate_bytes_crc32(chunk_data)
        
        path, sha256, crc32, size = store_chunk(self.session_id, 0, chunk_data)
        
        self.assertEqual(crc32, expected_crc32)
    
    def test_store_chunk_sha256_computation(self):
        """Test that store_chunk correctly computes SHA256."""
        chunk_data = b"Test data for SHA256"
        expected_sha256 = hashlib.sha256(chunk_data).hexdigest()
        
        path, sha256, crc32, size = store_chunk(self.session_id, 0, chunk_data)
        
        self.assertEqual(sha256, expected_sha256)


# ============================================================================
# VERIFY UPLOADED CHUNKS TESTS
# ============================================================================

class VerifyUploadedChunksTest(TestCase):
    """Test comprehensive chunk verification with corruption detection."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id='test_user',
            filename='test.tar.gz',
            total_size=100 * 1024 * 1024,
            total_chunks=5,
            chunk_size=10 * 1024 * 1024,
            temp_dir=str(get_upload_session_dir(self.session_id)),
            expires_at=timezone.now() + timedelta(days=7)
        )
    
    def test_verify_uploaded_chunks_nonexistent_session(self):
        """Test verification on nonexistent session."""
        fake_session_id = uuid.uuid4()
        
        result = verify_uploaded_chunks(fake_session_id)
        
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['total_checked'], 0)
        self.assertEqual(len(result['corrupted_chunks']), 1)
    
    def test_verify_uploaded_chunks_no_chunks_uploaded(self):
        """Test verification when no chunks exist."""
        result = verify_uploaded_chunks(self.session_id)
        
        # Should check all 5 chunks, all should be missing
        self.assertEqual(result['total_checked'], 5)
        self.assertEqual(result['passed'], 0)
        self.assertEqual(result['failed'], 5)
        self.assertEqual(len(result['corrupted_chunks']), 5)
    
    def test_verify_uploaded_chunks_all_good(self):
        """Test verification when all chunks are valid."""
        # Create chunks with valid hashes
        chunk_data = b"Test chunk data"
        sha256 = hashlib.sha256(chunk_data).hexdigest()
        crc32 = calculate_bytes_crc32(chunk_data)
        
        for i in range(3):
            # Store the chunk
            path, computed_sha256, computed_crc32, size = store_chunk(
                self.session_id, i, chunk_data
            )
            
            # Create UploadChunk record
            UploadChunk.objects.create(
                chunked_upload=self.upload,
                chunk_number=i,
                chunk_size=size,
                chunk_hash=computed_sha256,
                chunk_crc32=computed_crc32,
                file_path=path,
                verified=True
            )
        
        result = verify_uploaded_chunks(self.session_id, chunk_numbers=range(3))
        
        self.assertEqual(result['total_checked'], 3)
        self.assertEqual(result['passed'], 3)
        self.assertEqual(result['failed'], 0)
    
    def test_verify_specific_chunks(self):
        """Test verifying only specific chunks."""
        # Create some chunks
        for i in range(5):
            path, sha256, crc32, size = store_chunk(
                self.session_id, i, b"Data for chunk " + str(i).encode()
            )
            UploadChunk.objects.create(
                chunked_upload=self.upload,
                chunk_number=i,
                chunk_size=size,
                chunk_hash=sha256,
                chunk_crc32=crc32,
                file_path=path,
                verified=True
            )
        
        # Verify only chunks 1 and 3
        result = verify_uploaded_chunks(self.session_id, chunk_numbers=[1, 3])
        
        self.assertEqual(result['total_checked'], 2)
        self.assertEqual(result['passed'], 2)
        self.assertEqual(result['failed'], 0)


# ============================================================================
# MANIFEST VALIDATION VIEW TESTS
# ============================================================================

class ManifestValidationViewTest(APITestCase):
    """Test ManifestValidationView for early manifest validation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        
        # Create test user and token
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        
        # Valid manifest template
        self.valid_manifest = {
            "manifest_version": "1.0",
            "upload_id": str(uuid.uuid4()),
            "created_at": "2026-02-26T10:00:00Z",
            "patient": {
                "pseudo_id": "patient_test_123",
                "sex": "M",
                "age_at_acquisition": 45,
                "cohort_tag": "test"
            },
            "study": {
                "study_uid": "1.2.3.4.5",
                "acquisition_date": "2026-02-20",
                "contrast_used": False,
                "notes": ""
            },
            "images": [
                {
                    "filename": "image_001.dcm",
                    "checksum_sha256": "a" * 64,
                    "series_uid": "1.2.3.4.5.1",
                    "body_part": "CHEST"
                }
            ]
        }
    
    def test_validate_manifest_valid(self):
        """Test validating a valid manifest."""
        response = self.client.post(
            '/api/v1/uploads/validate-manifest/',
            {"manifest": self.valid_manifest},
            format='json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['valid'])
        self.assertEqual(data['errors'], [])
    
    def test_validate_manifest_missing_required_field(self):
        """Test validation fails when required field is missing."""
        # Remove required patient.pseudo_id
        del self.valid_manifest['patient']['pseudo_id']
        
        response = self.client.post(
            '/api/v1/uploads/validate-manifest/',
            {"manifest": self.valid_manifest},
            format='json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['valid'])
        self.assertGreater(len(data['errors']), 0)
    
    def test_validate_manifest_invalid_pseudo_id_pattern(self):
        """Test validation fails on invalid pseudo_id pattern."""
        # pseudo_id too short
        self.valid_manifest['patient']['pseudo_id'] = "abc"
        
        response = self.client.post(
            '/api/v1/uploads/validate-manifest/',
            {"manifest": self.valid_manifest},
            format='json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['valid'])
        self.assertGreater(len(data['errors']), 0)
    
    def test_validate_manifest_invalid_checksum(self):
        """Test validation fails on invalid SHA256 checksum."""
        # Invalid checksum (not 64 hex chars)
        self.valid_manifest['images'][0]['checksum_sha256'] = "invalid_checksum"
        
        response = self.client.post(
            '/api/v1/uploads/validate-manifest/',
            {"manifest": self.valid_manifest},
            format='json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['valid'])
    
    def test_validate_manifest_missing_manifest_field(self):
        """Test validation fails when manifest field is missing."""
        response = self.client.post(
            '/api/v1/uploads/validate-manifest/',
            {},  # No manifest field
            format='json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['valid'])
    
    def test_validate_manifest_duplicate_filenames(self):
        """Test validation fails on duplicate filenames."""
        # Add duplicate image
        self.valid_manifest['images'].append({
            "filename": "image_001.dcm",  # Duplicate!
            "checksum_sha256": "b" * 64,
            "series_uid": "1.2.3.4.5.2",
            "body_part": "CHEST"
        })
        
        response = self.client.post(
            '/api/v1/uploads/validate-manifest/',
            {"manifest": self.valid_manifest},
            format='json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['valid'])
        # Should have error about duplicate filename
        self.assertGreater(len(data['errors']), 0)
    
    def test_validate_manifest_future_date(self):
        """Test validation fails on future acquisition date."""
        from datetime import datetime, timedelta
        future_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        self.valid_manifest['study']['acquisition_date'] = future_date
        
        response = self.client.post(
            '/api/v1/uploads/validate-manifest/',
            {"manifest": self.valid_manifest},
            format='json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['valid'])
    
    def test_validate_manifest_authentication_required(self):
        """Test that endpoint requires authentication."""
        # Create unauthenticated client
        unauthenticated_client = APIClient()
        
        response = unauthenticated_client.post(
            '/api/v1/uploads/validate-manifest/',
            {"manifest": self.valid_manifest},
            format='json'
        )
        
        self.assertEqual(response.status_code, 401)


# ============================================================================
# CHUNK VERIFICATION VIEW TESTS
# ============================================================================

class ChunkVerificationViewTest(APITestCase):
    """Test ChunkVerificationView for corruption detection endpoint."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        
        # Create test user and token
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        
        # Create upload session
        self.session_id = uuid.uuid4()
        self.upload = ChunkedUpload.objects.create(
            id=self.session_id,
            uploader_id=self.user.username,
            filename='test.tar.gz',
            total_size=100 * 1024 * 1024,
            total_chunks=5,
            chunk_size=10 * 1024 * 1024,
            temp_dir=str(get_upload_session_dir(self.session_id)),
            expires_at=timezone.now() + timedelta(days=7)
        )
    
    def test_verify_chunks_nonexistent_session(self):
        """Test verification on nonexistent session."""
        fake_session_id = uuid.uuid4()
        
        response = self.client.post(
            f'/api/v1/uploads/chunked/{fake_session_id}/verify/'
        )
        
        self.assertEqual(response.status_code, 404)
    
    def test_verify_chunks_no_chunks_uploaded(self):
        """Test verification when no chunks uploaded."""
        response = self.client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/verify/'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['verification_status'], 'corruption_detected')
        self.assertGreater(data['failed'], 0)
        self.assertGreater(len(data['corrupted_chunks']), 0)
    
    def test_verify_chunks_all_healthy(self):
        """Test verification when all chunks are healthy."""
        # Create 5 chunks to match total_chunks=5
        for i in range(5):
            path, sha256, crc32, size = store_chunk(
                self.session_id, i, b"Chunk data " + str(i).encode()
            )
            UploadChunk.objects.create(
                chunked_upload=self.upload,
                chunk_number=i,
                chunk_size=size,
                chunk_hash=sha256,
                chunk_crc32=crc32,
                file_path=path,
                verified=True
            )
        
        response = self.client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/verify/'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['verification_status'], 'success')
        self.assertEqual(data['passed'], 5)
        self.assertEqual(data['failed'], 0)
        self.assertFalse(data['recommend_restart'])
    
    def test_verify_specific_chunks(self):
        """Test verifying specific chunks."""
        # Create chunks
        for i in range(5):
            path, sha256, crc32, size = store_chunk(
                self.session_id, i, b"Chunk " + str(i).encode()
            )
            UploadChunk.objects.create(
                chunked_upload=self.upload,
                chunk_number=i,
                chunk_size=size,
                chunk_hash=sha256,
                chunk_crc32=crc32,
                file_path=path,
                verified=True
            )
        
        response = self.client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/verify/?chunk_numbers=0,2,4'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total_checked'], 3)
        self.assertEqual(data['passed'], 3)
    
    def test_verify_chunks_invalid_chunk_numbers(self):
        """Test verification with invalid chunk_numbers parameter."""
        response = self.client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/verify/?chunk_numbers=invalid,data'
        )
        
        self.assertEqual(response.status_code, 400)
    
    def test_verify_chunks_permission_denied(self):
        """Test verification with wrong user."""
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123'
        )
        other_token = Token.objects.create(user=other_user)
        
        other_client = APIClient()
        other_client.credentials(HTTP_AUTHORIZATION=f'Token {other_token.key}')
        
        response = other_client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/verify/'
        )
        
        self.assertEqual(response.status_code, 403)
    
    def test_verify_chunks_authentication_required(self):
        """Test that endpoint requires authentication."""
        unauthenticated_client = APIClient()
        
        response = unauthenticated_client.post(
            f'/api/v1/uploads/chunked/{self.session_id}/verify/'
        )
        
        self.assertEqual(response.status_code, 401)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class UploadImprovementsIntegrationTest(APITestCase):
    """Integration tests for early validation + chunk verification workflow."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        
        # Create test user and token
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
    
    def test_full_workflow_validate_then_upload(self):
        """Test complete workflow: validate manifest, then verify chunks."""
        # Step 1: Validate manifest
        manifest = {
            "manifest_version": "1.0",
            "upload_id": str(uuid.uuid4()),
            "created_at": "2026-02-26T10:00:00Z",
            "patient": {"pseudo_id": "test_patient_001", "sex": "M", "age_at_acquisition": 50},
            "study": {"study_uid": "1.2.3", "acquisition_date": "2026-02-20", "contrast_used": False},
            "images": [{"filename": "img.dcm", "checksum_sha256": "a" * 64, "series_uid": "1.2.3.1", "body_part": "CHEST"}]
        }
        
        response = self.client.post(
            '/api/v1/uploads/validate-manifest/',
            {"manifest": manifest},
            format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['valid'])
        
        # Step 2: Initialize chunked upload
        upload_response = self.client.post(
            '/api/v1/uploads/chunked/init/',
            {
                "filename": "test.tar.gz",
                "total_size": 100 * 1024 * 1024,
                "chunk_size": 10 * 1024 * 1024
            },
            format='json'
        )
        self.assertEqual(upload_response.status_code, 201)
        session_id = upload_response.json()['session_id']
        
        # Step 3: Upload a chunk
        chunk_data = b"test chunk data"
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()
        
        chunk_response = self.client.post(
            f'/api/v1/uploads/chunked/{session_id}/chunk/?chunk_number=0&chunk_hash={chunk_hash}',
            chunk_data,
            content_type='application/octet-stream'
        )
        self.assertEqual(chunk_response.status_code, 202)
        
        # Step 4: Verify chunks
        verify_response = self.client.post(
            f'/api/v1/uploads/chunked/{session_id}/verify/'
        )
        self.assertEqual(verify_response.status_code, 200)
        verify_data = verify_response.json()
        self.assertIn(verify_data['verification_status'], ['success', 'corruption_detected'])


if __name__ == '__main__':
    import unittest
    unittest.main()
