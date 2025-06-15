from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
import uuid
from django.utils import timezone
from django.conf import settings
from django_paddle_billing.models import Subscription as PaddleSubscription
import logging
from mptt.models import MPTTModel, TreeForeignKey

logger = logging.getLogger(__name__)

def workspace_avatar_path(instance, filename):
    """Generate upload path for workspace avatars"""
    ext = filename.split('.')[-1].lower()
    return f'avatars/{uuid.uuid4()}.{ext}'

def workspace_asset_path(instance, filename):
    """Generate upload path for workspace assets"""
    logger.debug(f"Generating path for file: {filename} for asset: {instance.id}")
    logger.debug(f"Asset status: {instance.status}")
    logger.debug(f"Asset creation timestamp: {instance.date_uploaded}")
    return f'workspaces/{instance.workspace.id}/assets/{instance.id}/{filename}'

class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='WorkspaceMember',
        through_fields=('workspace', 'user'),
        related_name='workspaces'
    )
    avatar = models.ImageField(
        upload_to=workspace_avatar_path,
        null=True,
        blank=True
    )
    subscriptions = models.ManyToManyField(
        PaddleSubscription,
        related_name='workspaces',
        blank=True
    )

    def __str__(self):
        return self.name
    
    class Meta:
        app_label = 'main'

    @property
    def subscription_details(self):
        """Get detailed subscription information"""
        now = timezone.now()
        
        # Debug logging
        all_subs = self.subscriptions.all()
        # logger.info(f"Workspace {self.id} subscriptions count: {all_subs.count()}")
        
        subscription = all_subs.first()
        # logger.info(f"Subscription: {subscription}")
        
        if not subscription:
            # logger.warning(f"No subscription found for workspace {self.id}")
            return {
                'status': 'free',
                'billing_details': None
            }

        # logger.info(f"Subscription data: {subscription.data}")
        ends_at = subscription.data.get('ends_at')
        scheduled_change = subscription.data.get('scheduled_change')
        
        if subscription.status == 'canceled' and ends_at and ends_at < now.isoformat():
            return {
                'status': 'free',
                'billing_details': None
            }
        
        # Safely get billing cycle data
        billing_cycle = subscription.data.get('billing_cycle', {})
        # logger.info(f"Billing cycle: {billing_cycle}")
        
        # Get first product safely
        product = subscription.products.first()
        plan_name = product.name if product else 'Unknown'
        
        return_data = {
            'status': subscription.status,
            'plan': plan_name,
            'billing_details': {
                'id': subscription.id,
                'next_billed_at': subscription.data.get('next_billed_at'),
                'billing_interval': billing_cycle.get('interval'),
                'billing_frequency': billing_cycle.get('frequency'),
                'canceled_at': subscription.data.get('canceled_at'),
                'ends_at': subscription.data.get('ends_at'),
                'scheduled_change': scheduled_change
            }
        }
        
        # logger.info(f"Return data: {return_data}")
        return return_data

    @property
    def subscription_status(self):
        """Get the current subscription status"""
        active_subscription = self.subscriptions.filter(
            status__in=['active', 'trialing']
        ).first()
        
        if not active_subscription:
            return 'free'
        return active_subscription.status

    @property
    def is_paid(self):
        """Check if workspace has an active paid subscription"""
        return self.subscription_status in ['active', 'trialing']

    def can_use_feature(self, feature_name):
        """Check if workspace can use a specific feature"""
        workspace_sub = getattr(self, 'subscription', None)
        if not workspace_sub or not workspace_sub.subscription:
            return False  # or check against free tier features
            
        # Check feature availability based on subscription plan
        plan = workspace_sub.subscription.price.product.name
        # Implement your feature matrix here
        feature_matrix = {
            'pro': ['feature1', 'feature2'],
            'enterprise': ['feature1', 'feature2', 'feature3']
        }
        return feature_name in feature_matrix.get(plan, [])

class WorkspaceMember(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrator'
        EDITOR = 'EDITOR', 'Editor'
        COMMENTER = 'COMMENTER', 'Commenter'

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices)
    joined_at = models.DateTimeField(auto_now_add=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='invites_sent'
    )
    
    class Meta:
        unique_together = ['workspace', 'user']

    def __str__(self):
        return f"{self.user} in {self.workspace}"

    def can_manage_workspace(self) -> bool:
        """Can edit workspace settings and invite members"""
        return self.role == self.Role.ADMIN

    def can_manage_content(self) -> bool:
        """Can create, edit, and delete content"""
        return self.role in [self.Role.ADMIN, self.Role.EDITOR]

    def can_comment(self) -> bool:
        """Can view and comment on content"""
        return True  # All roles can comment

