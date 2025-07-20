from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import storages
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
        storage=storages["staticfiles"],
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
    VIEW_TYPES = [
        ('GALLERY', 'Gallery'),
        ('KANBAN', 'Kanban'),
        ('TABLE', 'Table'),
    ]
    
    SORT_CHOICES = [
        ('custom', 'Custom order (drag and drop)'),
        ('-date_uploaded', 'Date uploaded (newest first)'),
        ('date_uploaded', 'Date uploaded (oldest first)'),
        ('-date_created', 'Date created (newest first)'),
        ('date_created', 'Date created (oldest first)'),
        ('-date_modified', 'Date modified (newest first)'),
        ('date_modified', 'Date modified (oldest first)'),
        ('name', 'Name (A-Z)'),
        ('-name', 'Name (Z-A)'),
        ('-size', 'File size (largest first)'),
        ('size', 'File size (smallest first)'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='boards')
    parent = TreeForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    order = models.PositiveIntegerField(default=0, help_text="Order in which to display this board")
    default_view = models.CharField(
        max_length=20,
        choices=VIEW_TYPES,
        default='GALLERY',
        help_text="Default view type for this board"
    )
    kanban_group_by_field = models.ForeignKey(
        'CustomField',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Custom field to group by when using kanban view (should be a single-select field)"
    )
    default_sort = models.CharField(
        max_length=30,
        choices=SORT_CHOICES,
        default='-date_uploaded',
        help_text="Default sort order for assets in this board"
    )

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
    
    def clean(self):
        """Validate board configuration"""
        from django.core.exceptions import ValidationError
        
        # If kanban_group_by_field is set, it should be a single-select field
        if self.kanban_group_by_field:
            if self.kanban_group_by_field.field_type != 'SINGLE_SELECT':
                raise ValidationError({
                    'kanban_group_by_field': 'Kanban grouping field must be a single-select field.'
                })
            
            # The field should belong to the same workspace
            if self.kanban_group_by_field.workspace != self.workspace:
                raise ValidationError({
                    'kanban_group_by_field': 'Kanban grouping field must belong to the same workspace as the board.'
                })
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
    
    def reorder_assets(self, asset_order_list):
        """
        Reorder assets in this board based on a list of asset IDs.
        Used for custom drag-and-drop ordering.
        
        Args:
            asset_order_list: List of asset UUIDs in the desired order
        """
        for index, asset_id in enumerate(asset_order_list):
            try:
                board_asset = BoardAsset.objects.get(board=self, asset_id=asset_id)
                board_asset.order = index
                board_asset.save()
            except BoardAsset.DoesNotExist:
                # Asset not in this board, skip
                continue
    
    def get_effective_kanban_group_by_field(self):
        """
        Get the kanban grouping field, with smart defaulting if none is explicitly set.
        Returns the explicitly set field, or finds a SINGLE_SELECT field in the workspace,
        preferring one titled "Status".
        """
        # If explicitly set, return it
        if self.kanban_group_by_field:
            return self.kanban_group_by_field
        
        # Smart defaulting: look for SINGLE_SELECT fields in the workspace
        single_select_fields = CustomField.objects.filter(
            workspace=self.workspace,
            field_type='SINGLE_SELECT'
        ).order_by('title')
        
        # First, try to find a field titled "Status" (case insensitive)
        status_field = single_select_fields.filter(title__iexact='status').first()
        if status_field:
            return status_field
        
        # Otherwise, return the first SINGLE_SELECT field found
        return single_select_fields.first()

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
    description = models.TextField(blank=True, null=True)
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
    order = models.PositiveIntegerField(default=0, help_text="Manual ordering position within this board")
    
    class Meta:
        ordering = ['order', 'added_at']
        unique_together = ['board', 'asset']

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
    GRAMMAR = 'grammar', 'Grammar Check'
    IMAGE_QUALITY = 'image_quality', 'Image Quality Check'
    COLOR_CONTRAST = 'color_contrast', 'Color Contrast Analysis'
    COLOR_BLINDNESS = 'color_blindness', 'Color Blindness Analysis'
    FONT_SIZE_DETECTION = 'font_size_detection', 'Font Size Detection'
    TEXT_OVERFLOW = 'text_overflow', 'Text Overflow Detection'
    PLACEHOLDER_DETECTION = 'placeholder_detection', 'Placeholder Text Detection'
    REPEATED_TEXT = 'repeated_text', 'Repeated Text Detection'

class AIActionDefinition:
    """
    Static definitions for AI action configurations and metadata.
    This class acts as a registry of all available AI actions.
    """
    
    # Full language metadata for grammar checking
    LANGUAGE_METADATA = [
        {"name": "German", "code": "de", "longCode": "de"},
        {"name": "German (Germany)", "code": "de", "longCode": "de-DE"},
        {"name": "German (Austria)", "code": "de", "longCode": "de-AT"},
        {"name": "German (Swiss)", "code": "de", "longCode": "de-CH"},
        {"name": "English", "code": "en", "longCode": "en"},
        {"name": "English (US)", "code": "en", "longCode": "en-US"},
        {"name": "English (Australian)", "code": "en", "longCode": "en-AU"},
        {"name": "English (GB)", "code": "en", "longCode": "en-GB"},
        {"name": "English (Canadian)", "code": "en", "longCode": "en-CA"},
        {"name": "English (New Zealand)", "code": "en", "longCode": "en-NZ"},
        {"name": "English (South African)", "code": "en", "longCode": "en-ZA"},
        {"name": "Spanish", "code": "es", "longCode": "es"},
        {"name": "Spanish (voseo)", "code": "es", "longCode": "es-AR"},
        {"name": "French", "code": "fr", "longCode": "fr"},
        {"name": "French (Canada)", "code": "fr", "longCode": "fr-CA"},
        {"name": "French (Switzerland)", "code": "fr", "longCode": "fr-CH"},
        {"name": "French (Belgium)", "code": "fr", "longCode": "fr-BE"},
        {"name": "Dutch", "code": "nl", "longCode": "nl"},
        {"name": "Dutch (Belgium)", "code": "nl", "longCode": "nl-BE"},
        {"name": "Portuguese (Angola preAO)", "code": "pt", "longCode": "pt-AO"},
        {"name": "Portuguese (Brazil)", "code": "pt", "longCode": "pt-BR"},
        {"name": "Portuguese (Moçambique preAO)", "code": "pt", "longCode": "pt-MZ"},
        {"name": "Portuguese (Portugal)", "code": "pt", "longCode": "pt-PT"},
        {"name": "Portuguese", "code": "pt", "longCode": "pt"},
        {"name": "Arabic", "code": "ar", "longCode": "ar"},
        {"name": "Asturian", "code": "ast", "longCode": "ast-ES"},
        {"name": "Belarusian", "code": "be", "longCode": "be-BY"},
        {"name": "Breton", "code": "br", "longCode": "br-FR"},
        {"name": "Catalan", "code": "ca", "longCode": "ca-ES"},
        {"name": "Catalan (Valencian)", "code": "ca", "longCode": "ca-ES-valencia"},
        {"name": "Catalan (Balearic)", "code": "ca", "longCode": "ca-ES-balear"},
        {"name": "Danish", "code": "da", "longCode": "da-DK"},
        {"name": "Simple German", "code": "de-DE-x-simple-language", "longCode": "de-DE-x-simple-language"},
        {"name": "Greek", "code": "el", "longCode": "el-GR"},
        {"name": "Esperanto", "code": "eo", "longCode": "eo"},
        {"name": "Persian", "code": "fa", "longCode": "fa"},
        {"name": "Irish", "code": "ga", "longCode": "ga-IE"},
        {"name": "Galician", "code": "gl", "longCode": "gl-ES"},
        {"name": "Italian", "code": "it", "longCode": "it"},
        {"name": "Japanese", "code": "ja", "longCode": "ja-JP"},
        {"name": "Khmer", "code": "km", "longCode": "km-KH"},
        {"name": "Polish", "code": "pl", "longCode": "pl-PL"},
        {"name": "Romanian", "code": "ro", "longCode": "ro-RO"},
        {"name": "Russian", "code": "ru", "longCode": "ru-RU"},
        {"name": "Slovak", "code": "sk", "longCode": "sk-SK"},
        {"name": "Slovenian", "code": "sl", "longCode": "sl-SI"},
        {"name": "Swedish", "code": "sv", "longCode": "sv"},
        {"name": "Tamil", "code": "ta", "longCode": "ta-IN"},
        {"name": "Tagalog", "code": "tl", "longCode": "tl-PH"},
        {"name": "Ukrainian", "code": "uk", "longCode": "uk-UA"},
        {"name": "Chinese", "code": "zh", "longCode": "zh-CN"},
        {"name": "Crimean Tatar", "code": "crh", "longCode": "crh-UA"},
        {"name": "Norwegian (Bokmål)", "code": "nb", "longCode": "nb"},
        {"name": "Norwegian (Bokmål)", "code": "no", "longCode": "no"},
        {"name": "Dutch", "code": "nl", "longCode": "nl-NL"},
        {"name": "Simple German", "code": "de-DE-x-simple-language", "longCode": "de-DE-x-simple-language-DE"},
        {"name": "Spanish", "code": "es", "longCode": "es-ES"},
        {"name": "Italian", "code": "it", "longCode": "it-IT"},
        {"name": "Persian", "code": "fa", "longCode": "fa-IR"},
        {"name": "Swedish", "code": "sv", "longCode": "sv-SE"},
        {"name": "German", "code": "de", "longCode": "de-LU"},
        {"name": "French", "code": "fr", "longCode": "fr-FR"}
    ]
    
    DEFINITIONS = {
        AIActionChoices.GRAMMAR: {
            'description': 'Checks for grammar errors in visible text',
            'supported_asset_types': ['DOCUMENT', 'IMAGE'],
            'configuration_schema': {
                'properties': {
                    'language': {
                        'type': 'string',
                        'enum': [
                            'ar', 'ast-ES', 'be-BY', 'br-FR', 'ca-ES', 'ca-ES-valencia', 'ca-ES-balear',
                            'crh-UA', 'da-DK', 'de', 'de-DE', 'de-AT', 'de-CH', 'de-LU', 
                            'de-DE-x-simple-language', 'de-DE-x-simple-language-DE', 'el-GR', 'en', 
                            'en-US', 'en-AU', 'en-GB', 'en-CA', 'en-NZ', 'en-ZA', 'eo', 'es', 
                            'es-AR', 'es-ES', 'fa', 'fa-IR', 'fr', 'fr-CA', 'fr-CH', 'fr-BE', 
                            'fr-FR', 'ga-IE', 'gl-ES', 'it', 'it-IT', 'ja-JP', 'km-KH', 'nb', 
                            'nl', 'nl-BE', 'nl-NL', 'no', 'pl-PL', 'pt', 'pt-AO', 'pt-BR', 
                            'pt-MZ', 'pt-PT', 'ro-RO', 'ru-RU', 'sk-SK', 'sl-SI', 'sv', 'sv-SE', 
                            'ta-IN', 'tl-PH', 'uk-UA', 'zh-CN'
                        ],
                        'default': 'en-US',
                        'description': 'Language code for grammar checking. Use AIActionDefinition.get_language_choices() for full language metadata.'
                    }
                }
            }
        },
        AIActionChoices.IMAGE_QUALITY: {
            'description': 'Checks for resolution and image quality problems',
            'supported_asset_types': ['IMAGE'],
            'configuration_schema': {
                'properties': {
                    'enabled': {
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
                    'enabled': {
                        'type': 'boolean',
                        'default': True
                    }
                }
            }
        },
        AIActionChoices.COLOR_BLINDNESS: {
            'description': 'Analyzes content for color blindness accessibility',
            'supported_asset_types': ['IMAGE'],
            'configuration_schema': {
                'properties': {
                    'enabled': {
                        'type': 'boolean',
                        'default': True
                    }
                }
            }
        },
        AIActionChoices.FONT_SIZE_DETECTION: {
            'description': 'Detects and analyzes font sizes in text',
            'supported_asset_types': ['IMAGE', 'DOCUMENT'],
            'configuration_schema': {
                'properties': {
                    'enabled': {
                        'type': 'boolean',
                        'default': True
                    }
                }
            }
        },
        AIActionChoices.TEXT_OVERFLOW: {
            'description': 'Detects text that overflows its container',
            'supported_asset_types': ['IMAGE', 'DOCUMENT'],
            'configuration_schema': {
                'properties': {
                    'enabled': {
                        'type': 'boolean',
                        'default': True
                    }
                }
            }
        },
        AIActionChoices.PLACEHOLDER_DETECTION: {
            'description': 'Detects placeholder text that should be replaced',
            'supported_asset_types': ['IMAGE', 'DOCUMENT'],
            'configuration_schema': {
                'properties': {
                    'enabled': {
                        'type': 'boolean',
                        'default': True
                    }
                }
            }
        },
        AIActionChoices.REPEATED_TEXT: {
            'description': 'Detects repeated or duplicated text content',
            'supported_asset_types': ['IMAGE', 'DOCUMENT'],
            'configuration_schema': {
                'properties': {
                    'enabled': {
                        'type': 'boolean',
                        'default': True
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

    @classmethod
    def get_language_choices(cls):
        """Get all available language choices for grammar checking"""
        return cls.LANGUAGE_METADATA

    @classmethod
    def get_language_by_code(cls, code):
        """Get language metadata by longCode"""
        for lang in cls.LANGUAGE_METADATA:
            if lang['longCode'] == code:
                return lang
        return None

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
    
    # Track if this was auto-followed (for analytics and UI purposes)
    auto_followed = models.BooleanField(default=False, help_text="Whether this was automatically created by the system")
    
    class Meta:
        unique_together = ['user', 'board']
        indexes = [
            models.Index(fields=['user', 'board']),
        ]

    def __str__(self):
        return f"{self.user.email} follows {self.board.name}"


class BoardExplicitUnfollow(models.Model):
    """Track when users explicitly unfollow boards to prevent auto re-following"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='board_explicit_unfollows')
    board = models.ForeignKey('Board', on_delete=models.CASCADE, related_name='explicit_unfollows')
    unfollowed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'board']
        indexes = [
            models.Index(fields=['user', 'board']),
        ]

    def __str__(self):
        return f"{self.user.email} explicitly unfollowed {self.board.name}"


class Comment(models.Model):
    """Comments that can be attached to any object (Asset, Board, etc.)"""
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Board context - null means comment appears in "all assets" view
    board = models.ForeignKey('Board', on_delete=models.CASCADE, null=True, blank=True, 
                             help_text="Board context for this comment. Null means global 'all assets' comment.")
    
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comments', null=True, blank=True)
    text = models.TextField()
    comment_type = models.CharField(max_length=50, default='USER', help_text="Type of comment (USER, AI_ANALYSIS, SYSTEM, etc.)")
    severity = models.CharField(
        max_length=20,
        choices=[
            ('high', 'High'),
            ('medium', 'Medium'),
            ('low', 'Low'),
            ('info', 'Info')
        ],
        null=True,
        blank=True,
        help_text="Severity level for AI analysis comments"
    )
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
            models.Index(fields=['content_type', 'object_id', 'board']),  # Board-scoped queries
            models.Index(fields=['board', 'created_at']),  # Board timeline
            models.Index(fields=['created_at']),
            models.Index(fields=['author']),
        ]

    def __str__(self):
        author_display = self.author.email if self.author else "Crops System"
        return f"Comment by {author_display} on {self.content_object}"

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
            if comment.author:  # Only add non-None authors
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


class UserNotificationPreference(models.Model):
    """User preferences for all notification types in a single model"""
    
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='notification_preference'
    )
    
    # JSON field storing preferences for all event types
    # Structure: {
    #   "event_type": {
    #     "in_app_enabled": bool,
    #     "email_enabled": bool
    #   }
    # }
    event_preferences = models.JSONField(default=dict)
    
    # Global email batching preference
    email_frequency = models.PositiveIntegerField(
        default=5,
        help_text="Minutes between email notifications (for batching)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Notification preferences for {self.user.email}"

    @classmethod
    def get_or_create_for_user(cls, user):
        """Get or create notification preferences for a user with defaults"""
        preference, created = cls.objects.get_or_create(
            user=user,
            defaults={
                'event_preferences': cls.get_default_preferences(),
                'email_frequency': 5
            }
        )
        
        # If preferences exist but are missing some event types, update them
        if not created:
            current_prefs = preference.event_preferences
            default_prefs = cls.get_default_preferences()
            
            # Add any missing event types with default values
            updated = False
            for event_type, default_settings in default_prefs.items():
                if event_type not in current_prefs:
                    current_prefs[event_type] = default_settings
                    updated = True
            
            if updated:
                preference.event_preferences = current_prefs
                preference.save()
        
        return preference

    @staticmethod
    def get_default_preferences():
        """Get default preferences for all event types"""
        defaults = {}
        for event_type, _ in EventType.choices:
            defaults[event_type] = {
                'in_app_enabled': True,
                'email_enabled': True
            }
        return defaults

    def get_preference_for_event(self, event_type):
        """Get preference settings for a specific event type"""
        return self.event_preferences.get(event_type, {
            'in_app_enabled': True,
            'email_enabled': True
        })

    def is_in_app_enabled(self, event_type):
        """Check if in-app notifications are enabled for an event type"""
        return self.get_preference_for_event(event_type).get('in_app_enabled', True)

    def is_email_enabled(self, event_type):
        """Check if email notifications are enabled for an event type"""
        return self.get_preference_for_event(event_type).get('email_enabled', True)

    def update_event_preference(self, event_type, in_app_enabled=None, email_enabled=None):
        """Update preference for a specific event type"""
        if event_type not in self.event_preferences:
            self.event_preferences[event_type] = {}
        
        if in_app_enabled is not None:
            self.event_preferences[event_type]['in_app_enabled'] = in_app_enabled
        if email_enabled is not None:
            self.event_preferences[event_type]['email_enabled'] = email_enabled
        
        self.save()

    def get_all_preferences_display(self):
        """Get all preferences in a display-friendly format"""
        preferences = []
        for event_type, display_name in EventType.choices:
            pref = self.get_preference_for_event(event_type)
            preferences.append({
                'event_type': event_type,
                'display_name': display_name,
                'in_app_enabled': pref.get('in_app_enabled', True),
                'email_enabled': pref.get('email_enabled', True)
            })
        return preferences


# Keep the old NotificationPreference model for backward compatibility during migration
class NotificationPreference(models.Model):
    """DEPRECATED: Use UserNotificationPreference instead"""
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='old_notification_preferences')
    event_type = models.CharField(max_length=60, choices=EventType.choices)
    
    # Separate boolean fields for each notification channel
    in_app_enabled = models.BooleanField(default=True, help_text="Receive in-app notifications")
    email_enabled = models.BooleanField(default=True, help_text="Receive email notifications")
    
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
        """DEPRECATED: Use UserNotificationPreference.get_or_create_for_user instead"""
        # For backward compatibility, delegate to the new model
        user_pref = UserNotificationPreference.get_or_create_for_user(user)
        event_pref = user_pref.get_preference_for_event(event_type)
        
        # Return a mock object that behaves like the old model
        class MockPreference:
            def __init__(self, user, event_type, in_app_enabled, email_enabled, email_frequency):
                self.user = user
                self.event_type = event_type
                self.in_app_enabled = in_app_enabled
                self.email_enabled = email_enabled
                self.email_frequency = email_frequency
            
            @property
            def has_any_channel_enabled(self):
                return self.in_app_enabled or self.email_enabled
        
        return MockPreference(
            user=user,
            event_type=event_type,
            in_app_enabled=event_pref.get('in_app_enabled', True),
            email_enabled=event_pref.get('email_enabled', True),
            email_frequency=user_pref.email_frequency
        )

    @classmethod
    def ensure_user_has_all_preferences(cls, user):
        """DEPRECATED: Use UserNotificationPreference.get_or_create_for_user instead"""
        UserNotificationPreference.get_or_create_for_user(user)


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


class AssetCheckerAnalysis(models.Model):
    """Stores Asset Checker Lambda service analysis results"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    check_id = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    s3_bucket = models.CharField(max_length=255)
    s3_key = models.CharField(max_length=1024)
    webhook_received = models.BooleanField(default=False)
    results = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    
    # Board context - null means analysis was triggered from "all assets" view
    board = models.ForeignKey('Board', on_delete=models.CASCADE, null=True, blank=True,
                             help_text="Board context that triggered this analysis. Null means global analysis.")
    
    # Tracking metadata
    use_webhook = models.BooleanField(default=True)
    webhook_url = models.URLField(null=True, blank=True)
    callback_url = models.URLField(null=True, blank=True)
    ai_action_result_id = models.IntegerField(null=True, blank=True, help_text="ID of the AIActionResult that triggered this analysis")
    
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['check_id']),
            models.Index(fields=['status']),
            models.Index(fields=['board', 'status']),  # Board-scoped analysis queries
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Asset Checker Analysis {self.check_id} - {self.status}"
    
    @property
    def is_complete(self):
        return self.status in ['completed', 'failed']
    
    @property
    def is_successful(self):
        return self.status == 'completed' and self.results is not None
