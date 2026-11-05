"""
Test settings for `make test`: the regular test settings, but against the
throwaway `test-db` PostgreSQL service (docker-compose profile "test")
instead of in-memory SQLite, so tests exercise the production database
engine without ever touching the production database.

Migrations stay disabled (inherited DisableMigrations): tables are created
straight from the models, which also sidesteps the known duplicate-CreateModel
problem in uploads/migrations 0018-0025 on a brand-new database.
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .test_settings import *  # noqa: F401,F403

_TEST_DB_HOST = os.environ.get('TEST_DB_HOST', 'test-db')

# Hard guard: refuse to run tests against the production database service.
if _TEST_DB_HOST in {'db', 'ct_upload_db'}:
    raise ImproperlyConfigured(
        f"TEST_DB_HOST={_TEST_DB_HOST!r} is the production database. "
        "Tests must use the 'test-db' service (make test)."
    )

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('TEST_DB_NAME', 'ct_upload_test'),
        'USER': os.environ.get('TEST_DB_USER', 'test'),
        'PASSWORD': '',
        'HOST': _TEST_DB_HOST,
        'PORT': os.environ.get('TEST_DB_PORT', '5432'),
        'TEST': {'NAME': 'test_ct_upload'},
    }
}
