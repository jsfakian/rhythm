"""
Utilities for managing chunked uploads.
Handles chunk storage, assembly, verification, and cleanup.
Includes enhanced corruption detection and validation.
"""

import binascii
import hashlib
import logging
import os
import shutil
from datetime import timedelta
from pathlib import Path
from zlib import crc32

from django.conf import settings
from django.utils import timezone

from .models import ChunkedUpload, UploadChunk

logger = logging.getLogger(__name__)


def get_chunks_dir():
    """Get the base directory for storing upload chunks."""
    chunks_dir = Path(settings.RAW_DATA_DIR) / '_chunks'
    chunks_dir.mkdir(parents=True, exist_ok=True)
    return chunks_dir


def get_upload_session_dir(session_id):
    """
    Get the temporary directory for a specific upload session.
    Creates the directory if it doesn't exist.
    
    Args:
        session_id: UUID of the ChunkedUpload session
        
    Returns:
        Path object for the session directory
    """
    session_dir = get_chunks_dir() / str(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def calculate_file_hash(file_path):
    """
    Calculate SHA256 hash of a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Hex digest of SHA256 hash
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for byte_block in iter(lambda: f.read(4096), b''):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def calculate_bytes_hash(data):
    """
    Calculate SHA256 hash of bytes.
    
    Args:
        data: Bytes to hash
        
    Returns:
        Hex digest of SHA256 hash
    """
    return hashlib.sha256(data).hexdigest()


def calculate_bytes_crc32(data):
    """
    Calculate CRC32 checksum of bytes for quick corruption detection.
    
    Args:
        data: Bytes to checksum
        
    Returns:
        CRC32 checksum as hex string (8 chars)
    """
    crc = crc32(data) & 0xffffffff
    return f'{crc:08x}'


def calculate_file_crc32(file_path):
    """
    Calculate CRC32 checksum of a file for quick corruption detection.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Hex digest of CRC32 checksum
    """
    crc = 0
    with open(file_path, 'rb') as f:
        for byte_block in iter(lambda: f.read(8192), b''):
            crc = crc32(byte_block, crc) & 0xffffffff
    return f'{crc:08x}'


def verify_chunk_integrity(file_path, expected_hash):
    """
    Verify a chunk's integrity by computing its hash.
    
    Args:
        file_path: Path to chunk file
        expected_hash: Expected SHA256 hash
        
    Returns:
        True if hash matches, False otherwise
    """
    actual_hash = calculate_file_hash(file_path)
    return actual_hash == expected_hash


def verify_file_integrity(file_path, expected_hash):
    """
    Verify complete file's integrity.
    
    Args:
        file_path: Path to complete file
        expected_hash: Expected SHA256 hash
        
    Returns:
        True if hash matches, False otherwise
    """
    return verify_chunk_integrity(file_path, expected_hash)


def verify_chunk_with_crc32(file_path, expected_crc32):
    """
    Verify chunk integrity using CRC32 (fast check).
    
    Args:
        file_path: Path to chunk file
        expected_crc32: Expected CRC32 checksum (hex string)
        
    Returns:
        True if CRC32 matches, False otherwise
    """
    actual_crc32 = calculate_file_crc32(file_path)
    return actual_crc32 == expected_crc32.lower()


def verify_uploaded_chunks(session_id, chunk_numbers=None):
    """
    Verify integrity of already-uploaded chunks.
    
    Performs both SHA256 and CRC32 verification to detect corruption.
    
    Args:
        session_id: UUID of ChunkedUpload session
        chunk_numbers: List of chunk numbers to verify, or None for all chunks
        
    Returns:
        Dictionary with verification results:
        {
            'total_checked': int,
            'passed': int,
            'failed': int,
            'corrupted_chunks': [
                {
                    'chunk_number': int,
                    'error': str,
                    'status': 'missing'|'sha256_mismatch'|'crc32_mismatch'
                },
                ...
            ]
        }
    """
    session_dir = get_upload_session_dir(session_id)
    
    try:
        upload = ChunkedUpload.objects.get(id=session_id)
    except ChunkedUpload.DoesNotExist:
        return {
            'total_checked': 0,
            'passed': 0,
            'failed': 1,
            'corrupted_chunks': [
                {
                    'chunk_number': None,
                    'error': f'Upload session {session_id} not found',
                    'status': 'session_not_found'
                }
            ]
        }
    
    # Determine which chunks to verify
    if chunk_numbers is None:
        chunk_numbers = range(upload.total_chunks)
    
    results = {
        'total_checked': 0,
        'passed': 0,
        'failed': 0,
        'corrupted_chunks': []
    }
    
    for chunk_num in chunk_numbers:
        chunk_filename = f'chunk_{chunk_num:06d}'
        chunk_path = session_dir / chunk_filename
        
        results['total_checked'] += 1
        
        # 1. Check chunk exists
        if not chunk_path.exists():
            results['failed'] += 1
            results['corrupted_chunks'].append({
                'chunk_number': chunk_num,
                'error': f'Chunk {chunk_num} file not found',
                'status': 'missing'
            })
            continue
        
        # 2. Get expected hashes from database
        try:
            chunk_obj = UploadChunk.objects.get(
                chunked_upload=upload,
                chunk_number=chunk_num
            )
            expected_sha256 = chunk_obj.chunk_hash
            expected_crc32 = getattr(chunk_obj, 'chunk_crc32', None)
        except UploadChunk.DoesNotExist:
            results['failed'] += 1
            results['corrupted_chunks'].append({
                'chunk_number': chunk_num,
                'error': f'Chunk {chunk_num} metadata not found in database',
                'status': 'metadata_missing'
            })
            continue
        
        # 3. Verify SHA256
        if expected_sha256:
            actual_sha256 = calculate_file_hash(str(chunk_path))
            if actual_sha256 != expected_sha256:
                results['failed'] += 1
                results['corrupted_chunks'].append({
                    'chunk_number': chunk_num,
                    'error': f'SHA256 mismatch: expected {expected_sha256}, got {actual_sha256}',
                    'status': 'sha256_mismatch'
                })
                continue
        
        # 4. Verify CRC32 (quick check) if available
        if expected_crc32:
            actual_crc32 = calculate_file_crc32(str(chunk_path))
            if actual_crc32 != expected_crc32.lower():
                results['failed'] += 1
                results['corrupted_chunks'].append({
                    'chunk_number': chunk_num,
                    'error': f'CRC32 mismatch: expected {expected_crc32}, got {actual_crc32}',
                    'status': 'crc32_mismatch'
                })
                continue
        
        results['passed'] += 1
    
    return results


def store_chunk(session_id, chunk_number, chunk_data):
    """
    Store an uploaded chunk to disk.
    
    Args:
        session_id: UUID of ChunkedUpload session
        chunk_number: Sequential chunk number
        chunk_data: Bytes of chunk data
        
    Returns:
        Tuple of (file_path, chunk_hash, chunk_crc32, chunk_size)
        
    Raises:
        IOError: If writing chunk fails
    """
    session_dir = get_upload_session_dir(session_id)
    chunk_filename = f'chunk_{chunk_number:06d}'
    chunk_path = session_dir / chunk_filename
    
    # Write chunk to disk
    with open(chunk_path, 'wb') as f:
        f.write(chunk_data)
    
    # Calculate hashes
    chunk_hash = calculate_bytes_hash(chunk_data)
    chunk_crc32 = calculate_bytes_crc32(chunk_data)
    chunk_size = len(chunk_data)
    
    return str(chunk_path), chunk_hash, chunk_crc32, chunk_size


def assemble_chunks(session_id, output_path, total_chunks):
    """
    Assemble all chunks into a single file.
    Chunks must be numbered sequentially 0 to total_chunks-1.
    
    Args:
        session_id: UUID of ChunkedUpload session
        output_path: Path where assembled file should be written
        total_chunks: Total number of chunks expected
        
    Returns:
        Tuple of (success, message, file_hash)
        
    Raises:
        IOError: If assembly fails
    """
    session_dir = get_upload_session_dir(session_id)
    
    # Ensure output directory exists
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Assemble chunks in order
    sha256_hash = hashlib.sha256()
    bytes_written = 0
    
    try:
        with open(output_path, 'wb') as output_file:
            for chunk_num in range(total_chunks):
                chunk_filename = f'chunk_{chunk_num:06d}'
                chunk_path = session_dir / chunk_filename
                
                if not chunk_path.exists():
                    return False, f'Missing chunk {chunk_num}', None
                
                with open(chunk_path, 'rb') as chunk_file:
                    while True:
                        chunk_data = chunk_file.read(8192)
                        if not chunk_data:
                            break
                        output_file.write(chunk_data)
                        sha256_hash.update(chunk_data)
                        bytes_written += len(chunk_data)
        
        file_hash = sha256_hash.hexdigest()
        return True, f'Assembled {bytes_written} bytes from {total_chunks} chunks', file_hash
        
    except Exception as e:
        # Clean up partial output on error
        if output_path.exists():
            output_path.unlink()
        return False, f'Failed to assemble chunks: {str(e)}', None


def cleanup_session(session_id, remove_all=False):
    """
    Clean up temporary files for a session.
    
    Args:
        session_id: UUID of ChunkedUpload session
        remove_all: If True, remove the entire session directory.
                   If False, only remove chunk files but keep the directory.
    """
    session_dir = get_upload_session_dir(session_id)
    
    if not session_dir.exists():
        return
    
    if remove_all:
        try:
            shutil.rmtree(session_dir)
        except Exception as e:
            # Log but don't fail
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Failed to remove session directory {session_id}: {e}')
    else:
        # Remove chunk files
        for chunk_file in session_dir.glob('chunk_*'):
            try:
                chunk_file.unlink()
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f'Failed to remove chunk file {chunk_file}: {e}')


def cleanup_expired_uploads(days=7):
    """
    Clean up incomplete uploads older than specified days.
    Use in a periodic task (Celery beat).
    
    Args:
        days: Remove uploads not completed in this many days
        
    Returns:
        Number of uploads cleaned up
    """
    cutoff_time = timezone.now() - timedelta(days=days)
    expired_uploads = ChunkedUpload.objects.filter(
        status__in=['INITIATED', 'IN_PROGRESS'],
        updated_at__lt=cutoff_time
    )
    
    cleanup_count = 0
    for upload in expired_uploads:
        try:
            cleanup_session(upload.id, remove_all=True)
            upload.status = 'CANCELLED'
            upload.save()
            cleanup_count += 1
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Failed to clean up expired upload {upload.id}: {e}')
    
    return cleanup_count


def get_upload_progress(session_id):
    """
    Get detailed progress information for an upload session.
    
    Args:
        session_id: UUID of ChunkedUpload session
        
    Returns:
        Dictionary with progress info or None if session not found
    """
    try:
        upload = ChunkedUpload.objects.get(id=session_id)
    except ChunkedUpload.DoesNotExist:
        return None
    
    return {
        'id': str(upload.id),
        'filename': upload.filename,
        'status': upload.status,
        'total_size': upload.total_size,
        'total_chunks': upload.total_chunks,
        'uploaded_chunks': upload.uploaded_chunks,
        'progress_percent': upload.progress_percent,
        'is_complete': upload.is_complete,
        'created_at': upload.created_at.isoformat(),
        'updated_at': upload.updated_at.isoformat(),
        'completed_at': upload.completed_at.isoformat() if upload.completed_at else None,
    }
