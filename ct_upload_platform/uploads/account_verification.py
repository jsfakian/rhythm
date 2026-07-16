"""Helper to send the signup email-verification link."""

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import email_verification_token


def send_verification_email(user: User, request) -> None:
    """Email *user* a link that activates their account when visited."""
    site = get_current_site(request)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    protocol = 'https'
    verify_path = reverse('verify-email', kwargs={'uidb64': uid, 'token': token})

    context = {
        'user': user,
        'protocol': protocol,
        'domain': site.domain,
        'verify_url': f'{protocol}://{site.domain}{verify_path}',
    }
    subject = render_to_string('uploads/verification_subject.txt', context).strip()
    message = render_to_string('uploads/verification_email.txt', context)

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )

    profile = getattr(user, 'profile', None)
    if profile is not None:
        profile.verification_email_sent_at = timezone.now()
        profile.save(update_fields=['verification_email_sent_at'])


def notify_admins_of_new_signup(user: User, request) -> None:
    """Email the configured admin address that *user* is pending verification.

    No-op if ``ADMIN_NOTIFICATION_EMAIL`` isn't set, so deployments that
    haven't configured it don't get a send failure on every signup.
    """
    if not settings.ADMIN_NOTIFICATION_EMAIL:
        return

    site = get_current_site(request)
    protocol = 'https'
    context = {
        'user': user,
        'protocol': protocol,
        'domain': site.domain,
        'manage_url': f'{protocol}://{site.domain}{reverse("user-management")}',
    }
    subject = render_to_string('uploads/new_signup_notification_subject.txt', context).strip()
    message = render_to_string('uploads/new_signup_notification_email.txt', context)

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [settings.ADMIN_NOTIFICATION_EMAIL],
        fail_silently=False,
    )
