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
    default_view: Optional[str] = 'GALLERY'
    kanban_group_by_field_id: Optional[int] = None
    default_sort: Optional[str] = '-date_uploaded'

class BoardUpdateSchema(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[Union[UUID, str]] = None
    default_view: Optional[str] = None
    kanban_group_by_field_id: Optional[int] = None
    default_sort: Optional[str] = None

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
    default_view: str
    kanban_group_by_field_id: Optional[int] = None
    kanban_group_by_field: Optional['CustomFieldSchema'] = None
    default_sort: str
    
    model_config = ConfigDict(
        from_attributes=True
    )

    @staticmethod
    def resolve_child_count(obj):
        return obj.children.count()
    
    @staticmethod
    def resolve_kanban_group_by_field_id(obj):
        effective_field = obj.get_effective_kanban_group_by_field()
        return effective_field.id if effective_field else None
    
    @staticmethod
    def resolve_kanban_group_by_field(obj):
        return obj.get_effective_kanban_group_by_field()

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

class PaginationSchema(Schema):
    """Pagination metadata for paginated responses"""
    page: int
    page_size: int
    total_count: int
    total_pages: int
    has_more: bool

class PaginatedAssetResponse(Schema):
    """Paginated response for asset listing"""
    data: List[AssetSchema]
    pagination: PaginationSchema
    
class BoardReorderSchema(Schema):
    board_id: UUID
    new_order: int

class BoardReorderRequestSchema(Schema):
    items: List[BoardReorderSchema]

class AssetReorderSchema(Schema):
    asset_ids: List[UUID]

class AssetReorderRequestSchema(Schema):
    asset_ids: List[UUID] = Field(..., description="List of asset UUIDs in the desired order")

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


# Notification System Schemas

class BoardFollowerSchema(Schema):
    id: int
    board_id: UUID
    board_name: str
    include_sub_boards: bool
    auto_followed: bool
    created_at: datetime
    
    @staticmethod
    def from_orm(obj):
        return {
            'id': obj.id,
            'board_id': obj.board.id,
            'board_name': obj.board.name,
            'include_sub_boards': obj.include_sub_boards,
            'auto_followed': obj.auto_followed,
            'created_at': obj.created_at
        }


class BoardFollowerCreate(Schema):
    board_id: UUID
    include_sub_boards: bool = True


class CommentAuthorSchema(Schema):
    id: int
    email: str
    first_name: str
    last_name: str


class CommentSchema(Schema):
    id: int
    author: CommentAuthorSchema
    text: str
    created_at: datetime
    updated_at: datetime
    parent_id: Optional[int] = None
    is_reply: bool
    has_replies: bool
    reply_count: int
    mentioned_users: List[str] = []  # List of mentioned user emails
    annotation_type: str = 'NONE'  # 'NONE', 'POINT', or 'AREA'
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    
    @staticmethod
    def from_orm(obj):
        return {
            'id': obj.id,
            'author': {
                'id': obj.author.id,
                'email': obj.author.email,
                'first_name': obj.author.first_name,
                'last_name': obj.author.last_name
            },
            'text': obj.text,
            'created_at': obj.created_at,
            'updated_at': obj.updated_at,
            'parent_id': obj.parent.id if obj.parent else None,
            'is_reply': obj.is_reply,
            'has_replies': obj.replies.exists() if hasattr(obj, 'replies') else False,
            'reply_count': obj.replies.count() if hasattr(obj, 'replies') else 0,
            'mentioned_users': [user.email for user in obj.mentioned_users.all()],
            'annotation_type': obj.annotation_type,
            'x': obj.x,
            'y': obj.y,
            'width': obj.width,
            'height': obj.height
        }


class CommentCreate(Schema):
    text: str
    content_type: str  # 'asset' or 'board'
    object_id: UUID
    parent_id: Optional[int] = None
    annotation_type: str = 'NONE'  # 'NONE', 'POINT', or 'AREA'
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None


class CommentUpdate(Schema):
    text: str


class EventPreferenceSchema(Schema):
    """Schema for individual event type preferences"""
    event_type: str
    display_name: str
    in_app_enabled: bool
    email_enabled: bool


class UserNotificationPreferenceSchema(Schema):
    """Schema for user's complete notification preferences"""
    user_id: int
    email_frequency: int
    preferences: List[EventPreferenceSchema]
    created_at: datetime
    updated_at: datetime
    
    @staticmethod
    def from_orm(obj):
        return {
            'user_id': obj.user.id,
            'email_frequency': obj.email_frequency,
            'preferences': obj.get_all_preferences_display(),
            'created_at': obj.created_at,
            'updated_at': obj.updated_at
        }


class EventPreferenceUpdate(Schema):
    """Schema for updating a single event type preference"""
    in_app_enabled: bool
    email_enabled: bool


class UserNotificationPreferenceUpdate(Schema):
    """Schema for updating user notification preferences"""
    email_frequency: Optional[int] = None
    event_preferences: Dict[str, EventPreferenceUpdate] = {}  # event_type -> preference


# Legacy schemas for backward compatibility
class NotificationPreferenceSchema(Schema):
    """DEPRECATED: Use UserNotificationPreferenceSchema instead"""
    id: int
    event_type: str
    event_type_display: str
    in_app_enabled: bool
    email_enabled: bool
    email_frequency: int
    
    @staticmethod
    def from_orm(obj):
        return {
            'id': obj.id,
            'event_type': obj.event_type,
            'event_type_display': obj.get_event_type_display(),
            'in_app_enabled': obj.in_app_enabled,
            'email_enabled': obj.email_enabled,
            'email_frequency': obj.email_frequency
        }


class NotificationPreferenceUpdate(Schema):
    """DEPRECATED: Use UserNotificationPreferenceUpdate instead"""
    in_app_enabled: bool
    email_enabled: bool
    email_frequency: int = 5


class NotificationPreferencesBulkUpdate(Schema):
    """DEPRECATED: Use UserNotificationPreferenceUpdate instead"""
    preferences: Dict[str, NotificationPreferenceUpdate]  # event_type -> preference


class NotificationSchema(Schema):
    id: int
    actor_id: Optional[int] = None
    actor_email: Optional[str] = None
    actor_first_name: Optional[str] = None
    actor_last_name: Optional[str] = None
    verb: str
    description: str
    action_object_type: Optional[str] = None
    action_object_id: Optional[str] = None
    target_name: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    workspace_id: Optional[str] = None
    workspace_name: Optional[str] = None
    unread: bool
    timestamp: datetime
    data: Dict = {}
    
    @staticmethod
    def from_orm(obj):
        # Extract actor information
        actor_id = None
        actor_email = None
        actor_first_name = None
        actor_last_name = None
        
        if obj.actor:
            actor_id = obj.actor.id
            actor_email = obj.actor.email
            actor_first_name = obj.actor.first_name
            actor_last_name = obj.actor.last_name
        
        # Extract target information
        target_type = None
        target_id = None
        workspace_id = None
        workspace_name = None
        
        if obj.target:
            # Get the model name from the target object
            target_type = obj.target.__class__.__name__.lower()
            target_id = str(obj.target.id)
            
            # Extract workspace information from the target
            workspace = None
            if hasattr(obj.target, 'workspace'):
                # Direct workspace relationship (Asset, Board, etc.)
                workspace = obj.target.workspace
            elif hasattr(obj.target, 'content_object') and hasattr(obj.target.content_object, 'workspace'):
                # For objects like Comment that have a content_object (Asset/Board)
                workspace = obj.target.content_object.workspace
            elif target_type == 'comment' and hasattr(obj.target, 'content_object'):
                # Special handling for comments - get workspace from the commented object
                content_obj = obj.target.content_object
                if hasattr(content_obj, 'workspace'):
                    workspace = content_obj.workspace
                elif hasattr(content_obj, 'boards') and content_obj.boards.exists():
                    # For assets, get workspace from first board
                    workspace = content_obj.boards.first().workspace
            
            if workspace:
                workspace_id = str(workspace.id)
                workspace_name = workspace.name
        
        # Extract action object information
        action_object_type = None
        action_object_id = None
        
        if obj.action_object:
            action_object_type = obj.action_object.__class__.__name__.lower()
            action_object_id = str(obj.action_object.id)
        
        return {
            'id': obj.id,
            'actor_id': actor_id,
            'actor_email': actor_email,
            'actor_first_name': actor_first_name,
            'actor_last_name': actor_last_name,
            'verb': obj.verb,
            'description': obj.description,
            'action_object_type': action_object_type,
            'action_object_id': action_object_id,
            'target_name': str(obj.target) if obj.target else None,
            'target_type': target_type,
            'target_id': target_id,
            'workspace_id': workspace_id,
            'workspace_name': workspace_name,
            'unread': obj.unread,
            'timestamp': obj.timestamp,
            'data': obj.data or {}
        }

# Filter Schemas for Asset Listing

class CustomFieldFilterValue(Schema):
    """Filter for a specific custom field value"""
    is_: Optional[int] = Field(None, alias="is", description="Filter by specific option ID (for single/multi-select fields)")
    not_set: Optional[bool] = Field(None, alias="notSet", description="Filter for fields that have no value set")
    contains: Optional[str] = Field(None, description="Text contains filter (for text fields)")
    date_from: Optional[datetime] = Field(None, alias="dateFrom", description="Date range start (for date fields)")
    date_to: Optional[datetime] = Field(None, alias="dateTo", description="Date range end (for date fields)")

class CustomFieldFilter(Schema):
    """Filter configuration for a custom field"""
    id: int = Field(..., description="Custom field ID")
    filter: CustomFieldFilterValue = Field(..., description="Filter criteria for this field")

class TagFilter(Schema):
    """Filter for tags (for future implementation)"""
    includes: Optional[List[str]] = Field(None, description="Assets must include all of these tags")
    excludes: Optional[List[str]] = Field(None, description="Assets must not include any of these tags")

class AssetListFilters(Schema):
    """Complete filter configuration for asset listing"""
    # Pagination and sorting
    page: int = Field(1, description="Page number (1-based)")
    page_size: int = Field(10, description="Number of items per page")
    order_by: str = Field("-date_uploaded", description="Sort field (prefix with - for descending)")
    search: Optional[str] = Field(None, description="Search term for file names")
    board_id: Optional[UUID] = Field(None, alias="boardId", description="Filter by specific board")
    
    # Filter options
    custom_fields: Optional[List[CustomFieldFilter]] = Field(None, alias="customFields", description="Custom field filters")
    tags: Optional[TagFilter] = Field(None, description="Tag filters (future implementation)")
    file_type: Optional[List[str]] = Field(None, alias="fileType", description="Filter by file types (IMAGE, VIDEO, etc.)")
    favorite: Optional[bool] = Field(None, description="Filter by favorite status")
    date_uploaded_from: Optional[datetime] = Field(None, alias="dateUploadedFrom", description="Uploaded after this date")
    date_uploaded_to: Optional[datetime] = Field(None, alias="dateUploadedTo", description="Uploaded before this date")


