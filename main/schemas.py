from ninja import Schema, ModelSchema
from typing import List, Optional, Union, Dict
from datetime import datetime
from uuid import UUID
from pydantic import ConfigDict, BaseModel, Field
from django_paddle_billing.models import Product, Subscription, Transaction
from os.path import dirname
from users.api import UserSchema
from django.db import models

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
    parent_id: Optional[Union[UUID, str]] = None

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
    children: Optional[List['BoardOutSchema']] = None
    thumbnail: Optional[str] = None
    
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

class AssetBulkDownloadSchema(Schema):
    asset_ids: List[UUID]

class BulkDownloadResponseSchema(Schema):
    download_url: str
    expires_at: datetime
    asset_count: int
    zip_size: int

    
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
    boards: Optional[List[BoardOutSchema]] = None
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
    
    @staticmethod
    def resolve_custom_fields(obj):
        return obj.custom_fields.all()
    
    @staticmethod
    def resolve_custom_field_values(obj):
        return obj.custom_field_values.all()

class BoardReorderSchema(Schema):
    board_id: UUID
    new_order: int

class BoardReorderRequestSchema(Schema):
    items: List[BoardReorderSchema]

class UploadPartSchema(Schema):
    part_number: int
    start_byte: int
    end_byte: int
    url: str
    expires_at: datetime

class UploadResponseSchema(Schema):
    upload_id: str
    key: str
    asset_id: Optional[UUID] = None  # Asset ID for tracking processing status
    total_parts: Optional[int] = None
    parts: Optional[List[UploadPartSchema]] = None
    direct_url: Optional[str] = None  # For single file uploads
    expires_at: datetime

class UploadCompleteSchema(Schema):
    upload_id: str
    key: str
    parts: List[Dict]  # List of parts with ETags

class CustomFieldSchema(Schema):
    id: int
    title: str
    field_type: str
    description: Optional[str] = None
    order: int
    workspace_id: UUID
    options: List['CustomFieldOptionSchema'] = []

    model_config = ConfigDict(
        from_attributes=True
    )

class CustomFieldOptionSchema(Schema):
    id: int
    label: str
    order: int
    color: str
    field_id: int
    ai_actions: List['CustomFieldOptionAIActionSchema'] = []

    model_config = ConfigDict(
        from_attributes=True
    )

    @staticmethod
    def resolve_ai_actions(obj):
        """Get AI actions from the ai_action_configs relation"""
        return list(obj.ai_action_configs.all()) if hasattr(obj, 'ai_action_configs') else []

class CustomFieldOptionAIActionSchema(Schema):
    id: int
    action: str
    action_display: str
    is_enabled: bool
    configuration: Dict = {}
    option_id: int

    model_config = ConfigDict(
        from_attributes=True
    )

    @staticmethod
    def resolve_action_display(obj):
        return obj.get_action_display()

class CustomFieldValueSchema(Schema):
    id: int
    field_id: int
    content_type: str
    object_id: UUID
    text_value: Optional[str] = None
    date_value: Optional[datetime] = None
    option_value: Optional[CustomFieldOptionSchema] = None
    multi_options: List[CustomFieldOptionSchema] = []
    value_display: str

    model_config = ConfigDict(
        from_attributes=True
    )

    @staticmethod
    def resolve_content_type(obj):
        return obj.content_type.model

    @staticmethod
    def resolve_value_display(obj):
        value = obj.get_value()
        if isinstance(value, models.QuerySet):
            return ', '.join(str(v) for v in value)
        return str(value) if value else ''

class AIActionResultSchema(Schema):
    id: int
    action: str
    action_display: str
    status: str
    result: Dict
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    field_value_id: int

    model_config = ConfigDict(
        from_attributes=True
    )

    @staticmethod
    def resolve_action_display(obj):
        return obj.get_action_display()

# Input schemas
class CustomFieldCreate(Schema):
    title: str
    field_type: str
    description: Optional[str] = None
    order: Optional[int] = None

class CustomFieldUpdate(Schema):
    title: Optional[str] = None
    description: Optional[str] = None
    order: Optional[int] = None

