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

# Never write test files into the real data directories. MEDIA_ROOT,
# RAW_DATA_DIR and PROCESSED_DATA_DIR default to folders inside the checkout,
# which on the server is the *production* bind mount: tests that attach a
# study-set ZIP used to leave RHY-SITE-HEADTRAUMA-UNK-PB-G1-000001_<suffix>.zip
# files in production media/examination_study_sets/ (publicly served under
# /media/), and failed outright anywhere media/ was not writable. Each test
# run gets its own throwaway tree instead, removed when the process exits.
import atexit  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

_TEST_FILES_ROOT = Path(tempfile.mkdtemp(prefix="ct_upload_test_files_"))
atexit.register(shutil.rmtree, _TEST_FILES_ROOT, ignore_errors=True)
MEDIA_ROOT = _TEST_FILES_ROOT / "media"
RAW_DATA_DIR = _TEST_FILES_ROOT / "raw_data"
PROCESSED_DATA_DIR = _TEST_FILES_ROOT / "processed_data"
for _test_dir in (MEDIA_ROOT, RAW_DATA_DIR, PROCESSED_DATA_DIR):
    _test_dir.mkdir()