class WorkspaceInvitation(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('ACCEPTED', 'Accepted'),
        ('REJECTED', 'Rejected'),
        ('EXPIRED', 'Expired'),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=WorkspaceMember.Role.choices)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    token = models.UUIDField(default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"Invitation for {self.email} to {self.workspace}"

    @property
    def is_expired(self):
        return self.expires_at < timezone.now()

    @property
    def is_pending(self):
        return self.status == 'PENDING' and not self.is_expired

    def mark_as_accepted(self):
        self.status = 'ACCEPTED'
        self.save()

    def mark_as_rejected(self):
        self.status = 'REJECTED'
        self.save()

    def mark_as_expired(self):
        self.status = 'EXPIRED'
        self.save()

class ShareLink(models.Model):
    """Generic share links for any workspace content"""
    PERMISSION_CHOICES = [
        ('VIEW', 'View only'),
        ('COMMENT', 'Can comment'),
        ('EDIT', 'Can edit'),
        ('SUBMIT', 'Can submit (for forms)'),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, editable=False)
    permission = models.CharField(max_length=20, choices=PERMISSION_CHOICES, default='VIEW')
    
    # Generic foreign key to support sharing different types of content
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Optional settings
    expires_at = models.DateTimeField(null=True, blank=True)
    password = models.CharField(max_length=128, null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    current_uses = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Share link for {self.content_object}"

    @property
    def is_valid(self):
        if self.expires_at and self.expires_at < timezone.now():
            return False
        if self.max_uses and self.current_uses >= self.max_uses:
            return False
        return True

class Board(MPTTModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='boards')
    parent = TreeForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    order = models.PositiveIntegerField(default=0, help_text="Order in which to display this board")

    class MPTTMeta:
        order_insertion_by = ['order', 'name']

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.name} - {self.workspace.name}"

    @property
    def thumbnail(self):
        """Get the first image asset in this board to use as a thumbnail"""
        return self.assets.filter(file_type='IMAGE').first().file.url if self.assets.filter(file_type='IMAGE').first() else None

    @property
    def asset_count(self):
        """Get the number of assets in this board"""
        return self.assets.count()

    @property
    def is_root(self):
        """Check if this is a root board (no parent)"""
        return self.parent is None

    @property
    def level(self):
        """Get the nesting level of this board"""
        return self.get_level()

    def get_ancestors(self):
        """Get all parent boards up to root"""
        return super().get_ancestors()

    def get_descendants(self):
        """Get all descendant boards"""
        return super().get_descendants()

    def get_all_descendants_query(self):
        """
        Get all descendants in a single query
        """
        return self.get_descendants().select_related('parent', 'created_by')

class Asset(models.Model):
    ASSET_TYPES = [
        ('IMAGE', 'Image'),
        ('VIDEO', 'Video'),
        ('DOCUMENT', 'Document'),
        ('AUDIO', 'Audio'),
        ('OTHER', 'Other'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='assets')
    boards = models.ManyToManyField(Board, through='BoardAsset', related_name='assets')
    name = models.CharField(max_length=255)
    file = models.FileField(
        upload_to=workspace_asset_path,
        max_length=500
    )
    file_type = models.CharField(max_length=20, choices=ASSET_TYPES)
    mime_type = models.CharField(max_length=127, null=True, blank=True)
    file_extension = models.CharField(max_length=20, null=True, blank=True)  # jpg, mp4, etc.
    favorite = models.BooleanField(default=False)

    # Image/Video specific
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True)  # in seconds for video/audio
    
    size = models.BigIntegerField()  # File size in bytes
    metadata = models.JSONField(default=dict, blank=True)  # Flexible metadata storage
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    date_created = models.DateTimeField(null=True, blank=True) # When the file was originally created, not when it was uploaded
    date_modified = models.DateTimeField(auto_now=True)
    date_uploaded = models.DateTimeField(auto_now_add=True)

    class Status(models.TextChoices):
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING
    )
    processing_error = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        logger.debug(f"Saving asset: {self.id}, filename: {self.file.name if self.file else 'None'}")
        super().save(*args, **kwargs)
        logger.debug(f"Asset saved: {self.id}")

class Tag(models.Model):
    name = models.CharField(max_length=100)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='tags')
    assets = models.ManyToManyField(Asset, related_name='tags')

    class Meta:
        unique_together = ['name', 'workspace']

    def __str__(self):
        return self.name

