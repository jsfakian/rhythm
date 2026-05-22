#!/usr/bin/env python3
"""
Chunked Upload Client Utility

A command-line tool for uploading large files using the chunked upload API.
Supports resumable uploads and automatic retry on failure.

Usage:
    python chunked_upload_client.py upload <file> <server_url> <token>
    python chunked_upload_client.py resume <session_id> <file> <server_url> <token>
    python chunked_upload_client.py progress <session_id> <server_url> <token>
    python chunked_upload_client.py cancel <session_id> <server_url> <token>
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests
from tqdm import tqdm


class ChunkedUploadException(Exception):
    """Base exception for chunked upload operations."""
    pass


class ChunkedUploadClient:
    """Client for uploading files in chunks."""

    def __init__(
        self,
        base_url: str,
        token: str,
        chunk_size: int = 10485760,  # 10MB default
        max_retries: int = 3,
    ):
        """
        Initialize the client.

        Args:
            base_url: Base URL of the API server (e.g., http://localhost:8000)
            token: Authentication token (Bearer token)
            chunk_size: Size of each chunk in bytes (default 10MB)
            max_retries: Maximum number of retries for failed chunks
        """
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.chunk_size = chunk_size
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({'Authorization': f'Bearer {token}'})

    def _calculate_hash(
        self,
        file_path: str,
        chunk_start: int = 0,
        chunk_end: Optional[int] = None,
    ) -> str:
        """Calculate SHA256 hash of file or chunk."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            f.seek(chunk_start)
            if chunk_end is None:
                while True:
                    data = f.read(8192)
                    if not data:
                        break
                    sha256.update(data)
            else:
                remaining = chunk_end - chunk_start
                while remaining > 0:
                    data = f.read(min(8192, remaining))
                    if not data:
                        break
                    sha256.update(data)
                    remaining -= len(data)
        return sha256.hexdigest()

    def init_upload(
        self,
        filename: str,
        total_size: int,
        file_hash: Optional[str] = None,
    ) -> dict:
        """
        Initialize a chunked upload session.

        Args:
            filename: Name of the file
            total_size: Total file size in bytes
            file_hash: Optional file hash for verification

        Returns:
            Session info dict with session_id and other details
        """
        data = {
            'filename': filename,
            'total_size': total_size,
            'chunk_size': self.chunk_size,
        }
        if file_hash:
            data['file_hash'] = file_hash

        response = self.session.post(
            f'{self.base_url}/api/v1/uploads/chunked/init/',
            json=data,
        )

        if response.status_code != 201:
            raise ChunkedUploadException(
                f'Failed to initialize upload: {response.status_code} '
                f'{response.text}'
            )

        return response.json()

    def upload_chunk(
        self,
        session_id: str,
        chunk_number: int,
        chunk_data: bytes,
    ) -> dict:
        """
        Upload a single chunk with retry logic.

        Args:
            session_id: Upload session ID
            chunk_number: Sequential chunk number
            chunk_data: Chunk data bytes

        Returns:
            Response dict with progress info
        """
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()

        for attempt in range(self.max_retries):
            try:
                response = self.session.post(
                    f'{self.base_url}/api/v1/uploads/chunked/{session_id}/chunk/',
                    params={
                        'chunk_number': chunk_number,
                        'chunk_hash': chunk_hash,
                    },
                    data=chunk_data,
                    timeout=300,  # 5 minute timeout
                )

                if response.status_code in [201, 202]:
                    return response.json()
                elif response.status_code == 409:
                    # Hash mismatch or conflict
                    raise ChunkedUploadException(
                        f'Chunk {chunk_number} validation failed: '
                        f'{response.json().get("error")}'
                    )
                else:
                    raise ChunkedUploadException(
                        f'Upload failed with status {response.status_code}: '
                        f'{response.text}'
                    )

            except (requests.RequestException, ChunkedUploadException) as e:
                if attempt < self.max_retries - 1:
                    print(f'  Retry {attempt + 1}/{self.max_retries} for chunk {chunk_number}')
                    continue
                raise ChunkedUploadException(
                    f'Failed to upload chunk {chunk_number} after {self.max_retries} '
                    f'attempts: {str(e)}'
                )

    def get_progress(self, session_id: str) -> dict:
        """
        Get upload progress.

        Args:
            session_id: Upload session ID

        Returns:
            Progress info dict
        """
        response = self.session.get(
            f'{self.base_url}/api/v1/uploads/chunked/{session_id}/progress/'
        )

        if response.status_code != 200:
            raise ChunkedUploadException(
                f'Failed to get progress: {response.status_code} {response.text}'
            )

        return response.json()

    def complete_upload(self, session_id: str, file_hash: str) -> dict:
        """
        Complete the upload and assemble chunks.

        Args:
            session_id: Upload session ID
            file_hash: SHA256 hash of the complete file

        Returns:
            Completion info dict with job_id
        """
        response = self.session.post(
            f'{self.base_url}/api/v1/uploads/chunked/{session_id}/complete/',
            json={'file_hash': file_hash},
        )

        if response.status_code != 200:
            raise ChunkedUploadException(
                f'Failed to complete upload: {response.status_code} '
                f'{response.text}'
            )

        return response.json()

    def cancel_upload(self, session_id: str) -> None:
        """
        Cancel an upload session.

        Args:
            session_id: Upload session ID
        """
        response = self.session.delete(
            f'{self.base_url}/api/v1/uploads/chunked/{session_id}/'
        )

        if response.status_code != 204:
            raise ChunkedUploadException(
                f'Failed to cancel upload: {response.status_code} '
                f'{response.text}'
            )

    def upload_file(
        self,
        file_path: str,
        resume_session_id: Optional[str] = None,
    ) -> str:
        """
        Upload a file in chunks with automatic resumption.

        Args:
            file_path: Path to file to upload
            resume_session_id: Optional session ID to resume

        Returns:
            Job ID of the created UploadJob
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise ChunkedUploadException(f'File not found: {file_path}')

        total_size = file_path.stat().st_size
        print(f'File size: {total_size / (1024**3):.2f} GB')

        # Calculate file hash
        print('Calculating file hash...')
        file_hash = self._calculate_hash(str(file_path))
        print(f'File hash: {file_hash}')

        # Initialize or resume session
        if resume_session_id:
            print(f'Resuming upload session: {resume_session_id}')
            session_info = self.get_progress(resume_session_id)
            session_id = resume_session_id
            start_chunk = session_info['uploaded_chunks']
        else:
            print('Initializing new upload session...')
            session_info = self.init_upload(
                filename=file_path.name,
                total_size=total_size,
                file_hash=file_hash,
            )
            session_id = session_info['session_id']
            start_chunk = 0

        total_chunks = session_info['total_chunks']
        print(f'Session ID: {session_id}')
        print(f'Total chunks: {total_chunks}')
        print(f'Starting from chunk: {start_chunk}\n')

        # Upload chunks
        with open(file_path, 'rb') as f:
            progress_bar = tqdm(
                total=total_chunks,
                initial=start_chunk,
                unit='chunk',
                desc='Uploading',
                dynamic_ncols=True,
            )

            for chunk_num in range(start_chunk, total_chunks):
                f.seek(chunk_num * self.chunk_size)
                chunk_data = f.read(self.chunk_size)

                result = self.upload_chunk(session_id, chunk_num, chunk_data)

                progress_bar.update(1)
                progress_bar.set_postfix(
                    {'progress': f"{result['progress_percent']}%"}
                )

            progress_bar.close()

        print('\nAll chunks uploaded successfully!')

        # Complete upload
        print('Completing upload and assembling chunks...')
        completion_info = self.complete_upload(session_id, file_hash)

        print(f'\n✓ Upload completed!')
        print(f'Job ID: {completion_info["job_id"]}')
        print(f'Status URL: {completion_info["job_status_url"]}')

        return completion_info['job_id']


def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description='Upload large files using chunked upload API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Upload a new file
  %(prog)s upload archive.tar.gz http://localhost:8000 YOUR_TOKEN
  
  # Resume an incomplete upload
  %(prog)s resume 550e8400-e29b-41d4-a716-446655440000 archive.tar.gz \\
    http://localhost:8000 YOUR_TOKEN
  
  # Check upload progress
  %(prog)s progress 550e8400-e29b-41d4-a716-446655440000 \\
    http://localhost:8000 YOUR_TOKEN
  
  # Cancel an upload
  %(prog)s cancel 550e8400-e29b-41d4-a716-446655440000 \\
    http://localhost:8000 YOUR_TOKEN
        ''',
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Upload command
    upload_parser = subparsers.add_parser('upload', help='Upload a new file')
    upload_parser.add_argument('file', help='File to upload')
    upload_parser.add_argument('server_url', help='Server base URL')
    upload_parser.add_argument('token', help='Authentication token')
    upload_parser.add_argument(
        '--chunk-size',
        type=int,
        default=10485760,
        help='Chunk size in bytes (default 10MB)',
    )

    # Resume command
    resume_parser = subparsers.add_parser('resume', help='Resume an upload')
    resume_parser.add_argument('session_id', help='Upload session ID')
    resume_parser.add_argument('file', help='File to upload')
    resume_parser.add_argument('server_url', help='Server base URL')
    resume_parser.add_argument('token', help='Authentication token')
    resume_parser.add_argument(
        '--chunk-size',
        type=int,
        default=10485760,
        help='Chunk size in bytes (default 10MB)',
    )

    # Progress command
    progress_parser = subparsers.add_parser(
        'progress', help='Check upload progress'
    )
    progress_parser.add_argument('session_id', help='Upload session ID')
    progress_parser.add_argument('server_url', help='Server base URL')
    progress_parser.add_argument('token', help='Authentication token')

    # Cancel command
    cancel_parser = subparsers.add_parser('cancel', help='Cancel an upload')
    cancel_parser.add_argument('session_id', help='Upload session ID')
    cancel_parser.add_argument('server_url', help='Server base URL')
    cancel_parser.add_argument('token', help='Authentication token')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        client = ChunkedUploadClient(
            base_url=args.server_url,
            token=args.token,
            chunk_size=getattr(args, 'chunk_size', 10485760),
        )

        if args.command == 'upload':
            client.upload_file(args.file)

        elif args.command == 'resume':
            client.upload_file(args.file, resume_session_id=args.session_id)

        elif args.command == 'progress':
            progress = client.get_progress(args.session_id)
            print(json.dumps(progress, indent=2, default=str))

        elif args.command == 'cancel':
            client.cancel_upload(args.session_id)
            print(f'Upload {args.session_id} cancelled')

    except ChunkedUploadException as e:
        print(f'✗ Error: {e}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\n✗ Upload interrupted by user', file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f'✗ Unexpected error: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
