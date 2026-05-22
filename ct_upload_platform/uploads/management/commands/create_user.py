"""
Django management command to create a user with a random password and send the password via email.
"""

import secrets
import string
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings


class Command(BaseCommand):
    """Create a user with a random password and send credentials via email."""
    
    help = 'Create a user with a random password and send credentials via email'
    
    def add_arguments(self, parser):
        """Define command arguments."""
        parser.add_argument(
            '--username',
            type=str,
            required=True,
            help='Username for the new user'
        )
        parser.add_argument(
            '--email',
            type=str,
            required=True,
            help='Email address for the new user'
        )
        parser.add_argument(
            '--first-name',
            type=str,
            default='',
            help='First name of the user (optional)'
        )
        parser.add_argument(
            '--last-name',
            type=str,
            default='',
            help='Last name of the user (optional)'
        )
        parser.add_argument(
            '--is-staff',
            action='store_true',
            help='Grant staff privileges to the user'
        )
        parser.add_argument(
            '--is-superuser',
            action='store_true',
            help='Grant superuser privileges to the user'
        )
        parser.add_argument(
            '--no-email',
            action='store_true',
            help='Do not send email (only print password)'
        )
        parser.add_argument(
            '--password-length',
            type=int,
            default=16,
            help='Length of the generated password (default: 16)'
        )
    
    def _generate_password(self, length=16):
        """Generate a random password."""
        characters = string.ascii_letters + string.digits + string.punctuation
        # Remove ambiguous characters
        characters = characters.replace('l', '').replace('O', '').replace('0', '')
        password = ''.join(secrets.choice(characters) for _ in range(length))
        return password
    
    def _send_email(self, user, password):
        """Send user credentials via email."""
        subject = 'Your CT Upload Platform Account'
        
        message = f"""
Hello {user.first_name or user.username},

Your account has been created on the CT Upload Platform.

Login Details:
- Username: {user.username}
- Email: {user.email}
- Password: {password}
- Login URL: {settings.ALLOWED_HOSTS[0]}/login/

Please change your password after your first login for security.

Best regards,
CT Upload Platform Team
"""
        
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            return True
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'Failed to send email: {e}')
            )
            return False
    
    def handle(self, *args, **options):
        """Execute the command."""
        username = options['username']
        email = options['email']
        first_name = options.get('first_name', '')
        last_name = options.get('last_name', '')
        is_staff = options.get('is_staff', False)
        is_superuser = options.get('is_superuser', False)
        no_email = options.get('no_email', False)
        password_length = options.get('password_length', 16)
        
        # Check if user already exists
        if User.objects.filter(username=username).exists():
            raise CommandError(f'User with username "{username}" already exists')
        
        if User.objects.filter(email=email).exists():
            raise CommandError(f'User with email "{email}" already exists')
        
        # Generate random password
        password = self._generate_password(password_length)
        
        # Create user
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            
            # Set staff and superuser flags if requested
            if is_staff:
                user.is_staff = True
            if is_superuser:
                user.is_superuser = True
                user.is_staff = True  # Superuser should also be staff
            
            user.save()
            
            self.stdout.write(
                self.style.SUCCESS(f'✓ User "{username}" created successfully')
            )
            self.stdout.write(f'  Email: {email}')
            self.stdout.write(f'  Generated Password: {password}')
            
            if is_staff:
                self.stdout.write(f'  Staff: Yes')
            if is_superuser:
                self.stdout.write(f'  Superuser: Yes')
            
            # Send email
            if not no_email:
                if self._send_email(user, password):
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ Email sent to {email}')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠ User created but email could not be sent. '
                            f'Share the password manually: {password}'
                        )
                    )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'⚠ Email not sent (--no-email flag used). '
                        f'Share the password manually: {password}'
                    )
                )
        
        except Exception as e:
            raise CommandError(f'Error creating user: {e}')
