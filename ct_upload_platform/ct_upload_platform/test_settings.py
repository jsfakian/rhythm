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

# Pin independently of whatever SUPERUSER_EMAIL happens to be in the local .env,
# so signup-notification tests are deterministic.
ADMIN_NOTIFICATION_EMAIL = 'admin-notifications@example.com'

# Never talk to a real broker from tests. settings.py reads REDIS_URL from
# .env, which on the server is the *production* Redis (localhost:6381): any
# view test that calls .delay() used to enqueue a real process_upload_job
# task there, which the production worker then picked up and retried until
# it gave up (UploadJob.DoesNotExist). The in-memory transport keeps every
# .delay() inside the test process.
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
