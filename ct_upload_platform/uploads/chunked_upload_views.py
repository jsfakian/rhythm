"""
Views for chunked upload endpoints.
Handles resumable uploads for large files.
"""

import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from rest_framework import status, views
from rest_framework.parsers import BaseParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .chunk_manager import (
    get_upload_session_dir,
    store_chunk,
    verify_chunk_integrity,
    assemble_chunks,
    cleanup_session,
    get_upload_progress,
    calculate_file_hash,
)
from .models import ChunkedUpload, UploadChunk
from .serializers import (
    ChunkedUploadSerializer,
    ChunkedUploadInitSerializer,
    ChunkedUploadCompleteSerializer,
)
from .auth import check_upload_ownership, check_upload_access
from .tasks import process_upload_job
from .file_manager import get_raw_data_user_dir

# Configure logging
logger = logging.getLogger(__name__)


class RawBinaryParser(BaseParser):
    """
    Accepts a request body of any content type as opaque raw bytes.

    ChunkedUploadChunkView reads the chunk payload as a raw byte stream
    (clients may send it as application/octet-stream, application/zip, or
    with no Content-Type at all — the actual archive's MIME type, not a
    DRF-parseable one). Without a registered parser for that content type,
    DRF's content negotiation itself raises UnsupportedMediaType (415)
    before the view ever runs. Just as importantly: under
    SessionAuthentication, Django's CSRF check (`_check_token`) calls
    `request.POST` first, which — via DRF's Request wrapper — triggers the
    *default* parsers (JSON/form/multipart) for their content types. Those
    parsers consume the underlying stream, so the view's later
    `request.body`/`request.data` access then raises RawPostDataException
    (500). Registering this catch-all parser makes that same `request.POST`
    probe resolve harmlessly (raw bytes aren't form data, so it's empty)
    without consuming the stream in a way DRF can't safely re-serve, and
    gives the view a consistent, cached `request.data` to read regardless
    of which authentication class handled the request.
    """
    media_type = '*/*'

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read()


