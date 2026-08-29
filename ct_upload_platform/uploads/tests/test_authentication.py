"""
Unit tests for authentication, access control, and user management.

Tests cover:
- IP whitelist middleware
- Login API endpoint
- User creation management command
- Token authentication and refresh
"""

import json
import pyotp
from django.contrib.auth.models import User
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.test.client import Client
from django.core.management import call_command
from django.core.mail import outbox
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from io import StringIO


def complete_mandatory_2fa_enrollment(client, username, password):
    """
    Log in via /api/v1/auth/login/ and complete the mandatory first-time 2FA
    enrollment it triggers, returning the final (authenticated) response.

    Every account is required to enroll in 2FA on its first login (see
    ``views.LoginView``/``Enroll2FAConfirmView``), so tests exercising the full
    login flow need to walk through enrollment rather than expecting a token
    straight from ``/api/v1/auth/login/``.
    """
    login_response = client.post('/api/v1/auth/login/', {
        'username': username,
        'password': password,
    }, format='json')
    assert login_response.json().get('requires_2fa_setup'), login_response.json()

    initiate_response = client.post('/api/v1/auth/enroll-2fa/initiate/', format='json')
    secret = initiate_response.json()['secret']
    code = pyotp.TOTP(secret).now()

    return client.post(
        '/api/v1/auth/enroll-2fa/confirm/', {'code': code}, format='json',
    )


