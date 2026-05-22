"""
Celery configuration for ct_upload_platform.
"""

import os
from celery import Celery

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ct_upload_platform.settings')

app = Celery('ct_upload_platform')

# Load configuration from Django settings, all CELERY-prefixed settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all registered Django apps
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
