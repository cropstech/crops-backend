from ninja import Router, Schema
from ninja.decorators import decorate_view
from datetime import datetime, timedelta
from uuid import UUID
from typing import Optional, List, Any
from django.shortcuts import get_object_or_404
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from ninja.errors import HttpError
from ninja.responses import Response
from ninja.security import django_auth
from django.conf import settings

from .models import Workspace, WorkspaceInvitation, ShareLink, WorkspaceMember, Asset
from .schemas import (
    WorkspaceInviteSchema, ShareLinkSchema, WorkspaceCreateSchema, 
    WorkspaceDataSchema, WorkspaceUpdateSchema, AssetCreateSchema, 
    WorkspaceInviteIn, WorkspaceInviteOut, InviteAcceptSchema
)
from .utils import send_invitation_email
from .decorators import check_workspace_permission

router = Router(tags=["main"], auth=django_auth)



@router.post("/workspaces/create", response=WorkspaceDataSchema)
def create_workspace(request, data: WorkspaceCreateSchema):
    workspace = Workspace.objects.create(
        name=data.name,
        description=data.description,
        avatar=data.avatar
    )
    
    WorkspaceMember.objects.create(
        workspace=workspace,
        user=request.user,
        role=WorkspaceMember.Role.ADMIN
    )
    
    return workspace

@router.get("/workspaces", response=List[WorkspaceDataSchema])
def list_workspaces(request):
    workspaces = Workspace.objects.filter(
        workspacemember__user=request.user
    )
    return workspaces

@router.get("/workspaces/{workspace_id}", response=WorkspaceDataSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_workspace(request, workspace_id: UUID):
    # raise HttpError(403, "You are not a member of this workspace")
    workspace = get_object_or_404(Workspace.objects.filter(
        workspacemember__user=request.user
    ), id=workspace_id)
    return workspace

@router.put("/workspaces/{workspace_id}", response=WorkspaceDataSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def update_workspace(
    request, 
    workspace_id: UUID, 
    data: WorkspaceUpdateSchema, 
):
    try:
        workspace = get_object_or_404(Workspace, id=workspace_id)
        for field, value in data.dict(exclude_unset=True).items():
            setattr(workspace, field, value)
        workspace.save()
        return workspace
    except HttpError as e:
        raise e
    

@router.delete("/workspaces/{workspace_id}")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def delete_workspace(request, workspace_id: UUID):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    workspace.delete()
    return {"success": True}



@router.post("/workspaces/{workspace_id}/settings")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def update_workspace_settings(
    request, 
    workspace_id: UUID, 
    data: WorkspaceUpdateSchema, 
    workspace: Any, 
    member: Any
):
    # Update workspace settings...
    pass

@router.post("/workspaces/{workspace_id}/assets")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def create_asset(
    request, 
    workspace_id: UUID, 
    data: AssetCreateSchema, 
    workspace: Any, 
    member: Any
):
    asset = Asset.objects.create(
        workspace=workspace,
        created_by=request.user,
        **data.dict()
    )
    return asset

@router.get("/workspaces/{workspace_id}/assets")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def list_assets(
    request, 
    workspace_id: UUID, 
    workspace: Any, 
    member: Any
):
    assets = Asset.objects.filter(workspace=workspace)
    return assets


@router.post("/workspaces/{workspace_id}/share")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def create_share_link(
    request, 
    workspace_id: UUID, 
    data: ShareLinkSchema, 
    workspace: Any, 
    member: Any
):
    content_type = ContentType.objects.get(model=data.content_type.lower())
    
    share_link = ShareLink.objects.create(
        workspace=workspace,
        created_by=request.user,
        content_type=content_type,
        object_id=data.object_id,
        permission=data.permission,
        expires_at=data.expires_at,
        password=data.password,
        max_uses=data.max_uses
    )
    
    return {
        "id": share_link.id,
        "token": share_link.token,
        "url": f"/share/{share_link.token}"
    }

@router.get("/share/{token}")
def access_shared_content(request, token: str):
    share_link = get_object_or_404(ShareLink, token=token)
    
    if not share_link.is_valid:
        raise HttpError(403, "This share link has expired")
    
    share_link.current_uses += 1
    share_link.save()
    
    return {
        "content_type": share_link.content_type.model,
        "content": share_link.content_object
    }

@router.post("/workspaces/{workspace_id}/invites", response=WorkspaceInviteOut)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def create_workspace_invite(request, workspace_id: UUID, data: WorkspaceInviteSchema):
    invitation = WorkspaceInvitation.objects.create(
        workspace=workspace,
        email=data.email,
        role=data.role,
        invited_by=request.user,
        expires_at=data.expires_at or datetime.now() + timedelta(days=7)
    )
    
    send_invitation_email(invitation)
    
    return {
        "id": invitation.id,
        "token": invitation.token
    }

@router.post("/invites/accept")
def accept_workspace_invite(request, data: InviteAcceptSchema):
    invitation = get_object_or_404(WorkspaceInvitation, token=data.token)
    
    if invitation.status != 'PENDING':
        raise HttpError(400, "This invitation has already been used or expired")
    
    if invitation.expires_at < timezone.now():
        invitation.status = 'EXPIRED'
        invitation.save()
        raise HttpError(400, "This invitation has expired")
    
    if WorkspaceMember.objects.filter(workspace=invitation.workspace, user=request.user).exists():
        raise HttpError(400, "You are already a member of this workspace")
    
    WorkspaceMember.objects.create(
        workspace=invitation.workspace,
        user=request.user,
        role=invitation.role,
        invited_by=invitation.invited_by
    )
    
    invitation.status = 'ACCEPTED'
    invitation.save()
    
    return Response({
        "workspace_id": str(invitation.workspace.id),
        "role": invitation.role,
        "message": "Successfully joined workspace"
    }, status=200)

@router.get("/invites/{token}/info")
def get_invite_info(request, token: str):
    invitation = get_object_or_404(WorkspaceInvitation, token=token)
    
    if invitation.status != 'PENDING':
        raise HttpError(400, "This invitation has already been used or expired")
    
    if invitation.expires_at < timezone.now():
        invitation.status = 'EXPIRED'
        invitation.save()
        raise HttpError(400, "This invitation has expired")
    
    return {
        "workspace": {
            "id": str(invitation.workspace.id),
            "name": invitation.workspace.name,
            "description": invitation.workspace.description,
            "avatar": invitation.workspace.avatar.url if invitation.workspace.avatar else None,
        },
        "invited_by": {
            "name": invitation.invited_by.get_full_name() or invitation.invited_by.email,
            "email": invitation.invited_by.email
        },
        "role": invitation.role,
        "expires_at": invitation.expires_at
    }

