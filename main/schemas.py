from ninja import Schema, ModelSchema
from typing import List, Optional
from datetime import datetime
from uuid import UUID
from pydantic import ConfigDict, BaseModel, Field
from django_paddle_billing.models import Product, Subscription

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
    size: int
    status: str
    date_created: Optional[datetime]
    date_modified: datetime
    date_uploaded: datetime
    name: Optional[str] = None
    file_type: Optional[str] = None
    mime_type: Optional[str] = None
    metadata: Optional[dict] = None

    model_config = ConfigDict(
        from_attributes=True
    )

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
