"""
Tests for signup functionality.

Covers:
- SignupView API endpoint (unit tests)
- SignupPageView HTML view (functional tests)
- ensure_demo_user management command
"""

from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.test.client import Client
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase


SIGNUP_URL = '/api/v1/auth/signup/'
SIGNUP_PAGE_URL = '/signup/'


# ---------------------------------------------------------------------------
# API endpoint — unit tests
# ---------------------------------------------------------------------------

class SignupAPITestCase(APITestCase):
    """Tests for POST /api/v1/auth/signup/."""

    def setUp(self):
        self.client = APIClient()
        self.valid_payload = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'StrongPass99!',
            'password2': 'StrongPass99!',
            'institution': 'Test University Hospital',
            'professional_role': 'radiologist',
            'terms_accepted': True,
        }

    # --- happy path ---

    def test_signup_creates_user(self):
        response = self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_signup_returns_token(self):
        response = self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        data = response.json()
        self.assertIn('token', data)
        self.assertTrue(Token.objects.filter(key=data['token']).exists())

    def test_signup_response_contains_user_info(self):
        response = self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        data = response.json()
        self.assertEqual(data['username'], 'newuser')
        self.assertEqual(data['email'], 'newuser@example.com')
        self.assertIn('user_id', data)
        self.assertFalse(data['is_staff'])

    def test_signup_with_optional_name_fields(self):
        payload = {**self.valid_payload, 'first_name': 'Jane', 'last_name': 'Smith'}
        response = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='newuser')
        self.assertEqual(user.first_name, 'Jane')
        self.assertEqual(user.last_name, 'Smith')

    def test_signup_token_works_for_api_access(self):
        """Token returned at signup must authenticate subsequent API calls."""
        response = self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        token = response.json()['token']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        upload_response = self.client.get('/api/v1/uploads/')
        self.assertNotEqual(upload_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_signup_new_user_is_not_staff(self):
        self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        user = User.objects.get(username='newuser')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    # --- validation errors ---

    def test_signup_duplicate_username_rejected(self):
        User.objects.create_user(username='newuser', password='x', email='other@example.com')
        response = self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('username', data['details'])

    def test_signup_duplicate_email_rejected(self):
        User.objects.create_user(username='other', password='x', email='newuser@example.com')
        response = self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('email', data['details'])

    def test_signup_password_mismatch_rejected(self):
        payload = {**self.valid_payload, 'password2': 'DifferentPass99!'}
        response = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('password2', data['details'])

    def test_signup_weak_password_rejected(self):
        """Django's password validators should reject common/short passwords."""
        payload = {**self.valid_payload, 'password': '12345678', 'password2': '12345678'}
        response = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn('password', data['details'])

    def test_signup_missing_username_rejected(self):
        payload = {k: v for k, v in self.valid_payload.items() if k != 'username'}
        response = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_signup_missing_email_rejected(self):
        payload = {k: v for k, v in self.valid_payload.items() if k != 'email'}
        response = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_signup_missing_password_rejected(self):
        payload = {k: v for k, v in self.valid_payload.items() if k != 'password'}
        response = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_signup_invalid_email_rejected(self):
        payload = {**self.valid_payload, 'email': 'not-an-email'}
        response = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_signup_endpoint_accessible_without_auth(self):
        """Signup must not require authentication."""
        response = self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_signup_without_optional_fields(self):
        """first_name and last_name are optional; omitting them must succeed."""
        payload = {k: v for k, v in self.valid_payload.items()
                   if k not in ('first_name', 'last_name')}
        response = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# HTML page view — functional tests
# ---------------------------------------------------------------------------

class SignupPageViewTestCase(TestCase):
    """Tests for GET /signup/."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='existinguser',
            password='testpass123',
        )

    def test_signup_page_accessible(self):
        response = self.client.get(SIGNUP_PAGE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sign Up', response.content)

    def test_signup_page_contains_form_fields(self):
        response = self.client.get(SIGNUP_PAGE_URL)
        content = response.content.decode()
        self.assertIn('id="username"', content)
        self.assertIn('id="email"', content)
        self.assertIn('id="password"', content)
        self.assertIn('id="password2"', content)

    def test_signup_page_has_login_link(self):
        response = self.client.get(SIGNUP_PAGE_URL)
        self.assertIn(b'/login/', response.content)

    def test_authenticated_user_redirected_from_signup(self):
        self.client.login(username='existinguser', password='testpass123')
        response = self.client.get(SIGNUP_PAGE_URL)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_signup_page_uses_correct_template(self):
        response = self.client.get(SIGNUP_PAGE_URL)
        self.assertTemplateUsed(response, 'uploads/signup.html')


# ---------------------------------------------------------------------------
# Login page — regression: signup link present
# ---------------------------------------------------------------------------

class LoginPageSignupLinkTestCase(TestCase):
    """Ensure login page links to signup."""

    def test_login_page_has_signup_link(self):
        response = self.client.get('/login/')
        self.assertIn(b'/signup/', response.content)


# ---------------------------------------------------------------------------
# ensure_demo_user management command
# ---------------------------------------------------------------------------

class EnsureDemoUserCommandTestCase(TestCase):
    """Tests for the ensure_demo_user management command."""

    def _run(self):
        out = StringIO()
        call_command('ensure_demo_user', stdout=out)
        return out.getvalue()

    def test_creates_demo_user_on_first_run(self):
        self.assertFalse(User.objects.filter(username='demo').exists())
        self._run()
        self.assertTrue(User.objects.filter(username='demo').exists())

    def test_demo_user_can_login_with_expected_password(self):
        self._run()
        user = User.objects.get(username='demo')
        self.assertTrue(user.check_password('changeme123!!'))

    def test_demo_user_has_token(self):
        self._run()
        user = User.objects.get(username='demo')
        self.assertTrue(Token.objects.filter(user=user).exists())

    def test_demo_user_is_not_staff(self):
        self._run()
        user = User.objects.get(username='demo')
        self.assertFalse(user.is_staff)

    def test_idempotent_second_run_does_not_duplicate(self):
        self._run()
        self._run()
        self.assertEqual(User.objects.filter(username='demo').count(), 1)

    def test_idempotent_second_run_does_not_raise(self):
        self._run()
        try:
            self._run()
        except Exception as exc:
            self.fail(f'Second run raised an exception: {exc}')

    def test_output_on_creation(self):
        output = self._run()
        self.assertIn('demo', output)

    def test_output_on_skip(self):
        self._run()
        output = self._run()
        self.assertIn('already exists', output)
