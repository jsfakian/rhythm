#!/usr/bin/env python
"""
Orthanc Server Backup and Restore Script

Performs complete backup and restore of Orthanc DICOM storage.

Features:
- Full backup of Orthanc database and DICOM files
- Restore from backup
- Works with both local and remote servers
- Docker container support
- SSH/SFTP for remote operations

Usage:
    # Backup locally (default)
    python backup_orthanc.py backup --ip localhost --remote-path /backups/orthanc

    # Backup to remote server
    python backup_orthanc.py backup --ip 192.168.1.100 --remote-path /backups/orthanc \\
        --ssh-user backup --ssh-key ~/.ssh/id_rsa

    # Backup with Docker
    python backup_orthanc.py backup --ip localhost --remote-path /backups \\
        --use-docker --container-name ct_upload_orthanc

    # List available backups
    python backup_orthanc.py list --ip 192.168.1.100 --remote-path /backups/orthanc --ssh-user backup

    # Restore from latest backup
    python backup_orthanc.py restore --ip localhost --remote-path /backups/orthanc

    # Restore specific backup
    python backup_orthanc.py restore --ip localhost --remote-path /backups/orthanc --backup-id backup_20260227_143022
"""

import argparse
import os
import sys
import subprocess
import shutil
import tarfile
import json
import tempfile
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Dict, Optional
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RemoteStorage:
    """Handles remote file operations via SSH/SFTP."""

    def __init__(self, ip: str, remote_path: str, ssh_user: str = 'root', ssh_key: Optional[str] = None, ssh_port: int = 22):
        """
        Initialize remote storage.

        Args:
            ip: Remote server IP address (localhost for local operations)
            remote_path: Remote path for backups
            ssh_user: SSH username
            ssh_key: Path to SSH private key (None for password auth)
            ssh_port: SSH port
        """
        self.ip = ip
        self.remote_path = remote_path
        self.ssh_user = ssh_user
        self.ssh_key = ssh_key
        self.ssh_port = ssh_port
        self.is_local = (ip == 'localhost' or ip == '127.0.0.1')

    def _build_ssh_cmd(self, cmd: str) -> List[str]:
        """Build SSH command with authentication."""
        ssh_cmd = ['ssh', '-p', str(self.ssh_port)]
        
        if self.ssh_key:
            ssh_cmd.extend(['-i', self.ssh_key])
        
        ssh_cmd.append(f'{self.ssh_user}@{self.ip}')
        ssh_cmd.append(cmd)
        
        return ssh_cmd

    def mkdir(self, path: str) -> bool:
        """Create directory on remote server."""
        if self.is_local:
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
                return True
            except Exception as e:
                logger.error(f"Failed to create directory: {e}")
                return False
        
        cmd = f'mkdir -p "{path}"'
        try:
            result = subprocess.run(self._build_ssh_cmd(cmd), capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.error(f"SSH mkdir failed: {result.stderr}")
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to create remote directory: {e}")
            return False

    def exists(self, path: str) -> bool:
        """Check if path exists on remote server."""
        if self.is_local:
            return Path(path).exists()
        
        cmd = f'test -e "{path}" && echo "exists"'
        try:
            result = subprocess.run(self._build_ssh_cmd(cmd), capture_output=True, text=True, timeout=10)
            return 'exists' in result.stdout
        except Exception:
            return False

    def upload_file(self, local_file: Path, remote_file: str) -> bool:
        """Upload file to remote server."""
        if self.is_local:
            try:
                shutil.copy2(local_file, remote_file)
                return True
            except Exception as e:
                logger.error(f"Failed to copy file: {e}")
                return False
        
        try:
            cmd = ['scp', '-P', str(self.ssh_port)]
            if self.ssh_key:
                cmd.extend(['-i', self.ssh_key])
            cmd.extend([str(local_file), f'{self.ssh_user}@{self.ip}:{remote_file}'])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                logger.error(f"SCP upload failed: {result.stderr}")
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to upload file: {e}")
            return False

    def download_file(self, remote_file: str, local_file: Path) -> bool:
        """Download file from remote server."""
        if self.is_local:
            try:
                shutil.copy2(remote_file, local_file)
                return True
            except Exception as e:
                logger.error(f"Failed to copy file: {e}")
                return False
        
        try:
            cmd = ['scp', '-P', str(self.ssh_port)]
            if self.ssh_key:
                cmd.extend(['-i', self.ssh_key])
            cmd.extend([f'{self.ssh_user}@{self.ip}:{remote_file}', str(local_file)])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                logger.error(f"SCP download failed: {result.stderr}")
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to download file: {e}")
            return False

    def list_dir(self, path: str) -> List[str]:
        """List directory contents on remote server."""
        if self.is_local:
            try:
                return [item.name for item in Path(path).iterdir()]
            except Exception:
                return []
        
        cmd = f'find "{path}" -maxdepth 1 -type d'
        try:
            result = subprocess.run(self._build_ssh_cmd(cmd), capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return [line.split('/')[-1] for line in result.stdout.strip().split('\n') if line]
            return []
        except Exception:
            return []

    def read_file(self, path: str) -> Optional[str]:
        """Read file from remote server."""
        if self.is_local:
            try:
                return Path(path).read_text()
            except Exception:
                return None
        
        cmd = f'cat "{path}"'
        try:
            result = subprocess.run(self._build_ssh_cmd(cmd), capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return result.stdout
            return None
        except Exception:
            return None

    def delete_dir(self, path: str) -> bool:
        """Delete directory on remote server."""
        if self.is_local:
            try:
                shutil.rmtree(path)
                return True
            except Exception:
                return False
        
        cmd = f'rm -rf "{path}"'
        try:
            result = subprocess.run(self._build_ssh_cmd(cmd), capture_output=True, text=True, timeout=60)
            return result.returncode == 0
        except Exception:
            return False


class OrthancBackupManager:
    """Manages backup and restore operations for Orthanc server."""

    def __init__(
        self,
        ip: str = 'localhost',
        ssh_user: str = 'root',
        ssh_key: Optional[str] = None,
        ssh_port: int = 22,
        use_docker: bool = False,
        container_name: str = 'ct_upload_orthanc'
    ):
        """
        Initialize the backup manager.

        Args:
            ip: Remote server IP address (localhost for local operations)
            ssh_user: SSH username for remote access
            ssh_key: Path to SSH private key
            ssh_port: SSH port
            use_docker: Whether to use Docker container
            container_name: Docker container name for Orthanc
        """
        self.ip = ip
        self.ssh_user = ssh_user
        self.ssh_key = ssh_key
        self.ssh_port = ssh_port
        self.use_docker = use_docker
        self.container_name = container_name
        self.orthanc_data_dir = Path('/var/lib/orthanc/db')
        self.orthanc_config_dir = Path('/etc/orthanc')

    def _check_docker_container(self) -> bool:
        """Check if Orthanc Docker container exists and is running."""
        try:
            result = subprocess.run(
                ['docker', 'ps', '--format', 'table {{.Names}}'],
                capture_output=True,
                text=True,
                timeout=10
            )
            return self.container_name in result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.error("Docker not available or not running")
            return False

    def _is_orthanc_accessible(self) -> bool:
        """Check if Orthanc server is accessible."""
        try:
            if self.use_docker:
                result = subprocess.run(
                    ['docker', 'exec', self.container_name, 'curl', '-s', 'http://localhost:8042/system'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
            else:
                result = subprocess.run(
                    ['curl', '-s', 'http://localhost:8042/system'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _execute_in_container(self, cmd: List[str]) -> Tuple[int, str, str]:
        """
        Execute command in Docker container.

        Args:
            cmd: Command to execute (as array)

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        docker_cmd = ['docker', 'exec', self.container_name] + cmd
        result = subprocess.run(docker_cmd, capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr

    def _create_backup_metadata(self, backup_id: str) -> Dict:
        """Create metadata file for backup."""
        return {
            'backup_id': backup_id,
            'timestamp': datetime.now().isoformat(),
            'type': 'orthanc_full',
            'description': 'Complete Orthanc database and DICOM storage backup',
            'orthanc_data_dir': str(self.orthanc_data_dir),
        }

    def backup_orthanc(self, remote_path: str) -> Tuple[bool, str]:
        """
        Create full backup of Orthanc server.

        Args:
            remote_path: Remote path to store backup

        Returns:
            Tuple of (success, backup_id)
        """
        # Initialize remote storage
        storage = RemoteStorage(self.ip, remote_path, self.ssh_user, self.ssh_key, self.ssh_port)
        
        # Generate backup ID
        backup_id = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        remote_backup_dir = f"{remote_path}/{backup_id}"
        
        # Create remote backup directory
        if not storage.mkdir(remote_backup_dir):
            logger.error("Failed to create remote backup directory")
            return False, ""
        
        logger.info(f"Created backup directory: {remote_backup_dir}")
        logger.info("Starting Orthanc backup...")
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_dir = Path(temp_dir)
                
                if self.use_docker:
                    success = self._backup_orthanc_docker(temp_dir)
                else:
                    success = self._backup_orthanc_local(temp_dir)
                
                if success:
                    # Upload tar file
                    backup_tar = temp_dir / 'orthanc_data.tar.gz'
                    logger.info("Uploading backup to remote storage...")
                    if not storage.upload_file(backup_tar, f"{remote_backup_dir}/orthanc_data.tar.gz"):
                        logger.error("Failed to upload backup")
                        storage.delete_dir(remote_backup_dir)
                        return False, ""
                    
                    # Create and upload metadata
                    metadata = self._create_backup_metadata(backup_id)
                    metadata_file = temp_dir / 'metadata.json'
                    try:
                        with open(metadata_file, 'w') as f:
                            json.dump(metadata, f, indent=2)
                        if storage.upload_file(metadata_file, f"{remote_backup_dir}/metadata.json"):
                            logger.info(f"Backup metadata uploaded")
                        else:
                            logger.warning("Failed to upload metadata")
                    except Exception as e:
                        logger.error(f"Failed to create metadata: {e}")
                    
                    logger.info(f"✓ Backup completed: {backup_id}")
                    return True, backup_id
                else:
                    # Clean up failed backup
                    storage.delete_dir(remote_backup_dir)
                    return False, ""
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            storage.delete_dir(remote_backup_dir)
            return False, ""

    def _backup_orthanc_docker(self, temp_dir: Path) -> bool:
        """
        Backup Orthanc using Docker container.

        Args:
            temp_dir: Temporary directory for backup

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Backing up Orthanc from Docker container: {self.container_name}")
        
        if not self._check_docker_container():
            logger.error(f"Docker container not found: {self.container_name}")
            return False
        
        # Create temporary directory in container
        temp_tar = '/tmp/orthanc_backup.tar.gz'
        
        try:
            # Create tar backup in container
            logger.info("Creating tar archive in container...")
            returncode, stdout, stderr = self._execute_in_container(
                ['tar', '-czf', temp_tar, '-C', '/var/lib/orthanc', 'db']
            )
            
            if returncode != 0:
                logger.error(f"Failed to create tar in container: {stderr}")
                return False
            
            # Copy tar from container
            logger.info("Copying backup from container...")
            backup_tar = temp_dir / 'orthanc_data.tar.gz'
            result = subprocess.run(
                ['docker', 'cp', f'{self.container_name}:{temp_tar}', str(backup_tar)],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to copy backup from container: {result.stderr}")
                return False
            
            # Clean up container temp file
            self._execute_in_container(['rm', '-f', temp_tar])
            
            logger.info(f"Backup size: {backup_tar.stat().st_size / (1024**3):.2f} GB")
            return True
            
        except Exception as e:
            logger.error(f"Docker backup failed: {e}")
            return False

    def _backup_orthanc_local(self, temp_dir: Path) -> bool:
        """
        Backup Orthanc from local filesystem.

        Args:
            temp_dir: Temporary directory for backup

        Returns:
            True if successful, False otherwise
        """
        logger.info("Backing up Orthanc from local filesystem...")
        
        if not self.orthanc_data_dir.exists():
            logger.error(f"Orthanc data directory not found: {self.orthanc_data_dir}")
            return False
        
        backup_tar = temp_dir / 'orthanc_data.tar.gz'
        
        try:
            logger.info(f"Creating tar archive: {backup_tar}")
            with tarfile.open(backup_tar, 'w:gz') as tar:
                tar.add(self.orthanc_data_dir, arcname='db')
            
            logger.info(f"Backup size: {backup_tar.stat().st_size / (1024**3):.2f} GB")
            return True
            
        except Exception as e:
            logger.error(f"Failed to backup Orthanc: {e}")
            return False

    def list_backups(self, remote_path: str) -> List[Dict]:
        """
        List available backups.

        Args:
            remote_path: Remote path where backups are stored

        Returns:
            List of backup metadata dictionaries
        """
        storage = RemoteStorage(self.ip, remote_path, self.ssh_user, self.ssh_key, self.ssh_port)
        
        if not storage.exists(remote_path):
            logger.warning(f"Backup path does not exist: {remote_path}")
            return []
        
        backups = []
        backup_dirs = storage.list_dir(remote_path)
        
        for backup_dir in sorted(backup_dirs, reverse=True):
            if not backup_dir:
                continue
            
            metadata_path = f"{remote_path}/{backup_dir}/metadata.json"
            metadata_content = storage.read_file(metadata_path)
            
            if metadata_content:
                try:
                    metadata = json.loads(metadata_content)
                    backups.append(metadata)
                except Exception as e:
                    logger.error(f"Failed to read metadata for {backup_dir}: {e}")
        
        return backups

    def restore_orthanc(
        self,
        remote_path: str,
        backup_id: Optional[str] = None,
        skip_validation: bool = False,
    ) -> bool:
        """
        Restore Orthanc from backup.

        Args:
            remote_path: Remote path where backups are stored
            backup_id: Specific backup ID to restore (latest if not specified)
            skip_validation: Skip Orthanc accessibility check before restore

        Returns:
            True if successful, False otherwise
        """
        storage = RemoteStorage(self.ip, remote_path, self.ssh_user, self.ssh_key, self.ssh_port)
        
        # Get backup directory
        if backup_id:
            remote_backup_dir = f"{remote_path}/{backup_id}"
        else:
            # Use latest backup
            backups = self.list_backups(remote_path)
            if not backups:
                logger.error("No backups found")
                return False
            remote_backup_dir = f"{remote_path}/{backups[0]['backup_id']}"
        
        if not storage.exists(remote_backup_dir):
            logger.error(f"Backup not found: {remote_backup_dir}")
            return False
        
        logger.info(f"Restoring from backup: {remote_backup_dir}")
        
        # Load metadata
        metadata_content = storage.read_file(f"{remote_backup_dir}/metadata.json")
        if metadata_content:
            try:
                metadata = json.loads(metadata_content)
                logger.info(f"Backup timestamp: {metadata.get('timestamp', 'unknown')}")
            except Exception:
                pass
        
        # Check if Orthanc is accessible (warning only)
        if not skip_validation:
            if not self.use_docker and not self._is_orthanc_accessible():
                logger.warning("Orthanc server may not be accessible")
            elif self.use_docker and not self._check_docker_container():
                logger.warning(f"Orthanc container {self.container_name} may not be running")
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_dir = Path(temp_dir)
                
                # Download backup
                logger.info("Downloading backup from remote storage...")
                backup_tar = temp_dir / 'orthanc_data.tar.gz'
                if not storage.download_file(f"{remote_backup_dir}/orthanc_data.tar.gz", backup_tar):
                    logger.error("Failed to download backup")
                    return False
                
                if self.use_docker:
                    success = self._restore_orthanc_docker(backup_tar)
                else:
                    success = self._restore_orthanc_local(backup_tar)
                
                if success:
                    logger.info("✓ Restore completed successfully")
                else:
                    logger.error("✗ Restore failed")
                
                return success
            
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def _restore_orthanc_docker(self, backup_tar: Path) -> bool:
        """
        Restore Orthanc using Docker container.

        Args:
            backup_tar: Path to backup tar file

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Restoring Orthanc in Docker container: {self.container_name}")
        
        if not self._check_docker_container():
            logger.error(f"Docker container not found: {self.container_name}")
            return False
        
        if not backup_tar.exists():
            logger.error(f"Backup tar file not found: {backup_tar}")
            return False
        
        temp_tar = '/tmp/orthanc_backup.tar.gz'
        
        try:
            # Copy tar to container
            logger.info("Copying backup to container...")
            result = subprocess.run(
                ['docker', 'cp', str(backup_tar), f'{self.container_name}:{temp_tar}'],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to copy backup to container: {result.stderr}")
                return False
            
            # Stop Orthanc gracefully
            logger.info("Stopping Orthanc service gracefully...")
            self._execute_in_container(['/bin/sh', '-c', 'pkill -TERM -f orthanc || true'])
            
            # Wait a bit for graceful shutdown
            import time
            time.sleep(5)
            
            # Remove old data
            logger.info("Removing old Orthanc data...")
            returncode, _, stderr = self._execute_in_container(
                ['rm', '-rf', '/var/lib/orthanc/db']
            )
            
            if returncode != 0:
                logger.error(f"Failed to remove old data: {stderr}")
                return False
            
            # Extract backup
            logger.info("Extracting backup...")
            returncode, _, stderr = self._execute_in_container(
                ['tar', '-xzf', temp_tar, '-C', '/var/lib/orthanc']
            )
            
            if returncode != 0:
                logger.error(f"Failed to extract backup: {stderr}")
                return False
            
            # Reset permissions
            logger.info("Setting permissions...")
            self._execute_in_container(['chown', '-R', '1000:1000', '/var/lib/orthanc'])
            
            # Clean up temp tar
            self._execute_in_container(['rm', '-f', temp_tar])
            
            logger.info("Container will restart automatically")
            return True
            
        except Exception as e:
            logger.error(f"Docker restore failed: {e}")
            return False

    def _restore_orthanc_local(self, backup_tar: Path) -> bool:
        """
        Restore Orthanc to local filesystem.

        Args:
            backup_tar: Path to backup tar file

        Returns:
            True if successful, False otherwise
        """
        logger.info("Restoring Orthanc to local filesystem...")
        
        if not backup_tar.exists():
            logger.error(f"Backup tar file not found: {backup_tar}")
            return False
        
        try:
            # Check if data directory exists
            if self.orthanc_data_dir.exists():
                logger.info("Removing old Orthanc data...")
                import time
                # Give services a moment to notice
                time.sleep(2)
                shutil.rmtree(self.orthanc_data_dir)
            
            # Create parent directory
            self.orthanc_data_dir.parent.mkdir(parents=True, exist_ok=True)
            
            # Extract backup
            logger.info("Extracting backup...")
            with tarfile.open(backup_tar, 'r:gz') as tar:
                tar.extractall(path=self.orthanc_data_dir.parent)
            
            logger.info(f"Restored: {self.orthanc_data_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Orthanc Server Backup and Restore Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Backup command
    backup_parser = subparsers.add_parser('backup', help='Create backup of Orthanc')
    backup_parser.add_argument('--ip', default='localhost', help='Remote server IP address (default: localhost)')
    backup_parser.add_argument('--remote-path', required=True, help='Remote path to store backup')
    backup_parser.add_argument('--ssh-user', default='root', help='SSH username (default: root)')
    backup_parser.add_argument('--ssh-key', help='Path to SSH private key (default: password auth)')
    backup_parser.add_argument('--ssh-port', type=int, default=22, help='SSH port (default: 22)')
    backup_parser.add_argument(
        '--use-docker',
        action='store_true',
        help='Backup from Docker container'
    )
    backup_parser.add_argument(
        '--container-name',
        default='ct_upload_orthanc',
        help='Docker container name (default: ct_upload_orthanc)'
    )
    
    # Restore command
    restore_parser = subparsers.add_parser('restore', help='Restore from backup')
    restore_parser.add_argument('--ip', default='localhost', help='Remote server IP address (default: localhost)')
    restore_parser.add_argument('--remote-path', required=True, help='Remote path where backups are stored')
    restore_parser.add_argument('--backup-id', help='Specific backup ID to restore (latest if not specified)')
    restore_parser.add_argument('--ssh-user', default='root', help='SSH username (default: root)')
    restore_parser.add_argument('--ssh-key', help='Path to SSH private key (default: password auth)')
    restore_parser.add_argument('--ssh-port', type=int, default=22, help='SSH port (default: 22)')
    restore_parser.add_argument(
        '--use-docker',
        action='store_true',
        help='Restore to Docker container'
    )
    restore_parser.add_argument(
        '--container-name',
        default='ct_upload_orthanc',
        help='Docker container name (default: ct_upload_orthanc)'
    )
    restore_parser.add_argument(
        '--skip-validation',
        action='store_true',
        help='Skip Orthanc accessibility check'
    )
    
    # List command
    list_parser = subparsers.add_parser('list', help='List available backups')
    list_parser.add_argument('--ip', default='localhost', help='Remote server IP address (default: localhost)')
    list_parser.add_argument('--remote-path', required=True, help='Remote path where backups are stored')
    list_parser.add_argument('--ssh-user', default='root', help='SSH username (default: root)')
    list_parser.add_argument('--ssh-key', help='Path to SSH private key (default: password auth)')
    list_parser.add_argument('--ssh-port', type=int, default=22, help='SSH port (default: 22)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Get container name from args if provided
    container_name = getattr(args, 'container_name', 'ct_upload_orthanc')
    use_docker = getattr(args, 'use_docker', False)
    
    manager = OrthancBackupManager(
        ip=args.ip,
        ssh_user=args.ssh_user,
        ssh_key=args.ssh_key,
        ssh_port=args.ssh_port,
        use_docker=use_docker,
        container_name=container_name
    )
    
    if args.command == 'backup':
        success, backup_id = manager.backup_orthanc(args.remote_path)
        sys.exit(0 if success else 1)
    
    elif args.command == 'restore':
        skip_validation = getattr(args, 'skip_validation', False)
        success = manager.restore_orthanc(
            args.remote_path,
            backup_id=args.backup_id,
            skip_validation=skip_validation,
        )
        sys.exit(0 if success else 1)
    
    elif args.command == 'list':
        backups = manager.list_backups(args.remote_path)
        if backups:
            logger.info("Available backups:")
            for i, backup in enumerate(backups, 1):
                logger.info(f"\n{i}. {backup['backup_id']}")
                logger.info(f"   Timestamp: {backup.get('timestamp', 'unknown')}")
                logger.info(f"   Type: {backup.get('type', 'unknown')}")
        else:
            logger.info("No backups found")


if __name__ == '__main__':
    main()
