from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.http import JsonResponse

def send_invitation_email(invitation):
    """
    Send workspace invitation email
    """
    subject = f"You've been invited to join {invitation.workspace.name}"
    
    context = {
        'workspace_name': invitation.workspace.name,
        'invited_by': invitation.invited_by.get_full_name() or invitation.invited_by.email,
        'role': invitation.get_role_display(),
        'accept_url': f"{settings.FRONTEND_URL}/invites/{invitation.token}",
        'expires_at': invitation.expires_at,
    }
    
    # You can create an HTML email template at templates/emails/workspace_invitation.html
    html_message = render_to_string('emails/workspace_invitation.html', context)
    plain_message = f"""
    You've been invited to join {invitation.workspace.name} by {invitation.invited_by.get_full_name() or invitation.invited_by.email}.
    Role: {invitation.get_role_display()}
    Click here to accept: {settings.FRONTEND_URL}/invites/{invitation.token}
    This invitation expires on {invitation.expires_at}
    """
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        # Log the error
        print(f"Failed to send invitation email: {e}")
        return False

def create_error_response(message, status=403):
    return JsonResponse(
        {"detail": message},
        status=status
    )
