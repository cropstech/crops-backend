from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
import uuid
from django.utils import timezone
from django.conf import settings

def workspace_avatar_path(instance, filename):
    """Generate upload path for workspace avatars"""
    ext = filename.split('.')[-1].lower()
    return f'media/workspaces/{instance.id}/avatars/{uuid.uuid4()}.{ext}'

def workspace_asset_path(instance, filename):
    """Generate upload path for workspace assets"""
    return f'media/workspaces/{instance.workspace.id}/assets/{instance.id}/{filename}'

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
    def __str__(self):
        return self.name


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
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
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
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to='assets/')
    file_type = models.CharField(max_length=20, choices=ASSET_TYPES)
    mime_type = models.CharField(max_length=127, null=True, blank=True)
    file_extension = models.CharField(max_length=20, null=True, blank=True)  # jpg, mp4, etc.

    # Image/Video specific
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True)  # in seconds for video/audio
    
    size = models.BigIntegerField()  # File size in bytes
    metadata = models.JSONField(default=dict, blank=True)  # Flexible metadata storage
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    date_created = models.DateTimeField(null=True)
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
