from ninja import Router, Schema
from ninja.security import HttpBearer
from datetime import datetime, timedelta
from django.shortcuts import get_object_or_404
from django.contrib.contenttypes.models import ContentType
from ninja import Router
from ninja_crud import views, viewsets
from photomink.main.schemas import WorkspaceInviteSchema, ShareLinkSchema, WorkspaceCreateSchema, WorkspaceDataSchema, WorkspaceUpdateSchema, AssetCreateSchema
from photomink.main.models import Workspace, WorkspaceInvitation, ShareLink, WorkspaceMember
from typing import List
from ninja.responses import Response
from photomink.main.utils import send_invitation_email
from django.utils import timezone
from ninja.errors import HttpError

router = Router(tags=["main"])


class WorkspaceViewSet(viewsets.APIViewSet):
    api = router
    model = Workspace
    list_workspaces = views.ListView(response_body=List[WorkspaceDataSchema])
    # create_workspace = views.CreateView(request_body=WorkspaceCreateSchema, response_body=WorkspaceDataSchema)
    get_workspace = views.ReadView(response_body=WorkspaceDataSchema)
    update_workspace = views.UpdateView(request_body=WorkspaceCreateSchema, response_body=WorkspaceDataSchema)
    delete_workspace = views.DeleteView()


@router.post("/workspaces/{workspace_id}/invites")
def create_workspace_invite(request, workspace_id: str, data: WorkspaceInviteSchema):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Get the workspace member object for the current user
    workspace_member = get_object_or_404(
        WorkspaceMember, 
        workspace=workspace, 
        user=request.user
    )
    
    # Check if user has permission to invite
    if not workspace_member.can_manage_workspace():
        return Response({"error": "Permission denied"}, status=403)
    
    # Create invitation
    invitation = WorkspaceInvitation.objects.create(
        workspace=workspace,
        email=data.email,
        role=data.role,
        invited_by=request.user,
        expires_at=data.expires_at or datetime.now() + timedelta(days=7)
    )
    
    # Send invitation email
    send_invitation_email(invitation)
    
    return Response({
        "id": str(invitation.id),
        "token": str(invitation.token)
    }, status=201)
 
@router.post("/workspaces/{workspace_id}/share")
def create_share_link(request, workspace_id: str, data: ShareLinkSchema):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Check if user has permission to share
    if not request.user.has_perm('create_share_links', workspace):
        return {"error": "Permission denied"}, 403
    
    # Get content type
    content_type = ContentType.objects.get(model=data.content_type.lower())
    
    # Create share link
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
    
    # Check if share link is valid
    if not share_link.is_valid:
        return {"error": "This share link has expired"}, 403
    
    # Increment usage counter
    share_link.current_uses += 1
    share_link.save()
    
    # Return shared content (implement based on content type)
    return {
        "content_type": share_link.content_type.model,
        "content": share_link.content_object
    } 

@router.post("/workspaces/create", response=WorkspaceDataSchema)
def create_workspace(request, data: WorkspaceCreateSchema):
    workspace = Workspace.objects.create(
        name=data.name,
        description=data.description,
        avatar=data.avatar
    )
    
    # Make creator an admin
    WorkspaceMember.objects.create(
        workspace=workspace,
        user=request.user,
        role=WorkspaceMember.Role.ADMIN
    )
    
    return workspace

@router.post("/workspaces/{workspace_id}/settings")
def update_workspace_settings(request, workspace_id: str, data: WorkspaceUpdateSchema):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    member = get_object_or_404(WorkspaceMember, workspace=workspace, user=request.user)
    
    if not member.can_manage_workspace():
        return Response({"error": "Only administrators can edit workspace settings"}, status=403)
    
    # Update workspace settings...

@router.post("/workspaces/{workspace_id}/assets")
def create_asset(request, workspace_id: str, data: AssetCreateSchema):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    member = get_object_or_404(WorkspaceMember, workspace=workspace, user=request.user)
    
    if not member.can_manage_content():
        return Response({"error": "You don't have permission to create assets"}, status=403)
    
    # Create asset...

class InviteAcceptSchema(Schema):
    token: str

@router.post("/invites/accept")
def accept_workspace_invite(request, data: InviteAcceptSchema):
    # Get invitation by token
    invitation = get_object_or_404(WorkspaceInvitation, token=data.token)
    
    # Check if invitation is still valid
    if invitation.status != 'PENDING':
        raise HttpError(400, "This invitation has already been used or expired")
    
    if invitation.expires_at < timezone.now():
        invitation.status = 'EXPIRED'
        invitation.save()
        raise HttpError(400, "This invitation has expired")
        
    # Check if user is already a member
    if WorkspaceMember.objects.filter(
        workspace=invitation.workspace,
        user=request.user
    ).exists():
        raise HttpError(400, "You are already a member of this workspace")
    
    # Create workspace member
    WorkspaceMember.objects.create(
        workspace=invitation.workspace,
        user=request.user,
        role=invitation.role,
        invited_by=invitation.invited_by
    )
    
    # Update invitation status
    invitation.status = 'ACCEPTED'
    invitation.save()
    
    return Response({
        "workspace_id": str(invitation.workspace.id),
        "role": invitation.role,
        "message": "Successfully joined workspace"
    }, status=200)

@router.get("/invites/{token}/info")
def get_invite_info(request, token: str):
    """Get information about an invitation without accepting it"""
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