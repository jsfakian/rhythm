"""
Management command to create a demo user (idempotent).

Usage:
    python manage.py ensure_demo_user
    docker-compose exec web python manage.py ensure_demo_user
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token


DEMO_USERNAME = 'demo'
DEMO_EMAIL = 'demo@example.com'
DEMO_PASSWORD = 'changeme123!!'


class Command(BaseCommand):
    help = 'Create the demo user (idempotent — safe to run multiple times)'

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={
                'email': DEMO_EMAIL,
                'first_name': 'Demo',
                'last_name': 'User',
            },
        )

        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            Token.objects.get_or_create(user=user)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Demo user '{DEMO_USERNAME}' created (password: {DEMO_PASSWORD})"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Demo user '{DEMO_USERNAME}' already exists — skipping."
                )
            )
