# Backup & Restore Guide

Quick reference for using the backup scripts with remote server support via SSH.

## Django App Backup/Restore

The Django backup script allows selective backup of database, raw data, processed data, and media files to local or remote servers.

### Installation

Ensure PostgreSQL client tools are installed:
```bash
# macOS
brew install postgresql

# Linux (Ubuntu/Debian)
sudo apt-get install postgresql-client
```

### Backup Examples

```bash
# Backup database and raw data locally
python backup_django.py backup --database --raw-data --ip localhost --remote-path /backups/django

# Backup to remote server via SSH
python backup_django.py backup --database --raw-data --processed-data --media \
    --ip 192.168.1.100 --remote-path /backups/django \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa

# Backup with password auth (prompts for password)
python backup_django.py backup --database --raw-data \
    --ip 192.168.1.100 --remote-path /backups/django \
    --ssh-user backup

# Backup everything to different server
python backup_django.py backup --database --raw-data --processed-data --media \
    --ip remote.example.com --remote-path /mnt/backups/django \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa --ssh-port 2222
```

### Restore Examples

```bash
# Restore everything from latest local backup
python backup_django.py restore --ip localhost --remote-path /backups/django

# Restore from remote server
python backup_django.py restore \
    --ip 192.168.1.100 --remote-path /backups/django \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa

# Restore specific backup
python backup_django.py restore \
    --ip 192.168.1.100 --remote-path /backups/django \
    --backup-id backup_20260227_143022 \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa

# Restore only database (skip other components)
python backup_django.py restore \
    --ip localhost --remote-path /backups/django \
    --skip-raw-data --skip-processed-data --skip-media

# Restore specific components
python backup_django.py restore \
    --ip 192.168.1.100 --remote-path /backups/django \
    --database --raw-data --skip-processed-data --skip-media \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa
```

### List Backups

```bash
# List local backups
python backup_django.py list --ip localhost --remote-path /backups/django

# List remote backups
python backup_django.py list \
    --ip 192.168.1.100 --remote-path /backups/django \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa
```

### Database Configuration

The script uses environment variables for database connection:

```bash
export DB_NAME=ct_upload_platform
export DB_USER=postgres
export DB_PASSWORD=your_password
export DB_HOST=localhost
export DB_PORT=5432
```

## Orthanc Server Backup/Restore

The Orthanc backup script backs up everything from the Orthanc server to local or remote locations.

### Installation

Ensure Docker is installed if using Docker mode:
```bash
# Docker must be installed and running
docker --version
```

SSH tools are required for remote operations (usually pre-installed).

### Backup Examples

```bash
# Backup Orthanc locally
python backup_orthanc.py backup --ip localhost --remote-path /backups/orthanc

# Backup from Docker container locally
python backup_orthanc.py backup --ip localhost --remote-path /backups/orthanc \
    --use-docker

# Backup from Docker to remote server
python backup_orthanc.py backup --ip localhost --remote-path /mnt/backups/orthanc \
    --use-docker --container-name ct_upload_orthanc

# Backup with custom container name
python backup_orthanc.py backup --ip localhost --remote-path /backups \
    --use-docker --container-name my_orthanc_prod

# Backup to remote server via SSH
python backup_orthanc.py backup \
    --ip 192.168.1.100 --remote-path /backups/orthanc \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa \
    --use-docker --container-name ct_upload_orthanc

# Backup to remote NFS with custom SSH port
python backup_orthanc.py backup \
    --ip backup.example.com --remote-path /mnt/nfs/orthanc-backups \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa --ssh-port 2222 \
    --use-docker
```

### Restore Examples

```bash
# Restore from latest local backup
python backup_orthanc.py restore --ip localhost --remote-path /backups/orthanc

# Restore from Docker container
python backup_orthanc.py restore --ip localhost --remote-path /backups/orthanc \
    --use-docker

# Restore from latest remote backup
python backup_orthanc.py restore \
    --ip 192.168.1.100 --remote-path /backups/orthanc \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa \
    --use-docker

# Restore specific backup
python backup_orthanc.py restore \
    --ip 192.168.1.100 --remote-path /backups/orthanc \
    --backup-id backup_20260227_143022 \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa \
    --use-docker

# Restore without accessibility check
python backup_orthanc.py restore \
    --ip 192.168.1.100 --remote-path /backups/orthanc \
    --use-docker --skip-validation \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa
```

