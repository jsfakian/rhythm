"""Token generators for account-related email links."""

from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """One-time token for the signup email-verification link.

    Includes ``is_active`` in the hash so the token is invalidated once the
    account has been activated, preventing reuse of an already-consumed link.
    """

    def _make_hash_value(self, user, timestamp):
        return f'{user.pk}{user.password}{timestamp}{user.is_active}'


email_verification_token = EmailVerificationTokenGenerator()
