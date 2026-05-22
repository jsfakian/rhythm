"""
Management command to create or rotate an API token for a user.
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = 'Create or rotate an API token for a user'

    def add_arguments(self, parser):
        parser.add_argument(
            'username',
            type=str,
            help='Username of the user to create/rotate token for'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force rotate existing token instead of showing it',
        )

    def handle(self, *args, **options):
        username = options['username']
        force_rotate = options.get('force', False)

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'User "{username}" does not exist')

        # Try to get existing token
        try:
            token = Token.objects.get(user=user)
            if force_rotate:
                # Delete the old token and create a new one
                token.delete()
                token = Token.objects.create(user=user)
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ Token rotated for user "{username}":\n{token.key}'
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✓ Existing token for user "{username}":\n{token.key}\n'
                        f'  Use --force to rotate the token'
                    )
                )
        except Token.DoesNotExist:
            # Create a new token
            token = Token.objects.create(user=user)
            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ Token created for user "{username}":\n{token.key}'
                )
            )
