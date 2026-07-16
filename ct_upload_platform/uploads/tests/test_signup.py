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

    def test_signup_does_not_return_token(self):
        """New accounts are pending admin verification — no token is issued at signup."""
        response = self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        data = response.json()
        self.assertNotIn('token', data)

    def test_signup_response_contains_user_info(self):
        response = self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        data = response.json()
        self.assertEqual(data['username'], 'newuser')
        self.assertEqual(data['email'], 'newuser@example.com')
        self.assertIn('message', data)

    def test_signup_creates_inactive_user(self):
        """New accounts stay inactive until an admin sends and the user clicks the verification link."""
        self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        user = User.objects.get(username='newuser')
        self.assertFalse(user.is_active)
        self.assertFalse(user.profile.email_verified)

    def test_signup_with_optional_name_fields(self):
        payload = {**self.valid_payload, 'first_name': 'Jane', 'last_name': 'Smith'}
        response = self.client.post(SIGNUP_URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='newuser')
        self.assertEqual(user.first_name, 'Jane')
        self.assertEqual(user.last_name, 'Smith')

    def test_signup_user_cannot_login_before_verification(self):
        """A freshly signed-up user must not be able to log in until an admin verifies them."""
        self.client.post(SIGNUP_URL, self.valid_payload, format='json')
        login_response = self.client.post(
            '/api/v1/auth/login/',
            {'username': 'newuser', 'password': 'StrongPass99!'},
            format='json',
        )
        self.assertEqual(login_response.status_code, status.HTTP_403_FORBIDDEN)

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
# Admin-triggered verification email + verification link
# ---------------------------------------------------------------------------

class EmailVerificationFlowTestCase(APITestCase):
    """Covers the manual 'send verification email' action and the link it sends."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='adminpass123',
        )
        self.client.post(SIGNUP_URL, {
            'username': 'pendinguser',
            'email': 'pendinguser@example.com',
            'password': 'StrongPass99!',
            'password2': 'StrongPass99!',
            'institution': 'Test University Hospital',
            'professional_role': 'radiologist',
            'terms_accepted': True,
        }, format='json')
        self.user = User.objects.get(username='pendinguser')

    def test_signup_notifies_admin_but_not_the_new_user(self):
        from django.core import mail
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(self.user.email, mail.outbox[0].to)

    def test_non_admin_cannot_send_verification_email(self):
        self.client.login(username='pendinguser', password='StrongPass99!')
        response = self.client.post(
            f'/users/api/{self.user.id}/update/', {'action': 'send_verification_email'}, format='json',
        )
        self.assertNotEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_can_send_verification_email(self):
        from django.core import mail
        mail.outbox.clear()  # setUp's signup() already queued an admin notification
        self.client.login(username='admin', password='adminpass123')
        response = self.client.post(
            f'/users/api/{self.user.id}/update/', {'action': 'send_verification_email'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('verify-email', mail.outbox[0].body)

    def test_clicking_verification_link_activates_account(self):
        from uploads.tokens import email_verification_token
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = email_verification_token.make_token(self.user)

        response = self.client.get(f'/verify-email/{uid}/{token}/')
        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.profile.email_verified)

    def test_invalid_verification_token_does_not_activate(self):
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.client.get(f'/verify-email/{uid}/bogus-token/')
        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_verified_user_can_then_login(self):
        from uploads.tokens import email_verification_token
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = email_verification_token.make_token(self.user)
        self.client.get(f'/verify-email/{uid}/{token}/')

        login_response = self.client.post(
            '/api/v1/auth/login/',
            {'username': 'pendinguser', 'password': 'StrongPass99!'},
            format='json',
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)


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
