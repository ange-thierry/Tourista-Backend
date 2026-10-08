"""Outgoing email. In development the console backend prints messages to the
runserver terminal; set EMAIL_* in .env to send real mail."""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .constants import UserRole

logger = logging.getLogger(__name__)


def _send(subject: str, body: str, recipients: list[str]) -> bool:
    recipients = [r for r in recipients if r]
    if not recipients:
        return False
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
        return True
    except Exception:  # never let email failures break a request
        logger.exception('Failed to send email "%s" to %s', subject, recipients)
        return False


def frontend_url(path: str) -> str:
    return f'{settings.FRONTEND_URL.rstrip("/")}/{path.lstrip("/")}'


def user_token_link(user, path: str, token: str | None = None) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = token or default_token_generator.make_token(user)
    return frontend_url(f'{path}?uid={uid}&token={token}')


def send_verification_email(user, token: str) -> bool:
    link = user_token_link(user, 'verify-email', token)
    return _send(
        'Confirm your Tourista Rwanda email',
        f'Hello {user.name},\n\nConfirm your email address to secure your account and see '
        f'bookings made with this email:\n\n{link}\n\nIf you did not create an account, ignore this email.',
        [user.email],
    )


def send_password_reset_email(user) -> bool:
    link = user_token_link(user, 'reset-password')
    return _send(
        'Reset your Tourista Rwanda password',
        f'Hello {user.name},\n\nUse this link to choose a new password (valid for '
        f'{settings.PASSWORD_RESET_TIMEOUT // 3600} hours):\n\n{link}\n\n'
        'If you did not ask for this, you can ignore this email.',
        [user.email],
    )


def send_booking_email(booking) -> bool:
    due = (
        f'Balance due: ${booking.amount_due} (pay any time from My Bookings).'
        if booking.amount_due > 0
        else 'Paid in full.'
    )
    when = f'{booking.check_in:%a %d %b %Y}'
    if booking.check_out != booking.check_in:
        when += f' – {booking.check_out:%a %d %b %Y}'
    if booking.time_slot:
        when += f' at {booking.time_slot}'
    return _send(
        f'Your booking {booking.reference} is confirmed',
        f'Hello {booking.guest_full_name},\n\n'
        f'{booking.service_name}\n{booking.location}\n{when}\nGuests/quantity: {booking.guests}\n\n'
        f'Total: ${booking.total_amount}. Paid: ${booking.amount_paid}. {due}\n\n'
        f'Reference: {booking.reference}\nManage it here: {frontend_url("my-bookings")}\n',
        [booking.guest_email],
    )


def send_provider_booking_email(booking, provider) -> bool:
    return _send(
        f'New booking {booking.reference}',
        f'{booking.guest_full_name} ({booking.guest_email}, {booking.guest_phone or "no phone"}) booked '
        f'{booking.service_name} for {booking.check_in:%d %b %Y}'
        f'{f" at {booking.time_slot}" if booking.time_slot else ""}.\n\n'
        f'Open your dashboard: {frontend_url("dashboard?tab=bookings")}\n',
        [provider.email],
    )


def staff_recipients() -> list[str]:
    configured = list(getattr(settings, 'STAFF_NOTIFICATION_EMAILS', []))
    if configured:
        return configured
    User = get_user_model()
    return list(User.objects.filter(role=UserRole.ADMIN, is_active=True).values_list('email', flat=True))


def notify_staff(subject: str, body: str) -> bool:
    return _send(subject, body, staff_recipients())
