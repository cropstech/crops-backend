from ninja import Schema, ModelSchema
from typing import List, Optional
from datetime import datetime
from uuid import UUID
from pydantic import ConfigDict, BaseModel, Field
from django_paddle_billing.models import Product, Subscription, Transaction
from os.path import dirname
from users.api import UserSchema

class WorkspaceCreateSchema(Schema):
    name: str
    avatar: Optional[str] = None
    description: Optional[str] = None

class WorkspaceDataSchema(Schema):
    id: str
    name: str
    avatar: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    user_role: Optional[str] = None
    subscription_details: Optional[dict] = None

    @staticmethod
    def resolve_id(obj):
        return str(obj.id)
    
    @staticmethod
    def resolve_subscription_details(obj):
        return obj.subscription_details
    
class WorkspaceUpdateSchema(Schema):
    name: Optional[str] = None
    avatar: Optional[str] = None
    description: Optional[str] = None
    
class WorkspaceUpdateForm(Schema):
    name: Optional[str] = None
    description: Optional[str] = None

class WorkspaceMemberSchema(Schema):
    id: int
    user_id: int
    role: str
    joined_at: datetime
    name: str
    email: str
    
    model_config = ConfigDict(
        from_attributes=True
    )

    @staticmethod
    def resolve_id(obj):
        return str(obj.id)
    
    @staticmethod
    def resolve_user_id(obj):
        return str(obj.user.id)

    @staticmethod
    def resolve_name(obj):
        return obj.user.get_full_name() or obj.user.username or obj.user.email
        
    @staticmethod
    def resolve_email(obj):
        return obj.user.email

class WorkspaceMemberUpdateSchema(Schema):
    role: str

class WorkspaceInviteSchema(Schema):
    email: str
    role: str
    expires_at: Optional[datetime] = None

class ShareLinkSchema(Schema):
    content_type: str  # e.g., 'asset', 'collection'
    object_id: int
    permission: str
    expires_at: Optional[datetime] = None
    password: Optional[str] = None
    max_uses: Optional[int] = None


class WorkspaceInviteIn(Schema):
    email: str
    role: str
    expires_at: Optional[datetime] = None

class WorkspaceInviteOut(Schema):
    id: int
    email: str
    role: str
    expires_at: datetime
    
    model_config = ConfigDict(
        from_attributes=True
    )
    
class InviteAcceptSchema(Schema):
    token: str
    
class AssetSchema(Schema):
    id: UUID
    file: str
    url: str
    directory: str  # New field for the path without filename
    size: int
    status: str
    date_created: Optional[datetime]
    date_modified: datetime
    date_uploaded: datetime
    name: Optional[str] = None
    file_type: Optional[str] = None
    file_extension: Optional[str] = None
    mime_type: Optional[str] = None
    metadata: Optional[dict] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    processing_error: Optional[str] = None
    workspace_id: UUID
    created_by: Optional[UserSchema] = None
    favorite: bool
    model_config = ConfigDict(
        from_attributes=True
    )

    @staticmethod
    def resolve_url(obj):
        if obj.file:
            return obj.file.url
        return None

    @staticmethod
    def resolve_file(obj):
        if obj.file:
            return obj.file.name
        return None

    @staticmethod
    def resolve_directory(obj):
        """Get the directory path without the filename"""
        if obj.file:
            # Get the full path and remove the filename
            return dirname(obj.file.name)
        return None

class SubscriptionSchema(ModelSchema):
    class Meta:
        model = Subscription
        fields = "__all__"

class ProductSchema(ModelSchema):
    class Meta:
        model = Product
        fields = ["id", "name", "status", "created_at", "updated_at"]

class ProductSubscriptionSchema(Schema):
    products: list[ProductSchema] = []
    subscriptions: list[SubscriptionSchema] = []

class PlanOut(Schema):
    id: str
    name: str
    description: Optional[str]
    price_id: str
    unit_price: float
    billing_period: Optional[str]
    features: List[str]

class TransactionSchema(ModelSchema):
    class Meta:
        model = Transaction
        fields = "__all__"

class BoardCreateSchema(Schema):
    name: str
    description: Optional[str] = None
    parent_id: Optional[UUID] = None

class BoardUpdateSchema(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[UUID] = None

class BoardOutSchema(Schema):
    id: UUID
    name: str
    description: Optional[str]
    workspace_id: UUID
    parent_id: Optional[UUID]
    created_at: datetime
    created_by_id: Optional[int]
    is_root: bool
    level: int
    child_count: int
    
    model_config = ConfigDict(
        from_attributes=True
    )

    @staticmethod
    def resolve_child_count(obj):
        return obj.children.count()

class DownloadInitiateSchema(Schema):
    asset_id: UUID
    use_multipart: bool = False
    part_size: Optional[int] = None  # Size in bytes for each part in multipart download

class DownloadPartSchema(Schema):
    part_number: int
    start_byte: int
    end_byte: int
    url: str
    expires_at: datetime

class DownloadResponseSchema(Schema):
    download_id: str
    asset_id: UUID
    total_size: int
    total_parts: Optional[int] = None
    parts: Optional[List[DownloadPartSchema]] = None
    direct_url: Optional[str] = None  # For single file downloads
    expires_at: datetime

class AssetBulkTagsSchema(Schema):
    asset_ids: List[UUID]
    tags: List[str]

class AssetBulkFavoriteSchema(Schema):
    asset_ids: List[UUID]
    favorite: bool

class AssetBulkBoardSchema(Schema):
    asset_ids: List[UUID]

class AssetBulkMoveSchema(Schema):
    asset_ids: List[UUID]
    destination_type: str  # 'workspace' or 'board'
    destination_id: UUID

class AssetBulkDeleteSchema(Schema):
    asset_ids: List[UUID]