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
from .models import Workspace, CustomFieldValue
from django_paddle_billing.models import Subscription
import logging
import time
from django.db.models.signals import post_save
from .services.ai_actions import trigger_ai_actions

logger = logging.getLogger(__name__)

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

# @receiver(subscription_updated)
# def handle_subscription_updated(sender, subscription, **kwargs):
#     """Handle subscription updates (like plan changes)"""
#     workspace_sub = WorkspaceSubscription.objects.filter(
#         subscription=subscription
#     ).first()
#     if workspace_sub:
#         # Maybe update workspace features based on new plan
#         pass

# Make sure signals are loaded
default_app_config = 'main.apps.MainConfig'

@receiver(post_save, sender=CustomFieldValue)
def handle_field_value_change(sender, instance, created, **kwargs):
    """
    When a field value is created or updated, trigger any associated AI actions
    if it's a single-select field with an option that has AI actions enabled.
    """
    if instance.field.field_type == 'SINGLE_SELECT' and instance.option_value:
        trigger_ai_actions(instance) 