class Collection(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='collections')
    assets = models.ManyToManyField(Asset, related_name='collections')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class BoardAsset(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE)
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    position = models.JSONField(null=True)  # for storing layout position if needed

class AssetAnalysis(models.Model):
    """Stores AI-generated analysis results for assets"""
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name='ai_analysis')
    
    # Store the raw analysis JSON data
    raw_analysis = models.JSONField(default=dict)
    
    # Extract specific fields for efficient querying
    labels = models.JSONField(default=list, help_text="AI-detected objects/scenes")
    moderation_labels = models.JSONField(default=list, help_text="Content moderation results")
    
    # Text field for full-text search
    searchable_text = models.TextField(blank=True, help_text="Flattened text of all labels for searching")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Analysis for {self.asset.name}"
    
    def save(self, *args, **kwargs):
        # Extract all label names to a searchable text field
        label_texts = []
        
        # Process regular labels
        for label in self.labels:
            if isinstance(label, dict) and 'name' in label:
                label_texts.append(label['name'].lower())
        
        # Process moderation labels
        for label in self.moderation_labels:
            if isinstance(label, dict) and 'name' in label:
                label_texts.append(label['name'].lower())
        
        # Join all texts with spaces for better search
        self.searchable_text = ' '.join(label_texts)
        
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name_plural = "Asset analyses"

class AIActionChoices(models.TextChoices):
    SPELLING_GRAMMAR = 'spelling_grammar', 'Spelling and Grammar Check'
    COLOR_CONTRAST = 'color_contrast', 'Color Contrast Analysis'
    IMAGE_QUALITY = 'image_quality', 'Image Quality Check'
    IMAGE_ARTIFACTS = 'image_artifacts', 'Image Artifacts Detection'

class AIActionDefinition:
    """
    Static definitions for AI action configurations and metadata.
    This class acts as a registry of all available AI actions.
    """
    
    DEFINITIONS = {
        AIActionChoices.SPELLING_GRAMMAR: {
            'description': 'Checks for spelling and grammar errors in visible text',
            'supported_asset_types': ['DOCUMENT', 'IMAGE'],
            'configuration_schema': {
                'properties': {
                    'language': {
                        'type': 'string',
                        'enum': ['en', 'es', 'fr']
                    },
                    'check_spelling': {
                        'type': 'boolean',
                        'default': True
                    },
                    'check_grammar': {
                        'type': 'boolean',
                        'default': True
                    }
                }
            }
        },
        AIActionChoices.COLOR_CONTRAST: {
            'description': 'Analyzes color contrast for accessibility compliance',
            'supported_asset_types': ['IMAGE'],
            'configuration_schema': {
                'properties': {
                    'wcag_level': {
                        'type': 'string',
                        'enum': ['AA', 'AAA'],
                        'default': 'AA'
                    }
                }
            }
        },
        AIActionChoices.IMAGE_QUALITY: {
            'description': 'Checks for resolution and image quality problems',
            'supported_asset_types': ['IMAGE'],
            'configuration_schema': {
                'properties': {
                    'min_resolution': {
                        'type': 'integer',
                        'default': 1920
                    },
                    'check_compression': {
                        'type': 'boolean',
                        'default': True
                    }
                }
            }
        },
        AIActionChoices.IMAGE_ARTIFACTS: {
            'description': 'Detects pixelation, blurriness, or compression artifacts',
            'supported_asset_types': ['IMAGE'],
            'configuration_schema': {
                'properties': {
                    'sensitivity': {
                        'type': 'string',
                        'enum': ['low', 'medium', 'high'],
                        'default': 'medium'
                    }
                }
            }
        }
    }

    @classmethod
    def get_definition(cls, action_id):
        """Get the definition for a specific action"""
        return cls.DEFINITIONS.get(action_id)

    @classmethod
    def get_supported_actions(cls, asset_type=None):
        """Get list of supported actions, optionally filtered by asset type"""
        if not asset_type:
            return list(cls.DEFINITIONS.keys())
            
        return [
            action_id for action_id, definition in cls.DEFINITIONS.items()
            if asset_type in definition['supported_asset_types']
        ]

class CustomField(models.Model):
    FIELD_TYPES = [
        ('SINGLE_SELECT', 'Single Select'),
        ('MULTI_SELECT', 'Multi Select'),
        ('TEXT', 'Plain Text'),
        ('DATE', 'Date'),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='custom_fields')
    title = models.CharField(max_length=255)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['order']
        unique_together = ['workspace', 'title']

    def __str__(self):
        return f"{self.title} ({self.get_field_type_display()})"

