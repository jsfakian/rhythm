"""
Management command to create or update the platform superuser from .env variables.

Usage:
    python manage.py ensure_superuser
    docker-compose exec web python manage.py ensure_superuser

Required environment variables:
    SUPERUSER_USERNAME   — login username (default: admin)
    SUPERUSER_EMAIL      — email address
    SUPERUSER_PASSWORD   — password (required; command aborts if unset)
"""

import os

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Create or update the platform superuser from environment variables (idempotent)'

    def handle(self, *args, **options):
        username = os.environ.get('SUPERUSER_USERNAME', 'admin').strip()
        email = os.environ.get('SUPERUSER_EMAIL', '').strip()
        password = os.environ.get('SUPERUSER_PASSWORD', '').strip()

        if not password:
            self.stderr.write(
                self.style.ERROR(
                    'SUPERUSER_PASSWORD is not set in the environment — aborting.'
                )
            )
            return

        user, created = User.objects.get_or_create(username=username)
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Superuser '{username}' created.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Superuser '{username}' updated.")
            )
