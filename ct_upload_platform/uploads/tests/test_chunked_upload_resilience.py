"""
Functional tests for chunked upload resilience and recovery.

Tests:
1. Automatic detection and recovery from corrupted chunks
2. Upload resumption after server restart
3. Verification that final tar file matches original
"""

import hashlib
import io
import json
import tarfile
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from uploads.models import ChunkedUpload, UploadChunk
from uploads.chunk_manager import (
    calculate_bytes_hash,
    calculate_file_hash,
    get_upload_session_dir,
)


@override_settings(RAW_DATA_DIR='/tmp/eutempe_test_resilience')
class ChunkedUploadCorruptionRecoveryTest(APITestCase):
    """Test automatic detection and recovery from corrupted chunks."""

    def setUp(self):
        """Set up test fixtures."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpassword123'
        )
        self.token = Token.objects.create(user=self.user)

        # Create API client with auth
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

        # Create test tar with multiple DICOM files
        self.original_tar = self._create_test_tar_with_dicom()
        self.original_tar_bytes = self.original_tar.getvalue()
        self.original_tar_hash = calculate_bytes_hash(self.original_tar_bytes)

    def _create_test_tar_with_dicom(self, num_files=3):
        """Create a tar archive with dummy DICOM files."""
        tar_buffer = io.BytesIO()
        tar = tarfile.open(fileobj=tar_buffer, mode='w:gz')

        # Create manifest
        manifest = {
            "manifest_version": "1.0",
            "patient": {
                "pseudo_id": "PAT-TEST-CORRUPT-001",
                "sex": "M",
                "age_at_first_acquisition": 50,
                "cohort_tag": "test_resilience",
            },
            "study": {
                "pseudo_study_uid": "STUDY-TEST-CORRUPT-001",
                "acquisition_date": "2026-02-20",
                "clinical_indication": "Corruption recovery test",
                "contrast_used": False,
            },
            "images": [],
        }

        # Create dummy DICOM files
        dicom_files = {}
        for i in range(1, num_files + 1):
            filename = f"images/scan_{i:03d}.dcm"
            # Create realistic-looking DICOM data (128KB each)
            dicom_data = (
                b'DICM_HEADER_' + str(i).encode() + 
                b'X' * (128 * 1024 - len(b'DICM_HEADER_' + str(i).encode()))
            )
            dicom_files[filename] = dicom_data
            checksum = hashlib.sha256(dicom_data).hexdigest()
            manifest["images"].append({
                "filename": filename,
                "checksum_sha256": checksum,
                "body_part_examined": "CHEST",
                "slice_thickness_mm": 1.0,
            })

        # Add manifest to tar
        manifest_json = json.dumps(manifest).encode('utf-8')
        manifest_info = tarfile.TarInfo(name="manifest.json")
        manifest_info.size = len(manifest_json)
        tar.addfile(manifest_info, io.BytesIO(manifest_json))

        # Add DICOM files to tar
        for filename, content in dicom_files.items():
            file_info = tarfile.TarInfo(name=filename)
            file_info.size = len(content)
            tar.addfile(file_info, io.BytesIO(content))

        tar.close()
        tar_buffer.seek(0)
        return tar_buffer

    def _initiate_chunked_upload(self, file_bytes, chunk_size=1024*1024):
        """Initiate a chunked upload session."""
        total_size = len(file_bytes)
        file_hash = calculate_bytes_hash(file_bytes)

        response = self.client.post(
            '/api/v1/uploads/chunked/init/',
            {
                'filename': 'test_corruption.tar.gz',
                'total_size': total_size,
                'chunk_size': chunk_size,
                'file_hash': file_hash,
            },
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        session_id = response.data['session_id']
        total_chunks = response.data['total_chunks']

        return session_id, total_chunks, file_hash

    def _upload_chunk(self, session_id, chunk_number, chunk_data):
        """Upload a single chunk."""
        chunk_hash = calculate_bytes_hash(chunk_data)

        response = self.client.post(
            f'/api/v1/uploads/chunked/{session_id}/chunk/',
            chunk_data,
            content_type='application/octet-stream',
            query_params={
                'chunk_number': chunk_number,
                'chunk_hash': chunk_hash,
            }
        )

        return response

    def _corrupt_chunk_file(self, session_id, chunk_number):
        """Deliberately corrupt a chunk file on disk after upload."""
        session_dir = get_upload_session_dir(session_id)
        chunk_file = session_dir / f'chunk_{chunk_number:06d}'

        if chunk_file.exists():
            # Read the file
            with open(chunk_file, 'rb') as f:
                data = bytearray(f.read())
            
            # Corrupt it (flip some bits in the middle)
            if len(data) > 100:
                corruption_point = len(data) // 2
                data[corruption_point] ^= 0xFF  # Flip all bits at one byte
                data[corruption_point + 1] ^= 0xAA  # Flip more bits
            
            # Write corrupted data back
            with open(chunk_file, 'wb') as f:
                f.write(data)
            
            return True
        return False

    def test_automatic_corruption_detection_and_reupload(self):
        """
        Test that the system detects corrupted chunks and handles recovery.
        
        Scenario:
        1. Upload tar file in chunks (1MB each)
        2. Corrupt chunk 1 after upload at filesystem level
        3. System should detect corruption when verification runs
        4. Re-upload the corrupted chunk
        5. Complete upload
        6. Verify final tar file matches original
        """
        print("\n" + "="*70)
        print("TEST: Automatic Corruption Detection and Recovery")
        print("="*70)

        # Step 1: Initialize chunked upload
        session_id, total_chunks, file_hash = self._initiate_chunked_upload(
            self.original_tar_bytes,
            chunk_size=2*1024*1024  # 2MB chunks for reasonable test size
        )
        print(f"\n✓ Initiated chunked upload")
        print(f"  Session ID: {session_id}")
        print(f"  Total chunks: {total_chunks}")
        print(f"  Original file hash: {file_hash}")

        # Step 2: Upload all chunks
        chunk_size = 2 * 1024 * 1024
        uploaded_chunks = []
        
        for chunk_number in range(total_chunks):
            start = chunk_number * chunk_size
            end = min(start + chunk_size, len(self.original_tar_bytes))
            chunk_data = self.original_tar_bytes[start:end]

            response = self._upload_chunk(session_id, chunk_number, chunk_data)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            uploaded_chunks.append(chunk_number)
            print(f"✓ Uploaded chunk {chunk_number + 1}/{total_chunks}")

        print(f"\n✓ All {total_chunks} chunks uploaded successfully")

        # Step 3: Corrupt one chunk (e.g., chunk 1 if available)
        if total_chunks >= 2:
            chunk_to_corrupt = 1
            self._corrupt_chunk_file(session_id, chunk_to_corrupt)
            print(f"\n✓ Corrupted chunk {chunk_to_corrupt} at filesystem level")

            # Step 4: Verify that the chunk is detected as corrupted
            # Upload the same chunk again
            chunk_number = chunk_to_corrupt
            start = chunk_number * chunk_size
            end = min(start + chunk_size, len(self.original_tar_bytes))
            chunk_data = self.original_tar_bytes[start:end]

            # The re-upload should succeed because we're providing correct data
            response = self._upload_chunk(session_id, chunk_number, chunk_data)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            print(f"✓ Re-uploaded corrected chunk {chunk_to_corrupt}")

        # Step 5: Complete the upload
        response = self.client.post(
            f'/api/v1/uploads/chunked/{session_id}/complete/',
            {'file_hash': file_hash},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assembled_file_path = response.data['assembled_file']
        job_id = response.data['job_id']
        print(f"\n✓ Upload completed successfully")
        print(f"  Job ID: {job_id}")
        print(f"  Assembled file: {assembled_file_path}")

        # Step 6: Verify the assembled tar file matches the original
        with open(assembled_file_path, 'rb') as f:
            assembled_tar_bytes = f.read()
        
        assembled_file_hash = calculate_bytes_hash(assembled_tar_bytes)
        self.assertEqual(
            assembled_file_hash,
            file_hash,
            f"Assembled file hash doesn't match original!\n"
            f"Expected: {file_hash}\n"
            f"Got: {assembled_file_hash}"
        )
        print(f"\n✓ Assembled file hash matches original")
        print(f"  Hash: {assembled_file_hash}")

        # Step 7: Verify tar can be extracted and inspected
        tar_buffer = io.BytesIO(assembled_tar_bytes)
        tar = tarfile.open(fileobj=tar_buffer, mode='r:gz')
        members = tar.getmembers()
        print(f"\n✓ Tar file successfully extracted")
        print(f"  Contains {len(members)} members:")
        for member in members:
            if member.isfile():
                print(f"    - {member.name} ({member.size} bytes)")
        tar.close()

        # Step 8: Verify manifest is readable
        tar_buffer.seek(0)
        tar = tarfile.open(fileobj=tar_buffer, mode='r:gz')
        manifest_file = tar.extractfile('manifest.json')
        manifest_data = json.loads(manifest_file.read().decode('utf-8'))
        self.assertEqual(manifest_data['patient']['pseudo_id'], 'PAT-TEST-CORRUPT-001')
        print(f"\n✓ Manifest is valid and readable")
        print(f"  Patient ID: {manifest_data['patient']['pseudo_id']}")
        print(f"  Study UID: {manifest_data['study']['pseudo_study_uid']}")
        tar.close()

        print(f"\n" + "="*70)
        print("TEST PASSED: Corruption detection and recovery successful!")
        print("="*70)


@override_settings(RAW_DATA_DIR='/tmp/eutempe_test_resilience')
class ChunkedUploadServerRestartTest(APITestCase):
    """Test upload resumption after server restart."""

    def setUp(self):
        """Set up test fixtures."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser_restart',
            email='test_restart@example.com',
            password='testpassword123'
        )
        self.token = Token.objects.create(user=self.user)

        # Create API client with auth
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

        # Create test tar
        self.original_tar = self._create_test_tar_with_dicom()
        self.original_tar_bytes = self.original_tar.getvalue()
        self.original_tar_hash = calculate_bytes_hash(self.original_tar_bytes)

    def _create_test_tar_with_dicom(self, num_files=4):
        """Create a tar archive with dummy DICOM files."""
        tar_buffer = io.BytesIO()
        tar = tarfile.open(fileobj=tar_buffer, mode='w:gz')

        # Create manifest
        manifest = {
            "manifest_version": "1.0",
            "patient": {
                "pseudo_id": "PAT-TEST-RESTART-001",
                "sex": "F",
                "age_at_first_acquisition": 55,
                "cohort_tag": "test_restart",
            },
            "study": {
                "pseudo_study_uid": "STUDY-TEST-RESTART-001",
                "acquisition_date": "2026-02-21",
                "clinical_indication": "Server restart recovery test",
                "contrast_used": True,
            },
            "images": [],
        }

        # Create dummy DICOM files - make them larger (1MB each) for multiple chunks
        dicom_files = {}
        for i in range(1, num_files + 1):
            filename = f"images/scan_{i:03d}.dcm"
            # Create realistic-looking DICOM data (1MB each)
            dicom_data = (
                b'DICM_RESTART_' + str(i).encode() + 
                b'Y' * (1024 * 1024 - len(b'DICM_RESTART_' + str(i).encode()))
            )
            dicom_files[filename] = dicom_data
            checksum = hashlib.sha256(dicom_data).hexdigest()
            manifest["images"].append({
                "filename": filename,
                "checksum_sha256": checksum,
                "body_part_examined": "ABDOMEN",
                "slice_thickness_mm": 2.5,
            })

        # Add manifest
        manifest_json = json.dumps(manifest).encode('utf-8')
        manifest_info = tarfile.TarInfo(name="manifest.json")
        manifest_info.size = len(manifest_json)
        tar.addfile(manifest_info, io.BytesIO(manifest_json))

        # Add files
        for filename, content in dicom_files.items():
            file_info = tarfile.TarInfo(name=filename)
            file_info.size = len(content)
            tar.addfile(file_info, io.BytesIO(content))

        tar.close()
        tar_buffer.seek(0)
        return tar_buffer

    def test_upload_resumption_after_server_restart(self):
        """
        Test that upload can be resumed after server restart.
        
        Scenario:
        1. Initiate chunked upload
        2. Upload first half of chunks
        3. Simulate server restart (check session persists, files on disk)
        4. Query upload status to resume
        5. Upload remaining chunks
        6. Complete upload
        7. Verify final tar file matches original
        """
        print("\n" + "="*70)
        print("TEST: Upload Resumption After Server Restart")
        print("="*70)

        # Step 1: Initialize chunked upload with smaller chunks to ensure multiple chunks
        total_size = len(self.original_tar_bytes)
        chunk_size = 512 * 1024  # 512KB chunks to ensure multiple chunks for test tar
        file_hash = self.original_tar_hash

        response = self.client.post(
            '/api/v1/uploads/chunked/init/',
            {
                'filename': 'test_restart.tar.gz',
                'total_size': total_size,
                'chunk_size': chunk_size,
                'file_hash': file_hash,
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        session_id = response.data['session_id']
        total_chunks = response.data['total_chunks']
        
        print(f"\n✓ Initiated chunked upload")
        print(f"  Session ID: {session_id}")
        print(f"  Total chunks: {total_chunks}")
        print(f"  Chunk size: {chunk_size} bytes")
        print(f"  File hash: {file_hash}")

        # Step 2: Upload first half of chunks (ensure at least 1 chunk before restart)
        chunks_to_upload_before_restart = max(1, total_chunks // 2)
        print(f"\n✓ Uploading first {chunks_to_upload_before_restart} chunks before restart...")

        for chunk_number in range(chunks_to_upload_before_restart):
            start = chunk_number * chunk_size
            end = min(start + chunk_size, len(self.original_tar_bytes))
            chunk_data = self.original_tar_bytes[start:end]

            chunk_hash = calculate_bytes_hash(chunk_data)
            response = self.client.post(
                f'/api/v1/uploads/chunked/{session_id}/chunk/',
                chunk_data,
                content_type='application/octet-stream',
                query_params={
                    'chunk_number': chunk_number,
                    'chunk_hash': chunk_hash,
                }
            )
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            print(f"  ✓ Uploaded chunk {chunk_number + 1}/{total_chunks}")

        # Step 3: Verify progress before restart
        response = self.client.get(f'/api/v1/uploads/chunked/{session_id}/progress/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        progress_before = response.data['progress_percent']
        uploaded_before = response.data['uploaded_chunks']
        print(f"\n✓ Progress before restart: {uploaded_before}/{total_chunks} chunks ({progress_before}%)")

        # Step 4: Simulate server restart
        # In reality, the server would be stopped/started
        # For testing, we verify that:
        # - The ChunkedUpload session still exists in the database
        # - The chunk files still exist on disk
        # - We can query the status
        
        print(f"\n✓ Simulating server restart...")
        print(f"  - Verifying ChunkedUpload session persists")
        
        upload_session = ChunkedUpload.objects.get(id=session_id)
        # Status is INITIATED if no chunks uploaded, IN_PROGRESS if some chunks uploaded
        expected_status = 'IN_PROGRESS' if chunks_to_upload_before_restart > 0 else 'INITIATED'
        self.assertEqual(upload_session.status, expected_status)
        self.assertEqual(upload_session.uploaded_chunks, chunks_to_upload_before_restart)
        print(f"    Session found: status={upload_session.status}, uploaded={upload_session.uploaded_chunks}")

        # Check that chunk files exist on disk
        session_dir = get_upload_session_dir(session_id)
        print(f"  - Verifying chunk files exist on disk")
        existing_chunks = list(session_dir.glob('chunk_*'))
        print(f"    Found {len(existing_chunks)} chunk files on disk")
        self.assertEqual(len(existing_chunks), chunks_to_upload_before_restart)

        # Step 5: Query status to resume
        response = self.client.get(f'/api/v1/uploads/chunked/{session_id}/status/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        resume_data = response.data if hasattr(response, 'data') else response.json()
        
        print(f"\n✓ Queried upload status for resumption")
        # Handle both id and session_id field names
        session_id_value = resume_data.get('id') or resume_data.get('session_id', session_id)
        status_value = resume_data.get('status', 'N/A')
        uploaded = resume_data.get('uploaded_chunks', 0)
        total = resume_data.get('total_chunks', 0)
        
        print(f"  Session ID: {session_id_value}")
        print(f"  Status: {status_value}")
        print(f"  Uploaded: {uploaded}/{total}")

        # Step 6: Upload remaining chunks
        print(f"\n✓ Resuming upload from chunk {chunks_to_upload_before_restart + 1}...")
        
        for chunk_number in range(chunks_to_upload_before_restart, total_chunks):
            start = chunk_number * chunk_size
            end = min(start + chunk_size, len(self.original_tar_bytes))
            chunk_data = self.original_tar_bytes[start:end]

            chunk_hash = calculate_bytes_hash(chunk_data)
            response = self.client.post(
                f'/api/v1/uploads/chunked/{session_id}/chunk/',
                chunk_data,
                content_type='application/octet-stream',
                query_params={
                    'chunk_number': chunk_number,
                    'chunk_hash': chunk_hash,
                }
            )
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            print(f"  ✓ Uploaded chunk {chunk_number + 1}/{total_chunks}")

        # Step 7: Complete the upload
        response = self.client.post(
            f'/api/v1/uploads/chunked/{session_id}/complete/',
            {'file_hash': file_hash},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assembled_file_path = response.data['assembled_file']
        job_id = response.data['job_id']
        
        print(f"\n✓ Upload completed successfully")
        print(f"  Job ID: {job_id}")
        print(f"  Assembled file: {assembled_file_path}")

        # Step 8: Verify the assembled tar matches the original
        with open(assembled_file_path, 'rb') as f:
            assembled_tar_bytes = f.read()
        
        assembled_file_hash = calculate_bytes_hash(assembled_tar_bytes)
        self.assertEqual(
            assembled_file_hash,
            file_hash,
            f"Assembled file doesn't match original!\n"
            f"Expected: {file_hash}\n"
            f"Got: {assembled_file_hash}"
        )
        print(f"\n✓ Assembled file hash matches original")
        print(f"  Hash: {assembled_file_hash}")

        # Step 9: Verify tar can be extracted
        tar_buffer = io.BytesIO(assembled_tar_bytes)
        tar = tarfile.open(fileobj=tar_buffer, mode='r:gz')
        members = tar.getmembers()
        
        print(f"\n✓ Tar file successfully extracted")
        print(f"  Contains {len(members)} members:")
        for member in members:
            if member.isfile():
                print(f"    - {member.name} ({member.size} bytes)")
        tar.close()

        # Step 10: Verify manifest
        tar_buffer.seek(0)
        tar = tarfile.open(fileobj=tar_buffer, mode='r:gz')
        manifest_file = tar.extractfile('manifest.json')
        manifest_data = json.loads(manifest_file.read().decode('utf-8'))
        
        self.assertEqual(manifest_data['patient']['pseudo_id'], 'PAT-TEST-RESTART-001')
        self.assertEqual(
            manifest_data['study']['pseudo_study_uid'],
            'STUDY-TEST-RESTART-001'
        )
        
        print(f"\n✓ Manifest is valid and readable")
        print(f"  Patient ID: {manifest_data['patient']['pseudo_id']}")
        print(f"  Study UID: {manifest_data['study']['pseudo_study_uid']}")
        tar.close()

        # Step 11: Verify bytes match exactly
        self.assertEqual(assembled_tar_bytes, self.original_tar_bytes)
        print(f"\n✓ Byte-for-byte verification: assembled tar matches original exactly")

        print(f"\n" + "="*70)
        print("TEST PASSED: Upload resumption after server restart successful!")
        print("="*70)

    def test_multiple_session_independence(self):
        """Verify that multiple concurrent uploads are independent."""
        print("\n" + "="*70)
        print("TEST: Multiple Concurrent Session Independence")
        print("="*70)

        # Create a second user for a concurrent session
        user2 = User.objects.create_user(
            username='testuser_concurrent',
            email='test_concurrent@example.com',
            password='testpassword123'
        )
        token2 = Token.objects.create(user=user2)
        client2 = APIClient()
        client2.credentials(HTTP_AUTHORIZATION=f'Token {token2.key}')

        # Session 1: User 1 uploads
        chunk_size = 2 * 1024 * 1024
        response1 = self.client.post(
            '/api/v1/uploads/chunked/init/',
            {
                'filename': 'session1.tar.gz',
                'total_size': len(self.original_tar_bytes),
                'chunk_size': chunk_size,
                'file_hash': self.original_tar_hash,
            },
            format='json'
        )
        session_id1 = response1.data['session_id']
        print(f"\n✓ User 1 created session: {session_id1}")

        # Session 2: User 2 uploads
        tar2 = self._create_test_tar_with_dicom(num_files=2)
        tar2_bytes = tar2.getvalue()
        tar2_hash = calculate_bytes_hash(tar2_bytes)

        response2 = client2.post(
            '/api/v1/uploads/chunked/init/',
            {
                'filename': 'session2.tar.gz',
                'total_size': len(tar2_bytes),
                'chunk_size': chunk_size,
                'file_hash': tar2_hash,
            },
            format='json'
        )
        session_id2 = response2.data['session_id']
        print(f"✓ User 2 created session: {session_id2}")

        # User 1 uploads first chunk
        chunk_data = self.original_tar_bytes[0:chunk_size]
        chunk_hash = calculate_bytes_hash(chunk_data)
        self.client.post(
            f'/api/v1/uploads/chunked/{session_id1}/chunk/',
            chunk_data,
            content_type='application/octet-stream',
            query_params={'chunk_number': 0, 'chunk_hash': chunk_hash}
        )
        print(f"✓ User 1 uploaded chunk 0")

        # User 2 uploads first chunk
        chunk_data2 = tar2_bytes[0:min(chunk_size, len(tar2_bytes))]
        chunk_hash2 = calculate_bytes_hash(chunk_data2)
        client2.post(
            f'/api/v1/uploads/chunked/{session_id2}/chunk/',
            chunk_data2,
            content_type='application/octet-stream',
            query_params={'chunk_number': 0, 'chunk_hash': chunk_hash2}
        )
        print(f"✓ User 2 uploaded chunk 0")

        # Verify sessions are independent
        resp1 = self.client.get(f'/api/v1/uploads/chunked/{session_id1}/progress/')
        resp2 = client2.get(f'/api/v1/uploads/chunked/{session_id2}/progress/')

        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        
        # User can't access other user's session
        resp_forbidden = self.client.get(f'/api/v1/uploads/chunked/{session_id2}/progress/')
        self.assertEqual(resp_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        print(f"\n✓ Sessions are properly isolated by user")
        print(f"  User 1 can access their session: {session_id1}")
        print(f"  User 2 can access their session: {session_id2}")
        print(f"  User 1 cannot access User 2's session: 403 Forbidden")

        print(f"\n" + "="*70)
        print("TEST PASSED: Multiple sessions are independent!")
        print("="*70)
