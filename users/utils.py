from sendy.api import SendyAPI
sendy_api = SendyAPI(
    host='https://sendy.baseline.is/',
    api_key='tBrmr5P4jbAwHMxoUqrI',
)
from django.db.models import Prefetch

def sendy_subscribe(email, name, subscribe_list, unsubscribe_list=None, user=None):
    """
    Subscribe a user to a Sendy list, and optionally unsubscribe from another list.
    :param email: User's email
    :param name: User's name
    :param subscribe_list: List ID to subscribe to
    :param unsubscribe_list: List ID to unsubscribe from (optional)
    :param user: User object (optional, for custom logic)
    """
    if unsubscribe_list:
        # Unsubscribe from the old list if currently subscribed
        subscriber_status = sendy_api.subscriber_status(unsubscribe_list, email)
        if subscriber_status == 'Subscribed':
            sendy_api.unsubscribe(unsubscribe_list, email)

    # Always subscribe to the new list
    sendy_api.subscribe(
        subscribe_list,
        email,
        name,
    )
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

def get_client_ip(request):
    """
    Get client IP address from request object.
    Handles cases where request might be coming through a proxy.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')

def send_verification_email(user):
    logger.info(f"Sending verification email to {user.email}")
    if not user.can_send_verification_email():
        time_diff = timezone.now() - user.last_verification_email_sent
        wait_time = 24 - (time_diff.total_seconds() / 3600)
        raise ValueError(f"Too many verification emails sent. Please wait {int(wait_time)} hours before requesting another.")

    token = user.generate_verification_token()
    verification_url = f"{settings.FRONTEND_URL}/account/verify-email/{token}"
    
    send_mail(
        'Verify your email',
        f'Please click this link to verify your email: {verification_url}\n'
        f'This link will expire in 24 hours.',
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )

    # Reset count if it's been more than 24 hours
    if user.last_verification_email_sent:
        time_diff = timezone.now() - user.last_verification_email_sent
        if time_diff.total_seconds() >= (24 * 3600):
            user.verification_email_sent_count = 0

    user.verification_email_sent_count = (user.verification_email_sent_count or 0) + 1
    user.last_verification_email_sent = timezone.now()
    user.save()

def send_password_reset_email(user):
    token = user.generate_token('password_reset')
    reset_url = f"{settings.FRONTEND_URL}/reset-password/{token}"
    
    send_mail(
        'Reset your password',
        f'Click this link to reset your password: {reset_url}\n'
        f'This link will expire in 1 hour.',
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )

def send_email_change_verification(user, new_email):
    token = user.generate_token('email_change')
    verification_url = f"{settings.FRONTEND_URL}/verify-email-change/{token}"
    
    send_mail(
        'Verify your new email\n\n',
        f'Click this link to verify your new email address: {verification_url}\n\n'
        f'This link will expire in 24 hours.',
        settings.DEFAULT_FROM_EMAIL,
        [new_email],
        fail_silently=False,
    ) 