def _resolve_upload(session_id: str, request, owner_or_staff: bool = False):
    """
    Fetch a ChunkedUpload by session_id and verify the caller's permission.

    Returns (upload, None) on success or (None, error_Response) on failure.
    Pass owner_or_staff=True to allow staff users to access any upload.
    """
    try:
        upload = ChunkedUpload.objects.get(id=session_id)
    except ChunkedUpload.DoesNotExist:
        return None, Response(
            {'error': 'Upload session not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    checker = check_upload_access if owner_or_staff else check_upload_ownership
    err = checker(request, upload.uploader_id)
    if err:
        return None, err
    return upload, None


class ChunkedUploadInitView(views.APIView):
    """Initialize a chunked upload session."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Initialize a chunked upload.

        Expected JSON:
        {
            "filename": "archive.tar.gz",
            "total_size": 68719476736,  # 64GB
            "chunk_size": 10485760,      # 10MB (optional, default 10MB)
            "file_hash": "sha256_hex"    # (optional for verification)
        }

        Returns:
        {
            "session_id": "uuid",
            "filename": "archive.tar.gz",
            "total_size": 68719476736,
            "total_chunks": 6872,
            "chunk_size": 10485760,
            "expires_at": "2024-03-10T10:00:00Z"
        }
        """
        serializer = ChunkedUploadInitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': serializer.errors, 'code': 'validation_error'},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data
        filename = data['filename']
        total_size = data['total_size']
        chunk_size = data.get('chunk_size', 10485760)
        file_hash = data.get('file_hash', '')
        batch = data.get('batch', '')
        manifest_item = data.get('manifest_item')

        uploader_id = request.user.username

        # Calculate total chunks
        import math
        total_chunks = math.ceil(total_size / chunk_size)

        # Validate total size
        max_size_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if total_size > max_size_bytes:
            # For chunked uploads, allow larger files
            # Use a higher limit like 1TB for chunked uploads
            max_chunked_size = 1024 * 1024 * 1024 * 1024  # 1TB
            if total_size > max_chunked_size:
                return Response(
                    {
                        'error': f'File size exceeds maximum 1TB',
                        'code': 'file_too_large'
                    },
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                )

        try:
            # Create ChunkedUpload session
            expires_at = timezone.now() + timedelta(days=7)

            upload = ChunkedUpload.objects.create(
                uploader_id=uploader_id,
                filename=filename,
                total_size=total_size,
                total_chunks=total_chunks,
                chunk_size=chunk_size,
                file_hash=file_hash if file_hash else None,
                temp_dir=str(get_upload_session_dir(None)),  # Will be set below
                expires_at=expires_at,
                batch=batch,
                manifest_item=manifest_item,
            )

            # Update temp_dir with actual session UUID
            session_dir = get_upload_session_dir(upload.id)
            upload.temp_dir = str(session_dir)
            upload.save()

            return Response(
                {
                    'session_id': str(upload.id),
                    'filename': upload.filename,
                    'total_size': upload.total_size,
                    'total_chunks': upload.total_chunks,
                    'chunk_size': upload.chunk_size,
                    'expires_at': upload.expires_at.isoformat(),
                },
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.error(f'Failed to initialize chunked upload: {e}')
            return Response(
                {'error': str(e), 'code': 'initialization_failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ChunkedUploadChunkView(views.APIView):
    """Upload a single chunk of a chunked upload."""
    permission_classes = [IsAuthenticated]
    parser_classes = [RawBinaryParser]

    def post(self, request, session_id):
        """
        Upload a chunk.

        Query params:
        - chunk_number: Sequential chunk number (0-based)
        - chunk_hash: SHA256 hash of chunk for verification

        Body: Raw chunk data (binary file)

        Returns:
        {
            "chunk_number": 0,
            "chunk_size": 10485760,
            "uploaded_chunks": 1,
            "progress_percent": 1,
            "status": "IN_PROGRESS"
        }
        """
        session_id = str(session_id)
        chunk_number = request.query_params.get('chunk_number')
        chunk_hash = request.query_params.get('chunk_hash')

        if chunk_number is None:
            return Response(
                {'error': 'chunk_number query param is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            chunk_number = int(chunk_number)
        except ValueError:
            return Response(
                {'error': 'chunk_number must be an integer'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not chunk_hash:
            return Response(
                {'error': 'chunk_hash query param is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        upload, err = _resolve_upload(session_id, request)
        if err:
            return err

        # Check session status
        if upload.status not in ['INITIATED', 'IN_PROGRESS']:
            return Response(
                {'error': f'Cannot upload chunks to {upload.status} session'},
                status=status.HTTP_409_CONFLICT
            )

        # Validate chunk number
        if chunk_number < 0 or chunk_number >= upload.total_chunks:
            return Response(
                {'error': f'Invalid chunk_number {chunk_number}. Must be 0 to {upload.total_chunks - 1}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get chunk data from request. request.data (not request.body) — see
        # RawBinaryParser's docstring for why the raw Django body property is
        # unsafe here under SessionAuthentication.
        chunk_data = request.data
        if not chunk_data:
            return Response(
                {'error': 'No chunk data provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Store the chunk
            chunk_path, calculated_hash, calculated_crc32, chunk_size = store_chunk(
                upload.id,
                chunk_number,
                chunk_data
            )

            # Verify hash (this is a client-provided hash for immediate validation)
            if calculated_hash != chunk_hash:
                logger.warning(
                    f'Chunk hash mismatch for session {upload.id} chunk {chunk_number}: '
                    f'expected {chunk_hash}, got {calculated_hash}'
                )
                return Response(
                    {
                        'error': 'Chunk hash verification failed',
                        'code': 'hash_mismatch',
                        'expected': chunk_hash,
                        'actual': calculated_hash,
                    },
                    status=status.HTTP_409_CONFLICT
                )

            # Create or update UploadChunk record with VERIFIED status initially
            # Note: verification_status will be updated if automatic verification detects corruption
            chunk_obj, created = UploadChunk.objects.update_or_create(
                chunked_upload=upload,
                chunk_number=chunk_number,
                defaults={
                    'chunk_size': chunk_size,
                    'chunk_hash': chunk_hash,
                    'chunk_crc32': calculated_crc32,
                    'file_path': chunk_path,
                    'verified': True,
                    'verification_status': UploadChunk.VERIFICATION_VERIFIED,
                    'verification_timestamp': timezone.now(),
                }
            )

            # Perform automatic verification (SHA256 + CRC32) during upload
            # This detects corruption early without requiring separate API calls
            verification_result = self._auto_verify_chunk(chunk_obj)
            
            # Update chunk based on verification result
            if not verification_result['success']:
                chunk_obj.verification_status = UploadChunk.VERIFICATION_CORRUPTED
                chunk_obj.verification_error = verification_result['error']
                chunk_obj.verified = False
                chunk_obj.save()

            # Update upload stats
            upload.status = 'IN_PROGRESS'
            uploaded_count = UploadChunk.objects.filter(chunked_upload=upload).count()
            upload.uploaded_chunks = uploaded_count
            upload.updated_at = timezone.now()
            upload.save()

            return Response(
                {
                    'session_id': str(upload.id),
                    'chunk_number': chunk_number,
                    'chunk_size': chunk_size,
                    'uploaded_chunks': upload.uploaded_chunks,
                    'total_chunks': upload.total_chunks,
                    'progress_percent': upload.progress_percent,
                    'status': upload.status,
                    # Automatic verification results
                    'verification_status': chunk_obj.verification_status,
                    'verification_success': verification_result['success'],
                    'verification_error': verification_result.get('error'),
                    # Resume information: tell client if they need to reupload this chunk
                    'needs_reupload': not verification_result['success'],
                    # Summary of good/bad chunks for resumption planning
                    'verified_chunks': UploadChunk.objects.filter(
                        chunked_upload=upload,
                        verification_status=UploadChunk.VERIFICATION_VERIFIED
                    ).count(),
                    'corrupted_chunks': UploadChunk.objects.filter(
                        chunked_upload=upload,
                        verification_status=UploadChunk.VERIFICATION_CORRUPTED
                    ).count(),
                },
                status=status.HTTP_202_ACCEPTED
            )

        except Exception as e:
            logger.error(f'Failed to store chunk {chunk_number} for session {upload.id}: {e}')
            return Response(
                {'error': str(e), 'code': 'chunk_storage_failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _auto_verify_chunk(self, chunk_obj):
        """
        Automatically verify a chunk using SHA256 and CRC32.
        
        Returns:
            dict: {
                'success': bool,
                'sha256_match': bool,
                'crc32_match': bool,
                'error': str (if failed)
            }
        """
        from .chunk_manager import calculate_file_hash, calculate_file_crc32
        
        try:
            chunk_path = chunk_obj.file_path
            
            # 1. Verify SHA256
            actual_sha256 = calculate_file_hash(chunk_path)
            sha256_match = actual_sha256 == chunk_obj.chunk_hash
            
            if not sha256_match:
                error = f'SHA256 mismatch: expected {chunk_obj.chunk_hash}, got {actual_sha256}'
                logger.warning(f'Chunk {chunk_obj.chunk_number} SHA256 verification failed: {error}')
                return {
                    'success': False,
                    'sha256_match': False,
                    'crc32_match': None,
                    'error': error
                }
            
            # 2. Verify CRC32 (quick check)
            if chunk_obj.chunk_crc32:
                actual_crc32 = calculate_file_crc32(chunk_path)
                crc32_match = actual_crc32 == chunk_obj.chunk_crc32.lower()
                
                if not crc32_match:
                    error = f'CRC32 mismatch: expected {chunk_obj.chunk_crc32}, got {actual_crc32}'
                    logger.warning(f'Chunk {chunk_obj.chunk_number} CRC32 verification failed: {error}')
                    return {
                        'success': False,
                        'sha256_match': True,
                        'crc32_match': False,
                        'error': error
                    }
            else:
                crc32_match = True  # CRC32 is optional
            
            # Both hashes match
            logger.info(f'Chunk {chunk_obj.chunk_number} verified successfully (SHA256 + CRC32)')
            return {
                'success': True,
                'sha256_match': True,
                'crc32_match': crc32_match,
                'error': None
            }
            
        except Exception as e:
            error = f'Verification error: {str(e)}'
            logger.error(f'Failed to verify chunk {chunk_obj.chunk_number}: {error}')
            return {
                'success': False,
                'sha256_match': None,
                'crc32_match': None,
                'error': error
            }


class ChunkedUploadCompleteView(views.APIView):
    """Complete a chunked upload and assemble chunks."""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        """
        Complete a chunked upload.

        Expected JSON:
        {
            "file_hash": "sha256_of_complete_file"
        }

        Returns:
        {
            "session_id": "uuid",
            "status": "COMPLETED",
            "filename": "archive.tar.gz",
            "total_size": 68719476736,
            "assembled_file": "/path/to/assembled/file.tar.gz",
            "file_hash": "sha256_hex"
        }
        """
        session_id = str(session_id)

        upload, err = _resolve_upload(session_id, request)
        if err:
            return err

        # Validate request
        serializer = ChunkedUploadCompleteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': serializer.errors, 'code': 'validation_error'},
                status=status.HTTP_400_BAD_REQUEST
            )

        provided_hash = serializer.validated_data['file_hash']

        # Check that all chunks have been uploaded
        if upload.uploaded_chunks < upload.total_chunks:
            return Response(
                {
                    'error': f'Not all chunks uploaded. Got {upload.uploaded_chunks}/{upload.total_chunks}',
                    'uploaded_chunks': upload.uploaded_chunks,
                    'total_chunks': upload.total_chunks,
                    'code': 'incomplete_upload'
                },
                status=status.HTTP_409_CONFLICT
            )

        try:
            # Assemble chunks into final file
            raw_data_dir = get_raw_data_user_dir(upload.uploader_id)
            output_filename = f'{upload.id}.tar'
            output_path = raw_data_dir / output_filename

            success, message, assembled_hash = assemble_chunks(
                upload.id,
                str(output_path),
                upload.total_chunks
            )

            if not success:
                logger.error(f'Failed to assemble chunks for session {upload.id}: {message}')
                return Response(
                    {'error': message, 'code': 'assembly_failed'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Verify assembled file hash
            if provided_hash != assembled_hash:
                logger.warning(
                    f'Assembled file hash mismatch for session {upload.id}: '
                    f'expected {provided_hash}, got {assembled_hash}'
                )
                return Response(
                    {
                        'error': 'Assembled file hash verification failed',
                        'code': 'file_hash_mismatch',
                        'expected': provided_hash,
                        'actual': assembled_hash,
                    },
                    status=status.HTTP_409_CONFLICT
                )

            # Clean up chunk files (but keep directory)
            cleanup_session(upload.id, remove_all=False)

            # Update upload session
            upload.status = 'COMPLETED'
            upload.file_hash = assembled_hash
            upload.completed_at = timezone.now()
            upload.save()

            # Create UploadJob from assembled file
            job = ChunkedUpload._create_upload_job_from_chunked_upload(
                upload,
                str(output_path)
            )

            logger.info(
                f'Chunked upload {upload.id} completed and assembled. '
                f'Created UploadJob {job.id}'
            )

            return Response(
                {
                    'session_id': str(upload.id),
                    'status': upload.status,
                    'filename': upload.filename,
                    'total_size': upload.total_size,
                    'assembled_file': str(output_path),
                    'file_hash': assembled_hash,
                    'job_id': str(job.id),
                    'job_status_url': f'/api/v1/uploads/{job.id}/',
                    'completed_at': upload.completed_at.isoformat(),
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f'Failed to complete chunked upload {upload.id}: {e}')
            return Response(
                {'error': str(e), 'code': 'completion_failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ChunkedUploadProgressView(views.APIView):
    """Get progress of a chunked upload."""
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        """
        Get chunked upload progress.

        Returns:
        {
            "session_id": "uuid",
            "filename": "archive.tar.gz",
            "status": "IN_PROGRESS",
            "total_size": 68719476736,
            "total_chunks": 6872,
            "uploaded_chunks": 3436,
            "progress_percent": 50,
            "is_complete": false,
            "created_at": "2024-02-26T10:00:00Z",
            "updated_at": "2024-02-26T10:15:00Z"
        }
        """
        session_id = str(session_id)

        upload, err = _resolve_upload(session_id, request, owner_or_staff=True)
        if err:
            return err

        serializer = ChunkedUploadSerializer(upload)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ChunkedUploadCancelView(views.APIView):
    """Cancel a chunked upload and clean up resources."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, session_id):
        """
        Cancel a chunked upload.

        Removes all chunk files and marks session as CANCELLED.

        Returns 204 No Content on success.
        """
        session_id = str(session_id)

        upload, err = _resolve_upload(session_id, request, owner_or_staff=True)
        if err:
            return err

        # Only allow cancelling non-completed uploads
        if upload.status == 'COMPLETED':
            return Response(
                {'error': 'Cannot cancel a completed upload'},
                status=status.HTTP_409_CONFLICT
            )

        try:
            # Clean up all session files
            cleanup_session(upload.id, remove_all=True)

            # Mark as cancelled
            upload.status = 'CANCELLED'
            upload.save()

            logger.info(f'Chunked upload {upload.id} cancelled by {request.user.username}')

            return Response(status=status.HTTP_204_NO_CONTENT)

        except Exception as e:
            logger.error(f'Failed to cancel chunked upload {upload.id}: {e}')
            return Response(
                {'error': str(e), 'code': 'cancellation_failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ManifestValidationView(views.APIView):
    """
    Validate a manifest.json file BEFORE starting chunked upload.
    
    This endpoint allows clients to validate the manifest as early as possible,
    avoiding the need to upload an entire file only to discover the manifest is invalid.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Validate a manifest.json file.

        Expected JSON:
        {
            "manifest": {
                "manifest_version": "1.0",
                "upload_id": "uuid",
                ...
            }
        }

        Returns:
        {
            "valid": true,
            "errors": []
        }
        
        or if invalid:
        
        {
            "valid": false,
            "errors": [
                {
                    "field": "$.patient.pseudo_id",
                    "code": "pattern",
                    "message": "..."
                },
                ...
            ]
        }
        """
        from .manifest_schema import validate_manifest_auto

        manifest_data = request.data.get('manifest')

        if not manifest_data:
            return Response(
                {
                    'valid': False,
                    'errors': [
                        {
                            'field': '$',
                            'code': 'missing_manifest',
                            'message': 'manifest field is required'
                        }
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate manifest — auto-detects whether this is a v1 (single
        # study/patient/images) or v2 (server-assigned batch/items) manifest
        # and validates against the matching schema.
        schema_version, errors = validate_manifest_auto(manifest_data)

        if errors:
            return Response(
                {
                    'valid': False,
                    'schema_version': schema_version,
                    'errors': errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                'valid': True,
                'schema_version': schema_version,
                'errors': []
            },
            status=status.HTTP_200_OK
        )


class ChunkVerificationView(views.APIView):
    """
    Verify integrity of already-uploaded chunks.
    
    Detects corrupted chunks using SHA256 and CRC32 verification.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        """
        Verify chunks in an upload session.

        Query params (optional):
        - chunk_numbers: Comma-separated list of chunk numbers to verify.
                         If omitted, verifies all chunks.

        Returns:
        {
            "session_id": "uuid",
            "total_checked": 100,
            "passed": 100,
            "failed": 0,
            "is_complete": false,
            "corrupted_chunks": [],
            "verification_status": "success"
        }
        
        or if corruption detected:
        
        {
            "session_id": "uuid",
            "total_checked": 100,
            "passed": 95,
            "failed": 5,
            "is_complete": false,
            "corrupted_chunks": [
                {
                    "chunk_number": 42,
                    "error": "SHA256 mismatch: expected abc..., got def...",
                    "status": "sha256_mismatch"
                },
                ...
            ],
            "verification_status": "corruption_detected",
            "recommend_restart": true
        }
        """
        from .chunk_manager import verify_uploaded_chunks
        
        session_id = str(session_id)
        
        upload, err = _resolve_upload(session_id, request, owner_or_staff=True)
        if err:
            return err

        # Parse optional chunk_numbers parameter
        chunk_numbers = request.query_params.get('chunk_numbers')
        if chunk_numbers:
            try:
                chunk_numbers = [int(x.strip()) for x in chunk_numbers.split(',')]
            except ValueError:
                return Response(
                    {
                        'error': 'Invalid chunk_numbers parameter. Must be comma-separated integers.',
                        'code': 'invalid_parameter'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        try:
            # Verify chunks
            verification_result = verify_uploaded_chunks(session_id, chunk_numbers)
            
            # Determine verification status
            if verification_result['failed'] == 0:
                verification_status = 'success'
                has_corruption = False
            elif verification_result['failed'] > 0:
                verification_status = 'corruption_detected'
                has_corruption = True
            else:
                verification_status = 'unknown'
                has_corruption = False
            
            response_data = {
                'session_id': str(upload.id),
                'filename': upload.filename,
                'total_chunks': upload.total_chunks,
                'uploaded_chunks': upload.uploaded_chunks,
                'total_checked': verification_result['total_checked'],
                'passed': verification_result['passed'],
                'failed': verification_result['failed'],
                'is_complete': upload.is_complete,
                'verification_status': verification_status,
                'corrupted_chunks': verification_result['corrupted_chunks'],
            }
            
            # Add recommendation if corruption detected
            if has_corruption:
                response_data['recommend_restart'] = True
                response_data['message'] = (
                    f'{verification_result["failed"]} corrupted chunk(s) detected. '
                    'Consider restarting the upload to re-upload corrupted chunks.'
                )
            else:
                response_data['recommend_restart'] = False
            
            logger.info(
                f'Chunk verification for session {session_id}: '
                f'{verification_result["passed"]} passed, '
                f'{verification_result["failed"]} failed'
            )
            
            return Response(
                response_data,
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            logger.error(f'Failed to verify chunks for session {session_id}: {e}')
            return Response(
                {'error': str(e), 'code': 'verification_failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UploadProgressView(views.APIView):
    """Get upload progress and status for resuming uploads."""
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        """
        Get detailed upload progress including which chunks are verified/corrupted.
        
        Useful for:
        - Resuming uploads (shows which chunks need to be re-uploaded)
        - Showing progress with details
        - Automatic retry logic (client can know exactly which chunks to retry)
        
        Returns:
        {
            "session_id": "uuid",
            "total_chunks": 100,
            "verified_chunks": 95,
            "corrupted_chunks": 5,
            "pending_chunks": 0,
            "progress_percent": 95,
            "needs_reupload": [0, 5, 12, 25, 80],
            "upload_can_resume": true,
            "chunks_status": [
                {
                    "chunk_number": 0,
                    "status": "VERIFIED"
                },
                {
                    "chunk_number": 5,
                    "status": "CORRUPTED",
                    "error": "CRC32 mismatch: expected abc..., got def..."
                },
                ...
            ]
        }
        """
        session_id = str(session_id)

        upload, err = _resolve_upload(session_id, request)
        if err:
            return err

        # Get chunk statistics
        all_chunks = UploadChunk.objects.filter(chunked_upload=upload).order_by('chunk_number')
        verified_chunks = all_chunks.filter(verification_status=UploadChunk.VERIFICATION_VERIFIED)
        corrupted_chunks = all_chunks.filter(verification_status=UploadChunk.VERIFICATION_CORRUPTED)
        pending_chunks = all_chunks.filter(verification_status=UploadChunk.VERIFICATION_PENDING)
        
        needs_reupload = [c.chunk_number for c in corrupted_chunks]

        # Build detailed chunk status
        chunks_status = []
        for chunk in all_chunks:
            status_info = {
                'chunk_number': chunk.chunk_number,
                'status': chunk.verification_status,
                'uploaded_at': chunk.uploaded_at.isoformat() if chunk.uploaded_at else None,
            }
            if chunk.verification_error:
                status_info['error'] = chunk.verification_error
            if chunk.verification_timestamp:
                status_info['verified_at'] = chunk.verification_timestamp.isoformat()
            chunks_status.append(status_info)

        return Response(
            {
                'session_id': str(upload.id),
                'total_chunks': upload.total_chunks,
                'verified_chunks': verified_chunks.count(),
                'corrupted_chunks': corrupted_chunks.count(),
                'pending_chunks': pending_chunks.count(),
                'progress_percent': upload.progress_percent,
                'upload_status': upload.status,
                'needs_reupload': needs_reupload,
                'upload_can_resume': len(needs_reupload) < upload.total_chunks,  # Can resume if some chunks are good
                'estimated_remaining_uploads': len(needs_reupload),
                'chunks_status': chunks_status,
            },
            status=status.HTTP_200_OK
        )
