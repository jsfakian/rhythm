"""
Django settings for ct_upload_platform project.
"""

import os
from pathlib import Path
import environ

# Initialize environment
env = environ.Env(
    DEBUG=(bool, False)
)

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
environ_file = BASE_DIR / '.env'
if environ_file.exists():
    environ.Env.read_env(environ_file)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='django-insecure-your-secret-key-change-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG', default=False)

ALLOWED_HOSTS = env('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

CSRF_TRUSTED_ORIGINS = env('CSRF_TRUSTED_ORIGINS', default='').split(',') if env('CSRF_TRUSTED_ORIGINS', default='') else []

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'uploads',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'ct_upload_platform.middleware.IPWhitelistMiddleware',
]

ROOT_URLCONF = 'ct_upload_platform.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ct_upload_platform.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DB_NAME', default='ct_upload_platform'),
        'USER': env('DB_USER', default='postgres'),
        'PASSWORD': env('DB_PASSWORD', default='password'),
        'HOST': env('DB_HOST', default='localhost'),
        'PORT': env('DB_PORT', default='5432'),
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'uploads.auth.BearerTokenAuthentication',  # Supports both Bearer and Token formats
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# Celery Configuration
CELERY_BROKER_URL = env('REDIS_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = env('REDIS_URL', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes

# Orthanc Configuration
# Orthanc is the authoritative DICOM storage. Django pushes cleaned DICOM files to Orthanc via STOW-RS.
ORTHANC_BASE_URL = env('ORTHANC_BASE_URL', default='http://orthanc:8042')
ORTHANC_USERNAME = env('ORTHANC_USERNAME', default='orthanc')
ORTHANC_PASSWORD = env('ORTHANC_PASSWORD', default='orthanc')

# Temporary upload directory for tar extraction
TEMP_UPLOAD_DIR = env('TEMP_UPLOAD_DIR', default=None)  # None means system temp directory

# Raw data directory for storing uploaded tar files organized by user
RAW_DATA_DIR = BASE_DIR / 'raw_data'

# Processed data directory for storing extracted and validated tar contents
PROCESSED_DATA_DIR = BASE_DIR / 'processed_data'

# Media files configuration (for annotations and other uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Custom application settings (overridable via environment)
MAX_UPLOAD_SIZE_MB = env.int('MAX_UPLOAD_SIZE_MB', default=2048)
MAX_IMAGES_PER_UPLOAD = env.int('MAX_IMAGES_PER_UPLOAD', default=10000)

# GDPR-Strict Configuration
# Path to GDPR-strict.json defining anonymization validation rules
GDPR_STRICT_CONFIG_PATH = env('GDPR_STRICT_CONFIG_PATH', default=str(BASE_DIR.parent / 'GDPR-strict.json'))
# Enable OCR-based pixel scanning for detecting visible identifiers (experimental)
GDPR_PIXEL_SCAN_ENABLED = env.bool('GDPR_PIXEL_SCAN_ENABLED', default=False)
# OCR confidence threshold (0-100) for flagging potential text
GDPR_PIXEL_SCAN_CONFIDENCE_THRESHOLD = env.int('GDPR_PIXEL_SCAN_CONFIDENCE_THRESHOLD', default=80)

MANIFEST_SCHEMA_VERSION = env('MANIFEST_SCHEMA_VERSION', default='1.0')
UPLOAD_TOKEN_EXPIRY_DAYS = env.int('UPLOAD_TOKEN_EXPIRY_DAYS', default=90)

# IP Whitelist Configuration
# Format: comma-separated IPs and/or CIDR ranges
# Example: "192.168.1.1,10.0.0.0/8,127.0.0.1"
# If not set, all IPs are allowed
IP_WHITELIST = env('IP_WHITELIST', default=None)

# Email Configuration
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='localhost')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='your-email@example.com')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='your-password')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@ct-upload-platform.local')

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'

# Token Expiration
TOKEN_EXPIRY_DAYS = env.int('TOKEN_EXPIRY_DAYS', default=30)

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': env('LOG_LEVEL', default='INFO'),
    },
}