### List Backups

```bash
# List local backups
python backup_orthanc.py list --ip localhost --remote-path /backups/orthanc

# List remote backups
python backup_orthanc.py list \
    --ip 192.168.1.100 --remote-path /backups/orthanc \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa
```

## Backup Strategy

### Daily Backups

```bash
# Create daily cron job (Django) - backup to remote server
0 2 * * * cd /app && python backup_django.py backup --database --raw-data --media \
    --ip 192.168.1.100 --remote-path /backups/django \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa >> /var/log/django_backup.log 2>&1

# Create daily cron job (Orthanc) - backup to remote server
0 3 * * * cd /app && python backup_orthanc.py backup \
    --ip 192.168.1.100 --remote-path /backups/orthanc \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa \
    --use-docker >> /var/log/orthanc_backup.log 2>&1
```

### Incremental Backups

Create multiple backup sets at different times:
```bash
# Morning full backup to local
python backup_django.py backup --database --raw-data --media \
    --ip localhost --remote-path /backups/django/full

# Evening backup to remote (database only, faster)
python backup_django.py backup --database \
    --ip 192.168.1.100 --remote-path /backups/django/incremental \
    --ssh-user backup --ssh-key ~/.ssh/id_rsa
```

### Retention Policy

```bash
# Keep last 30 days of backups (example)
# On remote server via SSH
ssh backup@192.168.1.100 'find /backups/django -type d -mtime +30 -exec rm -rf {} \;'
ssh backup@192.168.1.100 'find /backups/orthanc -type d -mtime +30 -exec rm -rf {} \;'
```

## SSH Configuration

### Key-based Authentication (Recommended)

```bash
# Generate SSH key (run once)
ssh-keygen -t ed25519 -f ~/.ssh/backup_key -N ""

# Copy public key to remote server
ssh-copy-id -i ~/.ssh/backup_key -p 22 backup@192.168.1.100

# Use in backup script
python backup_django.py backup --database \
    --ip 192.168.1.100 --remote-path /backups/django \
    --ssh-user backup --ssh-key ~/.ssh/backup_key
```

### SSH Config File

Create `~/.ssh/config`:
```
Host backup-server
    HostName 192.168.1.100
    User backup
    IdentityFile ~/.ssh/backup_key
    Port 22
    IdentitiesOnly yes
```

Then use:
```bash
python backup_django.py backup --database \
    --ip backup-server --remote-path /backups/django
```

### Password Authentication

If you can't use keys, SSH will prompt for password:
```bash
python backup_django.py backup --database \
    --ip 192.168.1.100 --remote-path /backups/django \
    --ssh-user backup
```

## Backup Structure

Each backup creates a directory with:
- `database.sql` - PostgreSQL dump
- `raw_data.tar.gz` - Raw data directory
- `processed_data.tar.gz` - Processed data directory
- `media.tar.gz` - Media files
- `orthanc_data.tar.gz` - Orthanc complete data
- `metadata.json` - Backup metadata and timestamp

Example:
```
/backups/django/
├── backup_20260227_140000/
│   ├── metadata.json
│   ├── database.sql
│   ├── raw_data.tar.gz
│   └── media.tar.gz
├── backup_20260227_150000/
│   └── ...
```

## Troubleshooting

### SSH Connection Issues

```bash
# Test SSH connection
ssh -i ~/.ssh/id_rsa -v backup@192.168.1.100 "echo 'Connected'"

# Check SSH key permissions
chmod 600 ~/.ssh/id_rsa
chmod 644 ~/.ssh/id_rsa.pub

# Verify remote server SSH key
ssh-keyscan 192.168.1.100 >> ~/.ssh/known_hosts
```

### PostgreSQL Connection Issues

```bash
# Test connection
psql -h localhost -U postgres -d ct_upload_platform -c "SELECT 1"

# Verify credentials
echo $DB_PASSWORD  # Should match actual password
```

### Docker Issues

