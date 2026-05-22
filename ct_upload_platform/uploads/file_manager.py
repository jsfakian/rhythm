"""
File management utilities for handling raw_data and processed_data directories.
"""

import os
from pathlib import Path
from django.conf import settings


def ensure_directory_exists(directory_path):
    """
    Ensure a directory exists, creating it if necessary.
    
    Args:
        directory_path: Path to the directory
        
    Returns:
        Path object for the directory
    """
    dir_path = Path(directory_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def get_raw_data_user_dir(uploader_id):
    """
    Get the raw_data directory path for a specific user.
    Creates the directory if it doesn't exist.
    
    Args:
        uploader_id: User identifier (username or ID)
        
    Returns:
        Path object for raw_data/{uploader_id}/
    """
    raw_data_user_dir = Path(settings.RAW_DATA_DIR) / uploader_id
    return ensure_directory_exists(raw_data_user_dir)


def get_processed_data_job_dir(job_id):
    """
    Get the processed_data directory path for a specific job.
    Creates the directory if it doesn't exist.
    
    Args:
        job_id: UUID of the upload job
        
    Returns:
        Path object for processed_data/{job_id}/
    """
    processed_data_job_dir = Path(settings.PROCESSED_DATA_DIR) / str(job_id)
    return ensure_directory_exists(processed_data_job_dir)


def get_all_raw_data_users():
    """
    Get a list of all user directories in raw_data.
    
    Returns:
        List of uploader_ids (directory names) in raw_data
    """
    raw_data_path = Path(settings.RAW_DATA_DIR)
    if not raw_data_path.exists():
        return []
    
    return [d.name for d in raw_data_path.iterdir() if d.is_dir()]


def get_user_tar_files(uploader_id):
    """
    Get all tar files for a specific user in raw_data.
    
    Args:
        uploader_id: User identifier
        
    Returns:
        List of tar file paths for the user
    """
    user_dir = get_raw_data_user_dir(uploader_id)
    tar_files = list(user_dir.glob("*.tar*"))
    return sorted(tar_files, key=lambda x: x.stat().st_mtime, reverse=True)


def get_job_processed_files(job_id):
    """
    Get all files in the processed_data directory for a job.
    
    Args:
        job_id: UUID of the upload job
        
    Returns:
        List of file paths in processed_data/{job_id}/
    """
    job_dir = get_processed_data_job_dir(job_id)
    files = []
    for item in job_dir.rglob("*"):
        if item.is_file():
            files.append(item)
    return sorted(files)


def delete_job_processed_data(job_id):
    """
    Delete all processed data for a specific job.
    
    Args:
        job_id: UUID of the upload job
        
    Returns:
        True if successful, False otherwise
    """
    job_dir = Path(settings.PROCESSED_DATA_DIR) / str(job_id)
    if job_dir.exists():
        try:
            import shutil
            shutil.rmtree(job_dir)
            return True
        except Exception as e:
            print(f"Failed to delete job processed data {job_dir}: {e}")
            return False
    return True


def delete_user_raw_data(uploader_id):
    """
    Delete all raw data (tar files) for a specific user.
    
    Args:
        uploader_id: User identifier
        
    Returns:
        True if successful, False otherwise
    """
    user_dir = Path(settings.RAW_DATA_DIR) / uploader_id
    if user_dir.exists():
        try:
            import shutil
            shutil.rmtree(user_dir)
            return True
        except Exception as e:
            print(f"Failed to delete user raw data {user_dir}: {e}")
            return False
    return True


def get_directory_size(directory_path):
    """
    Get the total size of a directory in bytes.
    
    Args:
        directory_path: Path to the directory
        
    Returns:
        Total size in bytes
    """
    total_size = 0
    dir_path = Path(directory_path)
    if dir_path.exists():
        for file_path in dir_path.rglob("*"):
            if file_path.is_file():
                total_size += file_path.stat().st_size
    return total_size
