from django.dispatch import receiver
from django.db import transaction
from django_paddle_billing.signals import (
    subscription_created,
    subscription_activated,
    subscription_canceled,
    subscription_past_due,
    subscription_paused,
    subscription_resumed,
    subscription_trialing,
    subscription_updated
)
from .models import Workspace, CustomFieldValue, UserNotificationPreference, WorkspaceMember
from django_paddle_billing.models import Subscription
import logging
import time
from django.db.models.signals import post_save
from .services.ai_actions import trigger_ai_actions
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

User = get_user_model()

@receiver(subscription_created)
def handle_subscription_created(sender, payload, occurred_at, **kwargs):
    """
    When a subscription is created, create the workspace subscription link
    """
    logger.info("Subscription created signal received")
    logger.info(f"Payload: {payload}")
    
    try:
        with transaction.atomic():
            logger.info(f"Custom data: {getattr(payload, 'custom_data', None)}")
            
            # Safely access custom_data if it exists
            workspace_id = None
            if hasattr(payload, 'custom_data') and payload.custom_data:
                workspace_id = payload.custom_data.get('workspace_id')
            
            logger.info(f"Workspace ID: {workspace_id}")
            logger.info(f"Subscription ID: {payload.id}")
            
            # Try to assign ids to variables, log errors if they fail
            try:
                subscription_id = payload.id
                workspace_id = payload.custom_data.get('workspace_id')
            except Exception as e:
                logger.error(f"Error getting ids from subscription signal: {str(e)}")
                return
            
            # Try to get the newly created subscription, retrying if it doesn't exist yet
            subscription = None
            for _ in range(3):
                subscription = Subscription.objects.get(id=subscription_id)
                if subscription:
                    workspace = Workspace.objects.get(id=workspace_id)
                    workspace.subscriptions.add(subscription)
                    workspace.save()
                    logger.info(f"Subscription {subscription_id} successfully assigned to workspace {workspace_id}")
                    break
                time.sleep(1)
            
            # Debug logging
            logger.info(f"Adding subscription {subscription.id} to workspace {workspace.id}")
    except Exception as e:
        logger.error(f"Error in subscription_created: {str(e)}", exc_info=True)

# @receiver(subscription_activated)
# def handle_subscription_activated(sender, subscription, **kwargs):
#     """Handle subscription activation"""
#     workspace_sub = WorkspaceSubscription.objects.filter(
#         subscription=subscription
#     ).first()
#     if workspace_sub:
#         # You might want to enable features or send notifications
#         pass

# @receiver(subscription_canceled)
# def handle_subscription_canceled(sender, subscription, **kwargs):
#     """Handle subscription cancellation"""
#     workspace_sub = WorkspaceSubscription.objects.filter(
#         subscription=subscription
#     ).first()
#     if workspace_sub:
#         # Maybe downgrade workspace to free tier
#         # Or schedule workspace for archival
#         pass

# @receiver(subscription_past_due)
# def handle_subscription_past_due(sender, subscription, **kwargs):
#     """Handle past due payments"""
#     workspace_sub = WorkspaceSubscription.objects.filter(
#         subscription=subscription
#     ).first()
#     if workspace_sub:
#         # Maybe send notification to workspace owner
#         # Or disable certain features
#         pass

# @receiver(subscription_paused)
# def handle_subscription_paused(sender, subscription, **kwargs):
#     """Handle paused subscriptions"""
#     workspace_sub = WorkspaceSubscription.objects.filter(
#         subscription=subscription
#     ).first()
#     if workspace_sub:
#         # Maybe limit workspace features
#         pass

@receiver(subscription_updated)
def handle_subscription_updated(sender, payload, occurred_at, **kwargs):
    """Handle subscription updated event"""
    logger.info(f"Subscription updated: {payload.id}")
    
    # Add a small delay to ensure the subscription is fully processed
    time.sleep(1)
    
    # Get the subscription object from the database
    try:
        subscription = Subscription.objects.get(id=payload.id)
        # Sync the subscription to get the latest data
        subscription.sync_from_paddle()
        logger.info(f"Subscription {subscription.id} synced successfully")
    except Subscription.DoesNotExist:
        logger.error(f"Subscription {payload.id} not found in database")
    except Exception as e:
        logger.error(f"Failed to sync subscription {payload.id}: {str(e)}")

# Make sure signals are loaded
default_app_config = 'main.apps.MainConfig' 

@receiver(post_save, sender=CustomFieldValue)
def trigger_ai_actions_on_field_value_change(sender, instance, created, **kwargs):
    """Trigger AI actions when a custom field value is created or updated"""
    # Check if AI actions were already triggered via API endpoint
    from main.services.ai_actions import _thread_local
    if getattr(_thread_local, 'api_triggered', False):
        logger.info("Skipping signal-based AI action trigger - already handled by API endpoint")
        return
    
    # Only trigger for single-select fields with option values
    if instance.field.field_type == 'SINGLE_SELECT' and instance.option_value:
        trigger_ai_actions(instance)

@receiver(post_save, sender=User)
def create_user_notification_preferences(sender, instance, created, **kwargs):
    """Create default notification preferences when a new user is created"""
    if created:
        UserNotificationPreference.get_or_create_for_user(instance)

@receiver(post_save, sender=WorkspaceMember)
def auto_follow_boards_for_new_member(sender, instance, created, **kwargs):
    """Auto-follow boards based on role when a new workspace member is created"""
    if created:
        from main.services.notifications import NotificationService
        
        workspace = instance.workspace
        user = instance.user
        role = instance.role
        
        # Get boards to auto-follow based on role
        boards_to_follow = []
        
        if role == WorkspaceMember.Role.ADMIN:
            # Admins follow all boards in the workspace
            boards_to_follow = list(workspace.boards.all())
            logger.info(f"Auto-following all {len(boards_to_follow)} boards for admin {user.email}")
            
        elif role in [WorkspaceMember.Role.EDITOR, WorkspaceMember.Role.COMMENTER]:
            # Editors and Commenters follow only root/main boards
            root_boards = workspace.boards.filter(parent=None)
            boards_to_follow = list(root_boards)
            logger.info(f"Auto-following {len(boards_to_follow)} root boards for {role.lower()} {user.email}")
        
        # Follow the boards
        for board in boards_to_follow:
            try:
                NotificationService.follow_board(
                    user=user,
                    board=board,
                    include_sub_boards=(role == WorkspaceMember.Role.ADMIN)  # Admins get sub-boards too
                )
                logger.info(f"Auto-followed board '{board.name}' for new {role.lower()} {user.email}")
            except Exception as e:
                logger.error(f"Failed to auto-follow board '{board.name}' for {user.email}: {str(e)}") 