class CustomFieldOption(models.Model):
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE, related_name='options')
    label = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=7, default="#000000")

    class Meta:
        ordering = ['order']
        unique_together = ['field', 'label']

    def __str__(self):
        return f"{self.label} ({self.field.title})"

    @property
    def available_ai_actions(self):
        """Get list of available AI actions for this option"""
        if self.field.field_type != 'SINGLE_SELECT':
            return []
            
        # If this is for an asset field, filter by asset type
        asset_type = None
        if hasattr(self.field, 'asset_type'):
            asset_type = self.field.asset_type
            
        return AIActionDefinition.get_supported_actions(asset_type)

class CustomFieldOptionAIAction(models.Model):
    """Links AI actions to custom field options with their configuration"""
    
    option = models.ForeignKey(CustomFieldOption, on_delete=models.CASCADE, related_name='ai_action_configs')
    action = models.CharField(
        max_length=50,
        choices=AIActionChoices.choices
    )
    is_enabled = models.BooleanField(
        default=True,
        help_text="Whether this action is currently enabled for this option"
    )
    configuration = models.JSONField(
        default=dict,
        help_text="Configuration settings for this action"
    )
    
    class Meta:
        unique_together = ['option', 'action']

    def __str__(self):
        return f"{self.get_action_display()} for {self.option}"

    def get_definition(self):
        """Get the full definition for this action"""
        return AIActionDefinition.get_definition(self.action)

class CustomFieldValue(models.Model):
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()  # Since both Asset and Board use UUID
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Value fields - only one will be used based on field_type
    text_value = models.TextField(null=True, blank=True)
    date_value = models.DateTimeField(null=True, blank=True)
    option_value = models.ForeignKey(
        CustomFieldOption, 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL,
        related_name='field_values'
    )
    multi_options = models.ManyToManyField(
        CustomFieldOption,
        related_name='multi_field_values',
        blank=True
    )

    class Meta:
        unique_together = ['field', 'content_type', 'object_id']

    def __str__(self):
        return f"{self.field.title} value for {self.content_object}"

    def get_value(self):
        """Get the appropriate value based on field type"""
        if self.field.field_type == 'SINGLE_SELECT':
            return self.option_value
        elif self.field.field_type == 'MULTI_SELECT':
            return self.multi_options.all()
        elif self.field.field_type == 'DATE':
            return self.date_value
        return self.text_value