```bash
# Check container status
docker ps | grep ct_upload

# View container logs
docker logs ct_upload_orthanc

# Restart container
docker restart ct_upload_orthanc
```

### Remote Server Permissions

```bash
# On remote server, ensure backup user can write to backup directory
sudo chown backup:backup /backups
sudo chmod 755 /backups

# Or use sudo if needed
sudo mkdir -p /backups/django
sudo chown backup:backup /backups/django
```

### Storage Space

```bash
# Check backup sizes
du -sh /backups/django/*
du -sh /backups/orthanc/*

# Check available space
df -h /backups

# Check remote server space via SSH
ssh backup@192.168.1.100 "df -h /backups"
```

## Requirements

### Python Modules

Both scripts use only Python standard library:
- `argparse` - Command-line arguments
- `os`, `sys` - System operations
- `pathlib` - Path handling
- `subprocess` - External command execution
- `tarfile` - Compression
- `json` - Metadata
- `logging` - Logging
- `shutil` - File operations
- `datetime` - Timestamps
- `tempfile` - Temporary directories

### System Tools

**Django Backup:**
- `pg_dump` - PostgreSQL client (for backup)
- `psql` - PostgreSQL client (for restore)
- `ssh` / `scp` - For remote operations
- `tar`, `gzip` - Archive creation (usually pre-installed)

**Orthanc Backup:**
- `docker` - if using `--use-docker` flag
- `ssh` / `scp` - For remote operations
- `tar`, `gzip` - Archive creation

## Performance Tips

1. **Remote transfers**: Large backups over SSH can be slow. Consider:
   - Running backups during off-hours
   - Using high-speed networks
   - Compression is enabled by default (reduces bandwidth 60-80%)

2. **Database backup time**: Depends on database size. Large databases may take 30+ minutes.

3. **SSH performance**: Key-based auth is faster than password auth for multiple operations.

4. **Scheduling**: Run backups during low-usage periods.

5. **Parallel backups**: Don't run multiple backups simultaneously on same system to avoid resource contention.

## Security Considerations

1. **SSH Key Protection**: Keep SSH keys secure
   - Use key-based auth, not password
   - Restrict permissions: `chmod 600 ~/.ssh/id_rsa`
   - Consider using SSH key passphrases

2. **Backup Encryption**: Add encryption layer for sensitive data
   ```bash
   # Example: encrypt with GPG after backup
   gpg --encrypt --recipient backup-key backup.tar.gz
   ```

3. **Access Control**: Restrict backup directory permissions
   ```bash
   chmod 700 /backups
   chown backup:backup /backups
   ```

4. **Network Security**: Use VPN or private networks for backup transfers

5. **Verification**: Periodically test restore procedures to ensure backups are valid

## Examples with Real Paths

```bash
# Full system backup to NFS mount on remote server
python backup_django.py backup --database --raw-data --processed-data --media \
  --ip nfs-server.local --remote-path /mnt/nfs/backup-server/django-backups \
  --ssh-user backup --ssh-key ~/.ssh/nfs_backup_key

python backup_orthanc.py backup \
  --ip nfs-server.local --remote-path /mnt/nfs/backup-server/orthanc-backups \
  --ssh-user backup --ssh-key ~/.ssh/nfs_backup_key \
  --use-docker

# List all backups
python backup_django.py list \
  --ip nfs-server.local --remote-path /mnt/nfs/backup-server/django-backups \
  --ssh-user backup --ssh-key ~/.ssh/nfs_backup_key

python backup_orthanc.py list \
  --ip nfs-server.local --remote-path /mnt/nfs/backup-server/orthanc-backups \
  --ssh-user backup --ssh-key ~/.ssh/nfs_backup_key

# Restore from specific date
python backup_django.py restore --backup-id backup_20260220_020000 \
  --ip nfs-server.local --remote-path /mnt/nfs/backup-server/django-backups \
  --ssh-user backup --ssh-key ~/.ssh/nfs_backup_key

python backup_orthanc.py restore --backup-id backup_20260220_030000 \
  --ip nfs-server.local --remote-path /mnt/nfs/backup-server/orthanc-backups \
  --ssh-user backup --ssh-key ~/.ssh/nfs_backup_key \
  --use-docker
```
