"""
Test settings for CT Upload Platform
Uses SQLite for testing without requiring PostgreSQL
"""

from pathlib import Path
from ct_upload_platform.settings import *

# Use SQLite for testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',  # In-memory database for tests
    }
}

# Disable password hashing for faster tests (not for production!)
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Disable migrations for faster test startup
class DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = DisableMigrations()

# Point GDPR config at the copy inside the Docker mount
GDPR_STRICT_CONFIG_PATH = '/app/GDPR-strict.json'

DICOM_ENRICHMENT_ENABLED = True