class IPWhitelistMiddlewareTestCase(TestCase):
    """Test IP whitelist middleware functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        # Create a test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
    
    @override_settings(IP_WHITELIST=None)
    def test_no_whitelist_allows_all_ips(self):
        """When IP_WHITELIST is not set, all IPs should be allowed."""
        response = self.client.get('/login/', REMOTE_ADDR='192.168.1.100')
        # Should not get forbidden
        self.assertNotEqual(response.status_code, 403)
    
    @override_settings(IP_WHITELIST='192.168.1.0/24,10.0.0.0/8')
    def test_whitelist_allows_matching_ip(self):
        """Whitelisted IPs should be allowed."""
        response = self.client.get('/login/', REMOTE_ADDR='192.168.1.100')
        # Should not get forbidden
        self.assertNotEqual(response.status_code, 403)
    
    @override_settings(IP_WHITELIST='192.168.1.0/24,10.0.0.0/8')
    def test_whitelist_blocks_unmatched_ip(self):
        """Non-whitelisted IPs should be blocked with 403."""
        response = self.client.get('/login/', REMOTE_ADDR='172.16.0.100')
        # Should get forbidden
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Access denied', response.content)
    
    @override_settings(IP_WHITELIST='127.0.0.1')
    def test_whitelist_single_ip(self):
        """Single IP whitelist should work."""
        # Matching IP
        response = self.client.get('/login/', REMOTE_ADDR='127.0.0.1')
        self.assertNotEqual(response.status_code, 403)
        
        # Non-matching IP
        response = self.client.get('/login/', REMOTE_ADDR='127.0.0.2')
        self.assertEqual(response.status_code, 403)
    
    @override_settings(IP_WHITELIST='192.168.1.1,10.0.0.0/8')
    def test_whitelist_exempts_login_endpoint(self):
        """Login endpoint should be exempted from IP whitelist."""
        # /api/v1/auth/login/ should be accessible from any IP
        response = self.client.post(
            '/api/v1/auth/login/',
            data=json.dumps({'username': 'test', 'password': 'test'}),
            content_type='application/json',
            REMOTE_ADDR='172.16.0.100'
        )
        # Should not be forbidden (might be 401 for auth, but not 403 for IP)
        self.assertNotEqual(response.status_code, 403)
    
    @override_settings(IP_WHITELIST='10.0.0.0/8')
    def test_whitelist_with_x_forwarded_for_header(self):
        """Should check X-Forwarded-For header for proxied requests."""
        # Proxied request with correct IP
        response = self.client.get(
            '/',
            HTTP_X_FORWARDED_FOR='10.0.0.100, 192.168.1.1',
            REMOTE_ADDR='192.168.1.1'
        )
        self.assertNotEqual(response.status_code, 403)
        
        # Proxied request with incorrect IP
        response = self.client.get(
            '/',
            HTTP_X_FORWARDED_FOR='172.16.0.100, 192.168.1.1',
            REMOTE_ADDR='192.168.1.1'
        )
        self.assertEqual(response.status_code, 403)


class LoginAPITestCase(APITestCase):
    """Test login REST API endpoint."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='john.doe',
            password='SecurePass123!',
            email='john@example.com'
        )
        self.login_url = '/api/v1/auth/login/'
    
    def test_login_with_valid_credentials(self):
        """User should be able to login with correct credentials, then complete mandatory 2FA enrollment."""
        response = self.client.post(self.login_url, {
            'username': 'john.doe',
            'password': 'SecurePass123!'
        }, format='json')

        # 2FA is mandatory: a first-time login doesn't return a token yet.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'requires_2fa_setup': True})

        response = complete_mandatory_2fa_enrollment(self.client, 'john.doe', 'SecurePass123!')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check response contains expected fields
        self.assertIn('token', data)
        self.assertEqual(data['username'], 'john.doe')
        self.assertEqual(data['email'], 'john@example.com')
        self.assertFalse(data['is_staff'])
        self.assertIsNotNone(data['user_id'])

        # Token should be valid in the database
        token = Token.objects.get(key=data['token'])
        self.assertEqual(token.user, self.user)
    
    def test_login_with_invalid_password(self):
        """Login should fail with incorrect password."""
        response = self.client.post(self.login_url, {
            'username': 'john.doe',
            'password': 'WrongPassword'
        }, format='json')
        
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertIn('error', data)
        self.assertEqual(data['error'], 'Invalid username or password')
    
    def test_login_with_invalid_username(self):
        """Login should fail with non-existent username."""
        response = self.client.post(self.login_url, {
            'username': 'nonexistent.user',
            'password': 'SomePassword123!'
        }, format='json')
        
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertIn('error', data)
    
    def test_login_missing_username(self):
        """Login should fail when username is missing."""
        response = self.client.post(self.login_url, {
            'password': 'SecurePass123!'
        }, format='json')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('error', data)
    
    def test_login_missing_password(self):
        """Login should fail when password is missing."""
        response = self.client.post(self.login_url, {
            'username': 'john.doe'
        }, format='json')
        
        self.assertEqual(response.status_code, 400)
    
    def test_login_returns_token_with_full_user_info(self):
        """Login response should include complete user information."""
        # Create user with more details
        user = User.objects.create_user(
            username='jane.smith',
            password='Pass123!',
            email='jane@example.com',
            first_name='Jane',
            last_name='Smith',
        )
        user.is_staff = True
        user.save()

        response = complete_mandatory_2fa_enrollment(self.client, 'jane.smith', 'Pass123!')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['first_name'], 'Jane')
        self.assertEqual(data['last_name'], 'Smith')
        self.assertTrue(data['is_staff'])

    def test_token_can_be_used_for_api_access(self):
        """Token from login should work for API authentication."""
        # Get token (completing mandatory 2FA enrollment)
        login_response = complete_mandatory_2fa_enrollment(self.client, 'john.doe', 'SecurePass123!')

        token = login_response.json()['token']
        
        # Use token to access protected endpoint
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = self.client.get('/api/v1/uploads/')
        
        # Should get a successful response (not 401 Unauthorized)
        self.assertNotEqual(response.status_code, 401)
    
    def test_login_endpoint_accessible_without_auth(self):
        """Login endpoint should not require authentication."""
        # Don't set credentials
        response = self.client.post(self.login_url, {
            'username': 'john.doe',
            'password': 'SecurePass123!'
        }, format='json')
        
        # Should not get 401 Unauthorized
        self.assertNotEqual(response.status_code, 401)


