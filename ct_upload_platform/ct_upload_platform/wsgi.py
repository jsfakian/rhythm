"""
WSGI config for ct_upload_platform project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ct_upload_platform.settings')

application = get_wsgi_application()
