#!/usr/bin/env python
"""
Django App Backup and Restore Script

Performs conditional backups of:
- PostgreSQL database (ct_upload_platform)
- Raw data directory (/app/raw_data)
- Processed data directory (/app/processed_data)
- Media directory (/app/media)

Usage:
    # Backup database and raw data to local path
    python backup_django.py backup --database --raw-data --ip localhost --remote-path /backups/django

    # Backup to remote server via SSH
    python backup_django.py backup --database --raw-data --processed-data --media \\
        --ip 192.168.1.100 --remote-path /backups/django --ssh-user backup --ssh-key ~/.ssh/id_rsa

    # List available backups on remote server
    python backup_django.py list --ip 192.168.1.100 --remote-path /backups/django --ssh-user backup

    # Restore from latest backup on remote server
    python backup_django.py restore --ip 192.168.1.100 --remote-path /backups/django --ssh-user backup

    # Restore specific backup
    python backup_django.py restore --ip 192.168.1.100 --remote-path /backups/django \\
        --backup-id backup_20260227_143022 --ssh-user backup
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


class DjangoBackupManager:
    """Manages backup and restore operations for Django application."""

    def __init__(
        self,
        django_base_dir: Optional[Path] = None,
        ip: str = 'localhost',
        ssh_user: str = 'root',
        ssh_key: Optional[str] = None,
        ssh_port: int = 22,
    ):
        """
        Initialize the backup manager.

        Args:
            django_base_dir: Path to Django project base directory
            ip: Remote server IP address (localhost for local operations)
            ssh_user: SSH username for remote access
            ssh_key: Path to SSH private key
            ssh_port: SSH port
        """
        if django_base_dir is None:
            django_base_dir = Path(__file__).resolve().parent
        
        self.base_dir = django_base_dir
        self.raw_data_dir = self.base_dir / 'raw_data'
        self.processed_data_dir = self.base_dir / 'processed_data'
        self.media_dir = self.base_dir / 'media'
        
        self.ip = ip
        self.ssh_user = ssh_user
        self.ssh_key = ssh_key
        self.ssh_port = ssh_port
        
        # Load Django settings for database configuration
        self.db_config = self._load_db_config()
        
    def _load_db_config(self) -> Dict:
        """Load database configuration from Django settings."""
        db_config = {
            'name': os.getenv('DB_NAME', 'ct_upload_platform'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'password'),
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '5432'),
        }
        return db_config

    def _create_backup_metadata(self, backup_id: str, components: List[str]) -> Dict:
        """Create metadata file for backup."""
        return {
            'backup_id': backup_id,
            'timestamp': datetime.now().isoformat(),
            'components': components,
            'django_version': self._get_django_version(),
            'database': {
                'engine': 'postgresql',
                'name': self.db_config['name'],
            }
        }

    def _get_django_version(self) -> str:
        """Get Django version."""
        try:
            import django
            return django.__version__
        except ImportError:
            return 'unknown'

    def backup_database(self, output_path: Path) -> bool:
        """
        Backup PostgreSQL database using pg_dump.

        Args:
            output_path: Path to save database backup

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Starting database backup...")
        
        db_backup_file = output_path / 'database.sql'
        
        try:
            # Build pg_dump command
            env = os.environ.copy()
            env['PGPASSWORD'] = self.db_config['password']
            
            cmd = [
                'pg_dump',
                '-h', self.db_config['host'],
                '-p', self.db_config['port'],
                '-U', self.db_config['user'],
                '-d', self.db_config['name'],
                '-v',
            ]
            
            logger.info(f"Executing: {' '.join(cmd)}")
            
            with open(db_backup_file, 'w') as f:
                result = subprocess.run(
                    cmd,
                    env=env,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3600
                )
            
            if result.returncode != 0:
                logger.error(f"pg_dump failed: {result.stderr}")
                db_backup_file.unlink()
                return False
            
            logger.info(f"Database backup saved: {db_backup_file}")
            return True
            
        except FileNotFoundError:
            logger.error("pg_dump not found. Install PostgreSQL client tools.")
            return False
        except Exception as e:
            logger.error(f"Failed to backup database: {e}")
            return False

    def backup_directory(self, source_dir: Path, output_path: Path, tar_name: str) -> bool:
        """
        Backup directory using tar compression.

        Args:
            source_dir: Source directory to backup
            output_path: Path to save tar archive
            tar_name: Name of tar file

        Returns:
            True if successful, False otherwise
        """
        if not source_dir.exists():
            logger.warning(f"Directory not found, skipping: {source_dir}")
            return True
        
        tar_file = output_path / tar_name
        
        try:
            logger.info(f"Backing up {tar_name}...")
            with tarfile.open(tar_file, 'w:gz') as tar:
                tar.add(source_dir, arcname=source_dir.name)
            logger.info(f"Backup saved: {tar_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to backup {tar_name}: {e}")
            return False

    def create_backup(
        self,
        remote_path: str,
        backup_database: bool = False,
        backup_raw_data: bool = False,
        backup_processed_data: bool = False,
        backup_media: bool = False,
    ) -> Tuple[bool, str]:
        """
        Create backup with selected components.

        Args:
            remote_path: Remote path to store backup
            backup_database: Backup database
            backup_raw_data: Backup raw data directory
            backup_processed_data: Backup processed data directory
            backup_media: Backup media directory

        Returns:
            Tuple of (success, backup_id)
        """
        # Validate that at least one component is selected
        if not any([backup_database, backup_raw_data, backup_processed_data, backup_media]):
            logger.error("Please select at least one component to backup (--database, --raw-data, --processed-data, --media)")
            return False, ""
        
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
        
        # Use local temp directory for creating backups
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            components = []
            
            # Backup database
            if backup_database:
                if self.backup_database(temp_dir):
                    db_file = temp_dir / 'database.sql'
                    if storage.upload_file(db_file, f"{remote_backup_dir}/database.sql"):
                        components.append('database')
                    else:
                        logger.warning("Database upload failed, continuing...")
                else:
                    logger.warning("Database backup failed, continuing...")
            
            # Backup raw data
            if backup_raw_data:
                if self.backup_directory(self.raw_data_dir, temp_dir, 'raw_data.tar.gz'):
                    tar_file = temp_dir / 'raw_data.tar.gz'
                    if storage.upload_file(tar_file, f"{remote_backup_dir}/raw_data.tar.gz"):
                        components.append('raw_data')
                    else:
                        logger.warning("Raw data upload failed, continuing...")
                else:
                    logger.warning("Raw data backup failed, continuing...")
            
            # Backup processed data
            if backup_processed_data:
                if self.backup_directory(self.processed_data_dir, temp_dir, 'processed_data.tar.gz'):
                    tar_file = temp_dir / 'processed_data.tar.gz'
                    if storage.upload_file(tar_file, f"{remote_backup_dir}/processed_data.tar.gz"):
                        components.append('processed_data')
                    else:
                        logger.warning("Processed data upload failed, continuing...")
                else:
                    logger.warning("Processed data backup failed, continuing...")
            
            # Backup media
            if backup_media:
                if self.backup_directory(self.media_dir, temp_dir, 'media.tar.gz'):
                    tar_file = temp_dir / 'media.tar.gz'
                    if storage.upload_file(tar_file, f"{remote_backup_dir}/media.tar.gz"):
                        components.append('media')
                    else:
                        logger.warning("Media upload failed, continuing...")
                else:
                    logger.warning("Media backup failed, continuing...")
            
            # Create and upload metadata
            if components:
                metadata = self._create_backup_metadata(backup_id, components)
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
                logger.info(f"  Components: {', '.join(components)}")
                return True, backup_id
            else:
                # Clean up empty backup directory
                storage.delete_dir(remote_backup_dir)
                logger.error("No backup components were successful")
                return False, ""

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

    def restore_backup(
        self,
        remote_path: str,
        backup_id: Optional[str] = None,
        restore_database: bool = True,
        restore_raw_data: bool = True,
        restore_processed_data: bool = True,
        restore_media: bool = True,
    ) -> bool:
        """
        Restore from backup.

        Args:
            remote_path: Remote path where backups are stored
            backup_id: Specific backup ID to restore (latest if not specified)
            restore_database: Restore database
            restore_raw_data: Restore raw data
            restore_processed_data: Restore processed data
            restore_media: Restore media

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
                logger.info(f"Components: {', '.join(metadata['components'])}")
            except Exception:
                pass
        
        success = True
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            
            # Restore database
            if restore_database and storage.exists(f"{remote_backup_dir}/database.sql"):
                db_file = temp_dir / 'database.sql'
                if storage.download_file(f"{remote_backup_dir}/database.sql", db_file):
                    if not self._restore_database(db_file):
                        success = False
                else:
                    success = False
            
            # Restore raw data
            if restore_raw_data and storage.exists(f"{remote_backup_dir}/raw_data.tar.gz"):
                tar_file = temp_dir / 'raw_data.tar.gz'
                if storage.download_file(f"{remote_backup_dir}/raw_data.tar.gz", tar_file):
                    if not self._restore_directory(tar_file, self.raw_data_dir):
                        success = False
                else:
                    success = False
            
            # Restore processed data
            if restore_processed_data and storage.exists(f"{remote_backup_dir}/processed_data.tar.gz"):
                tar_file = temp_dir / 'processed_data.tar.gz'
                if storage.download_file(f"{remote_backup_dir}/processed_data.tar.gz", tar_file):
                    if not self._restore_directory(tar_file, self.processed_data_dir):
                        success = False
                else:
                    success = False
            
            # Restore media
            if restore_media and storage.exists(f"{remote_backup_dir}/media.tar.gz"):
                tar_file = temp_dir / 'media.tar.gz'
                if storage.download_file(f"{remote_backup_dir}/media.tar.gz", tar_file):
                    if not self._restore_directory(tar_file, self.media_dir):
                        success = False
                else:
                    success = False
        
        if success:
            logger.info("✓ Restore completed successfully")
        else:
            logger.error("✗ Restore completed with errors")
        
        return success

    def _restore_database(self, backup_file: Path) -> bool:
        """
        Restore PostgreSQL database.

        Args:
            backup_file: Path to database dump file

        Returns:
            True if successful, False otherwise
        """
        logger.info("Restoring database...")
        
        try:
            env = os.environ.copy()
            env['PGPASSWORD'] = self.db_config['password']
            
            cmd = [
                'psql',
                '-h', self.db_config['host'],
                '-p', self.db_config['port'],
                '-U', self.db_config['user'],
                '-d', self.db_config['name'],
                '-f', str(backup_file),
            ]
            
            result = subprocess.run(
                cmd,
                env=env,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3600
            )
            
            if result.returncode != 0:
                logger.error(f"psql restore failed: {result.stderr}")
                return False
            
            logger.info("Database restored successfully")
            return True
            
        except FileNotFoundError:
            logger.error("psql not found. Install PostgreSQL client tools.")
            return False
        except Exception as e:
            logger.error(f"Failed to restore database: {e}")
            return False

    def _restore_directory(self, tar_file: Path, target_dir: Path) -> bool:
        """
        Restore directory from tar archive.

        Args:
            tar_file: Path to tar archive
            target_dir: Target directory to restore to

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Restoring {target_dir.name}...")
        
        try:
            # Remove existing directory
            if target_dir.exists():
                shutil.rmtree(target_dir)
            
            # Create parent directory
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            
            # Extract tar file
            with tarfile.open(tar_file, 'r:gz') as tar:
                tar.extractall(path=target_dir.parent)
            
            logger.info(f"Restored: {target_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore {target_dir.name}: {e}")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Django App Backup and Restore Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Backup command
    backup_parser = subparsers.add_parser('backup', help='Create backup')
    backup_parser.add_argument('--database', action='store_true', help='Backup PostgreSQL database')
    backup_parser.add_argument('--raw-data', action='store_true', help='Backup raw data directory')
    backup_parser.add_argument('--processed-data', action='store_true', help='Backup processed data directory')
    backup_parser.add_argument('--media', action='store_true', help='Backup media directory')
    backup_parser.add_argument('--ip', default='localhost', help='Remote server IP address (default: localhost)')
    backup_parser.add_argument('--remote-path', required=True, help='Remote path to store backup')
    backup_parser.add_argument('--ssh-user', default='root', help='SSH username (default: root)')
    backup_parser.add_argument('--ssh-key', help='Path to SSH private key (default: password auth)')
    backup_parser.add_argument('--ssh-port', type=int, default=22, help='SSH port (default: 22)')
    
    # Restore command
    restore_parser = subparsers.add_parser('restore', help='Restore from backup')
    restore_parser.add_argument('--ip', default='localhost', help='Remote server IP address (default: localhost)')
    restore_parser.add_argument('--remote-path', required=True, help='Remote path where backups are stored')
    restore_parser.add_argument('--backup-id', help='Specific backup ID to restore (latest if not specified)')
    restore_parser.add_argument('--database', action='store_true', default=True, help='Restore database')
    restore_parser.add_argument('--raw-data', action='store_true', default=True, help='Restore raw data')
    restore_parser.add_argument('--processed-data', action='store_true', default=True, help='Restore processed data')
    restore_parser.add_argument('--media', action='store_true', default=True, help='Restore media')
    restore_parser.add_argument('--skip-database', action='store_false', dest='database', help='Skip database restore')
    restore_parser.add_argument('--skip-raw-data', action='store_false', dest='raw_data', help='Skip raw data restore')
    restore_parser.add_argument('--skip-processed-data', action='store_false', dest='processed_data', help='Skip processed data restore')
    restore_parser.add_argument('--skip-media', action='store_false', dest='media', help='Skip media restore')
    restore_parser.add_argument('--ssh-user', default='root', help='SSH username (default: root)')
    restore_parser.add_argument('--ssh-key', help='Path to SSH private key (default: password auth)')
    restore_parser.add_argument('--ssh-port', type=int, default=22, help='SSH port (default: 22)')
    
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
    
    manager = DjangoBackupManager(
        ip=args.ip,
        ssh_user=args.ssh_user,
        ssh_key=args.ssh_key,
        ssh_port=args.ssh_port,
    )
    
    if args.command == 'backup':
        success, backup_id = manager.create_backup(
            args.remote_path,
            backup_database=args.database,
            backup_raw_data=args.raw_data,
            backup_processed_data=args.processed_data,
            backup_media=args.media,
        )
        sys.exit(0 if success else 1)
    
    elif args.command == 'restore':
        success = manager.restore_backup(
            args.remote_path,
            backup_id=args.backup_id,
            restore_database=args.database,
            restore_raw_data=args.raw_data,
            restore_processed_data=args.processed_data,
            restore_media=args.media,
        )
        sys.exit(0 if success else 1)
    
    elif args.command == 'list':
        backups = manager.list_backups(args.remote_path)
        if backups:
            logger.info("Available backups:")
            for i, backup in enumerate(backups, 1):
                logger.info(f"\n{i}. {backup['backup_id']}")
                logger.info(f"   Timestamp: {backup['timestamp']}")
                logger.info(f"   Components: {', '.join(backup['components'])}")
        else:
            logger.info("No backups found")


if __name__ == '__main__':
    main()