class LoginPageTestCase(TestCase):
    """Test login page view."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
    
    def test_login_page_accessible(self):
        """Login page should be accessible."""
        response = self.client.get('/login/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Login', response.content)
    
    def test_authenticated_user_redirected_from_login(self):
        """Already logged-in users should be redirected from login page."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get('/login/')

        # Should be redirected
        self.assertEqual(response.status_code, 302)


class LogoutViewTestCase(TestCase):
    """Logging out must end the session and send the user back to /login/."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass123')

    def test_get_logout_redirects_to_login(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get('/logout/')
        self.assertRedirects(response, '/login/')

    def test_post_logout_redirects_to_login(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post('/logout/')
        self.assertRedirects(response, '/login/')

    def test_logout_ends_the_session(self):
        """After logout, a subsequent request to a protected page must bounce
        back to /login/ rather than staying authenticated."""
        self.client.login(username='testuser', password='testpass123')
        self.client.get('/logout/')

        response = self.client.get('/account/security/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))


class SessionTimeoutSettingsTestCase(TestCase):
    """The automatic-logout timeout is configured for 1 hour of inactivity."""

    def test_session_cookie_age_is_one_hour(self):
        from django.conf import settings
        self.assertEqual(settings.SESSION_COOKIE_AGE, 3600)

    def test_session_is_idle_based(self):
        """SESSION_SAVE_EVERY_REQUEST resets the countdown on activity, so the
        1-hour timeout is measured from the last request, not from login."""
        from django.conf import settings
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)


class CreateUserManagementCommandTestCase(TestCase):
    """Test create_user management command."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.stdout = StringIO()
        self.stderr = StringIO()
    
    def test_create_user_with_valid_arguments(self):
        """Command should create user with valid arguments."""
        call_command(
            'create_user',
            '--username', 'newuser',
            '--email', 'newuser@example.com',
            '--no-email',
            stdout=self.stdout
        )
        
        # User should exist
        user = User.objects.get(username='newuser')
        self.assertEqual(user.email, 'newuser@example.com')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
    
    def test_create_user_with_full_details(self):
        """Command should create user with all details."""
        call_command(
            'create_user',
            '--username', 'john.doe',
            '--email', 'john@example.com',
            '--first-name', 'John',
            '--last-name', 'Doe',
            '--no-email',
            stdout=self.stdout
        )
        
        user = User.objects.get(username='john.doe')
        self.assertEqual(user.first_name, 'John')
        self.assertEqual(user.last_name, 'Doe')
    
    def test_create_user_with_staff_privileges(self):
        """Command should grant staff privileges when requested."""
        call_command(
            'create_user',
            '--username', 'staffuser',
            '--email', 'staff@example.com',
            '--is-staff',
            '--no-email',
            stdout=self.stdout
        )
        
        user = User.objects.get(username='staffuser')
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
    
    def test_create_user_with_superuser_privileges(self):
        """Command should grant superuser privileges when requested."""
        call_command(
            'create_user',
            '--username', 'superuser',
            '--email', 'super@example.com',
            '--is-superuser',
            '--no-email',
            stdout=self.stdout
        )
        
        user = User.objects.get(username='superuser')
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)  # Superuser should also be staff
    
    def test_create_user_generates_random_password(self):
        """Command should generate a random password."""
        call_command(
            'create_user',
            '--username', 'randompassuser',
            '--email', 'random@example.com',
            '--no-email',
            stdout=self.stdout
        )
        
        # User should be created and password should be set
        user = User.objects.get(username='randompassuser')
        # Password should not be empty or simple
        self.assertNotEqual(user.password, 'randompassuser')
        self.assertNotEqual(user.password, '')
    
    def test_create_user_duplicate_username_fails(self):
        """Command should fail when username already exists."""
        # Create first user
        User.objects.create_user(username='existing', password='pass', email='ex@example.com')
        
        # Try to create same username
        with self.assertRaises(Exception):
            call_command(
                'create_user',
                '--username', 'existing',
                '--email', 'new@example.com',
                '--no-email',
                stdout=self.stdout
            )
    
    def test_create_user_duplicate_email_fails(self):
        """Command should fail when email already exists."""
        User.objects.create_user(username='user1', password='pass', email='existing@example.com')
        
        with self.assertRaises(Exception):
            call_command(
                'create_user',
                '--username', 'user2',
                '--email', 'existing@example.com',
                '--no-email',
                stdout=self.stdout
            )
    
    def test_create_user_missing_required_arguments(self):
        """Command should fail without required arguments."""
        with self.assertRaises((SystemExit, CommandError)):
            call_command(
                'create_user',
                '--email', 'test@example.com'
            )
    
    def test_create_user_password_length_configurable(self):
        """Command should respect custom password length."""
        call_command(
            'create_user',
            '--username', 'custompasslength',
            '--email', 'custom@example.com',
            '--password-length', '24',
            '--no-email',
            stdout=self.stdout
        )
        
        user = User.objects.get(username='custompasslength')
        # Password should be generated (not empty)
        self.assertNotEqual(user.password, '')
    
    def test_create_user_without_email_flag(self):
        """Command should support --no-email flag to skip sending email."""
        call_command(
            'create_user',
            '--username', 'noemail',
            '--email', 'noemail@example.com',
            '--no-email',
            stdout=self.stdout
        )
        
        # User should still be created
        user = User.objects.get(username='noemail')
        self.assertIsNotNone(user)