class CustomFieldOptionCreate(Schema):
    label: str
    color: str = "#000000"
    order: Optional[int] = None

class CustomFieldOptionUpdate(Schema):
    label: Optional[str] = None
    color: Optional[str] = None
    order: Optional[int] = None

class CustomFieldOptionAIActionCreate(Schema):
    action: str
    configuration: Dict = {}

class CustomFieldOptionAIActionUpdate(Schema):
    is_enabled: Optional[bool] = None
    configuration: Optional[Dict] = None

class CustomFieldValueCreate(Schema):
    content_type: str
    object_id: UUID
    text_value: Optional[str] = None
    date_value: Optional[datetime] = None
    option_value_id: Optional[int] = None
    multi_option_ids: List[int] = []

# Field Configuration Schemas
class FieldOptionAIAction(Schema):
    """
    Configuration for an AI action attached to a field option.
    
    Example:
        {
            "action": "spelling_grammar",
            "is_enabled": true,
            "configuration": {
                "language": "en",
                "check_spelling": true,
                "check_grammar": true
            }
        }
    """
    action: str = Field(
        ...,
        description="The type of AI action. Available actions: spelling_grammar, color_contrast, image_quality, image_artifacts"
    )
    is_enabled: bool = Field(
        default=True,
        description="Whether this AI action is currently enabled"
    )
    configuration: Dict = Field(
        default={},
        description="Configuration settings specific to the AI action type. See action definitions for available settings."
    )

class FieldOption(Schema):
    """
    Configuration for a field option, including its AI actions.
    
    Example:
        {
            "id": 1,  # Include for existing options
            "label": "In Progress",
            "color": "#FFD700",
            "order": 1,
            "ai_actions": [
                {
                    "action": "spelling_grammar",
                    "is_enabled": true,
                    "configuration": {
                        "language": "en",
                        "check_spelling": true
                    }
                }
            ],
            "should_delete": false
        }
    """
    id: Optional[int] = Field(
        default=None,
        description="ID of an existing option. Omit when creating new options."
    )
    label: str = Field(
        ...,
        description="Display text for the option"
    )
    color: str = Field(
        default="#000000",
        description="Color for the option in hex format (e.g. #FF0000)"
    )
    order: Optional[int] = Field(
        default=None,
        description="Display order of the option. Lower numbers appear first."
    )
    ai_actions: List[FieldOptionAIAction] = Field(
        default=[],
        description="List of AI actions to trigger when this option is selected. Only applicable for SINGLE_SELECT fields."
    )
    should_delete: bool = Field(
        default=False,
        description="Set to true to delete an existing option. Only applicable when updating fields."
    )

class FieldConfiguration(Schema):
    """
    Configuration for creating or updating a custom field.
    
    Examples:
        Creating a new field:
        {
            "title": "Status",
            "field_type": "SINGLE_SELECT",
            "description": "Current status of the item",
            "options": [
                {
                    "label": "In Progress",
                    "color": "#FFD700",
                    "order": 1,
                    "ai_actions": [
                        {
                            "action": "spelling_grammar",
                            "is_enabled": true,
                            "configuration": {
                                "language": "en",
                                "check_spelling": true
                            }
                        }
                    ]
                }
            ]
        }
        
        Updating an existing field:
        {
            "title": "Status",
            "field_type": "SINGLE_SELECT",
            "description": "Current status of the item",
            "options": [
                {
                    "id": 1,
                    "label": "In Progress",
                    "color": "#FFD700",
                    "order": 1,
                    "ai_actions": []
                },
                {
                    "id": 2,
                    "should_delete": true
                },
                {
                    "label": "New Option",
                    "color": "#0000FF",
                    "order": 2
                }
            ]
        }
    """
    title: str = Field(
        ...,
        description="The name of the field. Must be unique within the workspace."
    )
    field_type: str = Field(
        ...,
        description="Type of field. One of: SINGLE_SELECT, MULTI_SELECT, TEXT, DATE"
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional description of the field's purpose"
    )
    options: List[FieldOption] = Field(
        default=[],
        description="List of options for SINGLE_SELECT and MULTI_SELECT fields. Ignored for other field types."
    )
