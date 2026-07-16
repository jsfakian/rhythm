"""Custom auth-related forms."""

from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, _unicode_ci_compare


class InactiveAllowedPasswordResetForm(PasswordResetForm):
    """PasswordResetForm variant that also matches not-yet-activated accounts.

    Signup accounts are created with ``is_active=False`` until an admin
    triggers email verification (see ``uploads.serializers``). Django's
    stock ``PasswordResetForm.get_users()`` filters on ``is_active=True``,
    so a user who forgets their password before verification never
    receives a reset email and silently lands on the generic "check your
    email" page. Dropping the ``is_active`` filter here lets those users
    reset their password too.
    """

    def get_users(self, email):
        UserModel = get_user_model()
        email_field_name = UserModel.get_email_field_name()
        users = UserModel._default_manager.filter(**{
            '%s__iexact' % email_field_name: email,
        })
        return (
            u for u in users
            if u.has_usable_password()
            and _unicode_ci_compare(email, getattr(u, email_field_name))
        )

    def save(self, **kwargs):
        # PasswordResetView derives use_https from request.is_secure(), which
        # is unreliable behind a proxy that doesn't set the forwarded-proto
        # header. Reset links must always be https regardless.
        kwargs['use_https'] = True
        super().save(**kwargs)
