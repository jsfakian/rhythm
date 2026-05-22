"""
ASGI config for ct_upload_platform project.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ct_upload_platform.settings')

application = get_asgi_application()