class TokenAuthenticationTestCase(APITestCase):
    """Test token-based API authentication."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
    
    def test_bearer_token_authentication(self):
        """Bearer token format should work for authentication."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.key}')
        response = self.client.get('/api/v1/uploads/')
        
        # Should not get 401
        self.assertNotEqual(response.status_code, 401)
    
    def test_token_format_authentication(self):
        """Legacy Token format should still work."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        response = self.client.get('/api/v1/uploads/')
        
        # Should not get 401
        self.assertNotEqual(response.status_code, 401)
    
    def test_invalid_token_rejected(self):
        """Invalid token should be rejected."""
        self.client.credentials(HTTP_AUTHORIZATION='Bearer invalid_token_123')
        response = self.client.get('/api/v1/uploads/')
        
        self.assertEqual(response.status_code, 401)
    
    def test_missing_token_rejected(self):
        """Request without token should be rejected."""
        # Don't set credentials
        response = self.client.get('/api/v1/uploads/')
        
        self.assertEqual(response.status_code, 401)
    
    def test_malformed_auth_header_rejected(self):
        """Malformed Authorization header should be rejected."""
        self.client.credentials(HTTP_AUTHORIZATION='JustAToken')
        response = self.client.get('/api/v1/uploads/')
        
        self.assertEqual(response.status_code, 401)


class UserPermissionsTestCase(APITestCase):
    """Test user permissions and access control."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create regular user
        self.user1 = User.objects.create_user(
            username='user1',
            password='pass1'
        )
        self.token1 = Token.objects.create(user=self.user1)
        
        # Create admin user
        self.user2 = User.objects.create_user(
            username='admin',
            password='pass2'
        )
        self.user2.is_staff = True
        self.user2.save()
        self.token2 = Token.objects.create(user=self.user2)
        
        self.client = APIClient()
    
    def test_authenticated_user_can_access_uploads(self):
        """Authenticated user should access upload endpoints."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token1.key}')
        response = self.client.get('/api/v1/uploads/')
        
        # Should not get 401 Unauthorized
        self.assertNotEqual(response.status_code, 401)
    
    def test_staff_user_has_is_staff_flag(self):
        """Staff user should have is_staff flag set."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token2.key}')

        # Login (completing mandatory 2FA enrollment) to get user info
        response = complete_mandatory_2fa_enrollment(self.client, 'admin', 'pass2')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['is_staff'])