class AIActionResult(models.Model):
    """Stores results of AI action executions"""
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed')
    ]

    field_value = models.ForeignKey(CustomFieldValue, on_delete=models.CASCADE, related_name='ai_results')
    action = models.CharField(
        max_length=50,
        choices=AIActionChoices.choices
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    result = models.JSONField(
        default=dict,
        help_text="Results of the AI analysis"
    )
    error_message = models.TextField(
        null=True, 
        blank=True,
        help_text="Error message if the action failed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_action_display()} result for {self.field_value}"

    def get_definition(self):
        """Get the full definition for this action"""
        return AIActionDefinition.get_definition(self.action)


# Notification System Models

class EventType(models.TextChoices):
    """Event types for notifications"""
    # Comments
    COMMENT_ON_FOLLOWED_BOARD_ASSET = 'comment_on_followed_board_asset', 'New comments on assets in followed boards'
    MENTION_IN_COMMENT = 'mention_in_comment', '@ mentions on assets'
    REPLY_TO_THREAD = 'reply_to_thread', 'Replies to threads you\'ve started or are in'
    
    # Activity
    SUB_BOARD_CREATED = 'sub_board_created', 'New sub-boards created in followed boards'
    ASSET_UPLOADED_TO_FOLLOWED_BOARD = 'asset_uploaded_to_followed_board', 'New items uploaded to followed boards'
    FIELD_CHANGE_IN_FOLLOWED_BOARD = 'field_change_in_followed_board', 'Custom field changes to followed boards & their assets'
    
    # Legacy/Additional events (keep for future use)
    AI_CHECK_COMPLETED = 'ai_check_completed', 'AI Check Completed'
    ASSET_FAVORITED = 'asset_favorited', 'Asset Favorited'


class BoardFollower(models.Model):
    """Users following specific boards for notifications"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='followed_boards')
    board = models.ForeignKey('Board', on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Include sub-boards in notifications (e.g., if following parent, get notified about sub-boards)
    include_sub_boards = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['user', 'board']
        indexes = [
            models.Index(fields=['user', 'board']),
        ]

    def __str__(self):
        return f"{self.user.email} follows {self.board.name}"


class Comment(models.Model):
    """Comments that can be attached to any object (Asset, Board, etc.)"""
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comments')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # For nested comments/replies
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')
    
    # Store mentioned users for @ mentions
    mentioned_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, 
        blank=True, 
        related_name='mentioned_in_comments'
    )

    # Annotation fields
    annotation_type = models.CharField(
        max_length=20,
        choices=[
            ('NONE', 'No annotation'),
            ('POINT', 'Point annotation'),
            ('AREA', 'Area annotation')
        ],
        default='NONE'
    )
    # Coordinates and dimensions for annotations
    x = models.FloatField(null=True, blank=True)
    y = models.FloatField(null=True, blank=True)
    width = models.FloatField(null=True, blank=True)
    height = models.FloatField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['created_at']),
            models.Index(fields=['author']),
        ]

    def __str__(self):
        return f"Comment by {self.author.email} on {self.content_object}"

    @property
    def is_reply(self):
        return self.parent is not None
    
    def get_thread_participants(self):
        """Get all users who have participated in this comment thread"""
        if self.parent:
            # If this is a reply, get participants from the root comment
            root_comment = self.parent
            while root_comment.parent:
                root_comment = root_comment.parent
        else:
            root_comment = self
        
        # Get all users who have commented in this thread
        thread_comments = Comment.objects.filter(
            models.Q(id=root_comment.id) | models.Q(parent=root_comment)
        )
        participants = set()
        for comment in thread_comments:
            participants.add(comment.author)
        return participants

    def get_annotation_data(self):
        """Get the annotation data in a structured format"""
        if self.annotation_type == 'NONE':
            return None
        elif self.annotation_type == 'POINT':
            return {
                'type': 'point',
                'x': self.x,
                'y': self.y
            }
        elif self.annotation_type == 'AREA':
            return {
                'type': 'area',
                'x': self.x,
                'y': self.y,
                'width': self.width,
                'height': self.height
            }
        return None


class Subscription(models.Model):
    """User subscriptions to receive notifications for specific objects"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_subscriptions')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # JSON list of event types the user wants to be notified about
    event_types = models.JSONField(
        default=list,
        help_text="List of event types to receive notifications for"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'content_type', 'object_id']
        indexes = [
            models.Index(fields=['user', 'content_type', 'object_id']),
        ]

    def __str__(self):
        return f"{self.user.email} subscribed to {self.content_object}"

    def is_subscribed_to_event(self, event_type):
        """Check if user is subscribed to a specific event type"""
        return event_type in self.event_types


class NotificationPreference(models.Model):
    """User preferences for how they want to receive notifications"""
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_preferences')
    event_type = models.CharField(max_length=60, choices=EventType.choices)
    
    # Separate boolean fields for each notification channel
    in_app_enabled = models.BooleanField(default=True, help_text="Receive in-app notifications")
    email_enabled = models.BooleanField(default=True, help_text="Receive email notifications")
    # Future channels can be added here:
    # sms_enabled = models.BooleanField(default=False, help_text="Receive SMS notifications")
    # slack_enabled = models.BooleanField(default=False, help_text="Receive Slack notifications")
    
    # Email batching preferences
    email_frequency = models.PositiveIntegerField(
        default=5,
        help_text="Minutes between email notifications (for batching)"
    )
    
    class Meta:
        unique_together = ['user', 'event_type']

    def __str__(self):
        channels = []
        if self.in_app_enabled:
            channels.append("in-app")
        if self.email_enabled:
            channels.append("email")
        channel_str = ", ".join(channels) if channels else "disabled"
        return f"{self.user.email} - {self.get_event_type_display()}: {channel_str}"

    @property
    def has_any_channel_enabled(self):
        """Check if any notification channel is enabled"""
        return self.in_app_enabled or self.email_enabled

    @classmethod
    def get_user_preference(cls, user, event_type):
        """Get user's preference for a specific event type, with defaults"""
        try:
            return cls.objects.get(user=user, event_type=event_type)
        except cls.DoesNotExist:
            # Return default preference (both channels enabled)
            return cls(
                user=user, 
                event_type=event_type, 
                in_app_enabled=True, 
                email_enabled=True, 
                email_frequency=5
            )


class EmailBatch(models.Model):
    """Batched email notifications to reduce email spam"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    notifications = models.ManyToManyField('notifications.Notification', related_name='email_batches')
    
    scheduled_for = models.DateTimeField()
    sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'scheduled_for']),
            models.Index(fields=['sent', 'scheduled_for']),
        ]

    def __str__(self):
        return f"Email batch for {self.user.email} - {self.notifications.count()} notifications"
