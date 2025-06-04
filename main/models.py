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
