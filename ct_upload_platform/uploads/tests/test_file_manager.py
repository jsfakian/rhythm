"""
Unit tests for file management utilities (raw_data and processed_data directories).
Tests directory creation, file management, and cleanup operations.
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, MagicMock
from django.test import TestCase as DjangoTestCase, override_settings
from django.conf import settings

from uploads.file_manager import (
    ensure_directory_exists,
    get_raw_data_user_dir,
    get_processed_data_job_dir,
    get_all_raw_data_users,
    get_user_tar_files,
    get_job_processed_files,
    delete_job_processed_data,
    delete_user_raw_data,
    get_directory_size,
)


class FileManagerTestCase(DjangoTestCase):
    """Test file manager utility functions."""

    @classmethod
    def setUpClass(cls):
        """Set up test directories."""
        super().setUpClass()
        cls.test_temp_dir = tempfile.mkdtemp(prefix="test_file_manager_")

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
        
        # Create directories if they don't exist
        os.makedirs(self.raw_data_dir, exist_ok=True)
        os.makedirs(self.processed_data_dir, exist_ok=True)

    def tearDown(self):
        """Clean up after each test."""
        if os.path.exists(self.raw_data_dir):
            shutil.rmtree(self.raw_data_dir)
        if os.path.exists(self.processed_data_dir):
            shutil.rmtree(self.processed_data_dir)

    @override_settings(RAW_DATA_DIR="/tmp/test_raw_data")
    def test_ensure_directory_exists_creates_dir(self):
        """Test that ensure_directory_exists creates directory."""
        test_dir = os.path.join(self.test_temp_dir, "new_dir")
        self.assertFalse(os.path.exists(test_dir))
        
        result = ensure_directory_exists(test_dir)
        
        self.assertTrue(os.path.exists(test_dir))
        self.assertIsInstance(result, Path)
        self.assertEqual(str(result), test_dir)
        
        # Clean up
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

    @override_settings(RAW_DATA_DIR="/tmp/test_raw_data")
    def test_ensure_directory_exists_with_existing_dir(self):
        """Test that ensure_directory_exists handles existing directories."""
        test_dir = os.path.join(self.test_temp_dir, "existing_dir")
        os.makedirs(test_dir, exist_ok=True)
        
        result = ensure_directory_exists(test_dir)
        
        self.assertTrue(os.path.exists(test_dir))
        self.assertEqual(str(result), test_dir)

    def test_get_raw_data_user_dir_creates_user_directory(self):
        """Test that get_raw_data_user_dir creates user-specific directory."""
        uploader_id = "test_user_123"
        
        with patch('uploads.file_manager.settings.RAW_DATA_DIR', self.raw_data_dir):
            result = get_raw_data_user_dir(uploader_id)
        
        expected_path = os.path.join(self.raw_data_dir, uploader_id)
        self.assertEqual(str(result), expected_path)
        self.assertTrue(os.path.isdir(expected_path))

    def test_get_raw_data_user_dir_with_multiple_users(self):
        """Test that multiple user directories can be created."""
        users = ["user1", "user2", "user3"]
        
        with patch('uploads.file_manager.settings.RAW_DATA_DIR', self.raw_data_dir):
            for user in users:
                get_raw_data_user_dir(user)
        
        for user in users:
            user_path = os.path.join(self.raw_data_dir, user)
            self.assertTrue(os.path.isdir(user_path))

    def test_get_processed_data_job_dir_creates_job_directory(self):
        """Test that get_processed_data_job_dir creates job-specific directory."""
        job_id = "job-12345-67890"
        
        with patch('uploads.file_manager.settings.PROCESSED_DATA_DIR', self.processed_data_dir):
            result = get_processed_data_job_dir(job_id)
        
        expected_path = os.path.join(self.processed_data_dir, job_id)
        self.assertEqual(str(result), expected_path)
        self.assertTrue(os.path.isdir(expected_path))

    def test_get_all_raw_data_users_returns_user_list(self):
        """Test that get_all_raw_data_users returns list of users."""
        users = ["user1", "user2", "user3"]
        
        with patch('uploads.file_manager.settings.RAW_DATA_DIR', self.raw_data_dir):
            for user in users:
                get_raw_data_user_dir(user)
            
            result = get_all_raw_data_users()
        
        self.assertEqual(sorted(result), sorted(users))

    def test_get_all_raw_data_users_empty_directory(self):
        """Test that get_all_raw_data_users returns empty list for empty directory."""
        with patch('uploads.file_manager.settings.RAW_DATA_DIR', self.raw_data_dir):
            result = get_all_raw_data_users()
        
        self.assertEqual(result, [])

    def test_get_all_raw_data_users_nonexistent_directory(self):
        """Test that get_all_raw_data_users handles nonexistent directory."""
        nonexistent = os.path.join(self.test_temp_dir, "nonexistent")
        
        with patch('uploads.file_manager.settings.RAW_DATA_DIR', nonexistent):
            result = get_all_raw_data_users()
        
        self.assertEqual(result, [])

    def test_get_user_tar_files_returns_tar_list(self):
        """Test that get_user_tar_files returns list of tar files."""
        user = "test_user"
        tar_files = ["file1.tar", "file2.tar.gz", "file3.tar"]
        
        with patch('uploads.file_manager.settings.RAW_DATA_DIR', self.raw_data_dir):
            user_dir = get_raw_data_user_dir(user)
            
            # Create dummy tar files
            for tar_file in tar_files:
                (user_dir / tar_file).touch()
            
            result = get_user_tar_files(user)
        
        result_names = [os.path.basename(str(f)) for f in result]
        self.assertEqual(sorted(result_names), sorted(tar_files))

    def test_get_user_tar_files_filters_non_tar_files(self):
        """Test that get_user_tar_files filters out non-tar files."""
        user = "test_user"
        
        with patch('uploads.file_manager.settings.RAW_DATA_DIR', self.raw_data_dir):
            user_dir = get_raw_data_user_dir(user)
            
            # Create mixed files
            (user_dir / "file1.tar").touch()
            (user_dir / "file2.txt").touch()
            (user_dir / "file3.tar.gz").touch()
            (user_dir / "readme.md").touch()
            
            result = get_user_tar_files(user)
        
        result_names = [os.path.basename(str(f)) for f in result]
        self.assertIn("file1.tar", result_names)
        self.assertIn("file3.tar.gz", result_names)
        self.assertNotIn("file2.txt", result_names)
        self.assertNotIn("readme.md", result_names)

    def test_get_job_processed_files_returns_all_files(self):
        """Test that get_job_processed_files returns all files in job directory."""
        job_id = "job-12345"
        
        with patch('uploads.file_manager.settings.PROCESSED_DATA_DIR', self.processed_data_dir):
            job_dir = get_processed_data_job_dir(job_id)
            
            # Create nested structure
            (job_dir / "manifest.json").touch()
            (job_dir / "images").mkdir()
            (job_dir / "images" / "image1.dcm").touch()
            (job_dir / "images" / "image2.dcm").touch()
            
            result = get_job_processed_files(job_id)
        
        result_names = [os.path.basename(str(f)) for f in result]
        self.assertIn("manifest.json", result_names)
        self.assertIn("image1.dcm", result_names)
        self.assertIn("image2.dcm", result_names)

    def test_delete_job_processed_data_removes_directory(self):
        """Test that delete_job_processed_data removes the job directory."""
        job_id = "job-12345"
        
        with patch('uploads.file_manager.settings.PROCESSED_DATA_DIR', self.processed_data_dir):
            job_dir = get_processed_data_job_dir(job_id)
            (job_dir / "manifest.json").touch()
            
            self.assertTrue(os.path.exists(str(job_dir)))
            
            result = delete_job_processed_data(job_id)
        
        self.assertTrue(result)
        self.assertFalse(os.path.exists(str(job_dir)))

    def test_delete_job_processed_data_nonexistent_directory(self):
        """Test that delete_job_processed_data handles nonexistent directory."""
        job_id = "nonexistent-job"
        
        with patch('uploads.file_manager.settings.PROCESSED_DATA_DIR', self.processed_data_dir):
            result = delete_job_processed_data(job_id)
        
        self.assertTrue(result)

    def test_delete_user_raw_data_removes_directory(self):
        """Test that delete_user_raw_data removes user directory."""
        user = "test_user"
        
        with patch('uploads.file_manager.settings.RAW_DATA_DIR', self.raw_data_dir):
            user_dir = get_raw_data_user_dir(user)
            (user_dir / "file1.tar").touch()
            
            self.assertTrue(os.path.exists(str(user_dir)))
            
            result = delete_user_raw_data(user)
        
        self.assertTrue(result)
        self.assertFalse(os.path.exists(str(user_dir)))

    def test_delete_user_raw_data_nonexistent_directory(self):
        """Test that delete_user_raw_data handles nonexistent directory."""
        user = "nonexistent_user"
        
        with patch('uploads.file_manager.settings.RAW_DATA_DIR', self.raw_data_dir):
            result = delete_user_raw_data(user)
        
        self.assertTrue(result)

    def test_get_directory_size_calculates_total(self):
        """Test that get_directory_size calculates total directory size correctly."""
        job_id = "job-12345"
        
        with patch('uploads.file_manager.settings.PROCESSED_DATA_DIR', self.processed_data_dir):
            job_dir = get_processed_data_job_dir(job_id)
            
            # Create files with known sizes
            with open(str(job_dir / "file1.txt"), "w") as f:
                f.write("X" * 1000)  # 1KB
            
            with open(str(job_dir / "file2.txt"), "w") as f:
                f.write("Y" * 2000)  # 2KB
            
            result = get_directory_size(str(job_dir))
        
        self.assertEqual(result, 3000)

    def test_get_directory_size_empty_directory(self):
        """Test that get_directory_size returns 0 for empty directory."""
        job_id = "job-12345"
        
        with patch('uploads.file_manager.settings.PROCESSED_DATA_DIR', self.processed_data_dir):
            job_dir = get_processed_data_job_dir(job_id)
            
            result = get_directory_size(str(job_dir))
        
        self.assertEqual(result, 0)

    def test_get_directory_size_nonexistent_directory(self):
        """Test that get_directory_size returns 0 for nonexistent directory."""
        nonexistent = os.path.join(self.test_temp_dir, "nonexistent")
        
        result = get_directory_size(nonexistent)
        
        self.assertEqual(result, 0)

    def test_get_directory_size_nested_files(self):
        """Test that get_directory_size includes nested files."""
        job_id = "job-12345"
        
        with patch('uploads.file_manager.settings.PROCESSED_DATA_DIR', self.processed_data_dir):
            job_dir = get_processed_data_job_dir(job_id)
            
            # Create nested structure
            (job_dir / "subdir").mkdir()
            with open(str(job_dir / "file1.txt"), "w") as f:
                f.write("X" * 1000)
            
            with open(str(job_dir / "subdir" / "file2.txt"), "w") as f:
                f.write("Y" * 2000)
            
            result = get_directory_size(str(job_dir))
        
        self.assertEqual(result, 3000)
