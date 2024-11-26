from ninja import Schema
from typing import List, Optional
from datetime import datetime
from uuid import UUID
from pydantic import ConfigDict

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

    @staticmethod
    def resolve_id(obj):
        return str(obj.id)
    
class WorkspaceUpdateSchema(Schema):
    name: Optional[str] = None
    avatar: Optional[str] = None
    description: Optional[str] = None

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
    
class AssetCreateSchema(Schema):
    name: str
    description: Optional[str] = None
    file: str


class WorkspaceInviteIn(Schema):
    email: str
    role: str
    expires_at: Optional[datetime] = None

class WorkspaceInviteOut(Schema):
    id: UUID
    token: UUID
    model_config = ConfigDict(arbitrary_types_allowed=True)

class InviteAcceptSchema(Schema):
    token: str