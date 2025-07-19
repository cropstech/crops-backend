from ninja import Router, Schema, File, Form, UploadedFile
from ninja.decorators import decorate_view
from datetime import datetime, timedelta
from uuid import UUID
from typing import Optional, List, Any, Dict
from django.shortcuts import get_object_or_404
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from ninja.errors import HttpError
from ninja.responses import Response
from ninja.security import django_auth
from django.conf import settings
from ninja.files import UploadedFile
from django.db import transaction
from django.core.files.storage import default_storage, storages
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from concurrent.futures import ThreadPoolExecutor
import logging
import boto3
from botocore.exceptions import ClientError
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from apiclient import HeaderAuthentication
from .models import (
    AIActionChoices,
    AIActionDefinition,
    AIActionResult,
    Asset,
    Board,
    BoardAsset,
    BoardFollower,
    Comment,
    CustomField,
    CustomFieldOption,
    CustomFieldOptionAIAction,
    CustomFieldValue,
    UserNotificationPreference,
    ShareLink,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMember
)
from .schemas import (
    WorkspaceInviteSchema, ShareLinkSchema, WorkspaceCreateSchema, 
    WorkspaceDataSchema, WorkspaceUpdateSchema, 
    WorkspaceInviteIn, WorkspaceInviteOut, InviteAcceptSchema,
    AssetSchema, WorkspaceUpdateForm, WorkspaceMemberUpdateSchema,
    WorkspaceMemberSchema,
    ProductSubscriptionSchema,
    PlanOut,
    TransactionSchema,
    BoardCreateSchema,
    BoardUpdateSchema,
    BoardOutSchema,
    DownloadInitiateSchema,
    DownloadResponseSchema,
    AssetBulkTagsSchema,
    AssetBulkFavoriteSchema,
    AssetBulkBoardSchema,
    AssetBulkMoveSchema,
    AssetBulkDeleteSchema,
    AssetBulkDownloadSchema,
    BulkDownloadResponseSchema,
    BoardReorderSchema,
    AssetReorderRequestSchema,
    UploadCompleteSchema,
    UploadResponseSchema,
    CustomFieldSchema,
    CustomFieldCreate,
    CustomFieldUpdate,
    CustomFieldOptionSchema,
    CustomFieldOptionCreate,
    CustomFieldOptionUpdate,
    CustomFieldValueSchema,
    CustomFieldValueCreate,
    AIActionResultSchema,
    CustomFieldOptionAIActionSchema,
    CustomFieldOptionAIActionCreate,
    CustomFieldOptionAIActionUpdate,
    FieldConfiguration,
    FieldOption,
    BoardFollowerSchema,
    BoardFollowerCreate,
    CommentSchema,
    CommentCreate,
    CommentUpdate,
    UserNotificationPreferenceSchema,
    UserNotificationPreferenceUpdate,
    NotificationSchema,
    AssetListFilters,
    PaginatedAssetResponse
)
from .utils import (
    send_invitation_email, process_file_metadata, process_file_metadata_background, 
    executor, accept_invitation, quick_file_metadata, generate_workspace_avatar
)
from .decorators import check_workspace_permission
from django_paddle_billing.models import Product, Subscription, Price, paddle_client
from paddle_billing_client.models.subscription import SubscriptionRequest
from .download import DownloadManager
import os
import zipfile
import tempfile
from .upload import UploadManager
from django.db import models

router = Router(tags=["main"], auth=django_auth)

logger = logging.getLogger(__name__)



@router.post("/workspaces/create", response=WorkspaceDataSchema)
def create_workspace(request, data: WorkspaceCreateSchema):
    # Generate avatar if none provided
    if not data.avatar:
        avatar_file = generate_workspace_avatar()
        workspace = Workspace.objects.create(
            name=data.name,
            description=data.description,
            avatar=avatar_file
        )
    else:
        workspace = Workspace.objects.create(
            name=data.name,
            description=data.description,
            avatar=data.avatar
        )
    
    with transaction.atomic():
        # Create default board FIRST (before workspace member)
        default_board = Board.objects.create(
            workspace=workspace,
            name="General",
            description="Default board for general content",
            created_by=request.user
        )
        
        # Create workspace member (this will trigger auto-follow signal for the board we just created)
        WorkspaceMember.objects.create(
            workspace=workspace,
            user=request.user,
            role=WorkspaceMember.Role.ADMIN
        )
        
        # Create default status field
        status_field = CustomField.objects.create(
            workspace=workspace,
            title="Status",
            field_type="SINGLE_SELECT",
            description="Use status tracking to maintain perfect team alignment throughout your workflow."
        )
        
        # Create status options with their AI actions
        status_options = [
            # {
            #     "label": "In Progress",
            #     "color": "#7B1FA2",
            #     "order": 1,
            #     "ai_actions": []
            # },
            {
                "label": "AI Check",
                "color": "#E64A19",
                "order": 1,
                "ai_actions": [
                    {
                        "action": "grammar",
                        "is_enabled": True,
                        "configuration": {
                            "language": "en-US"
                        }
                    },
                    {
                        "action": "color_contrast",
                        "is_enabled": True,
                        "configuration": {}
                    },
                    {
                        "action": "image_quality",
                        "is_enabled": True,
                        "configuration": {}
                    },
                    {
                        "action": "text_overflow",
                        "is_enabled": True,
                        "configuration": {}
                    }
                ]
            },
            {
                "label": "Ready for Review",
                "color": "#00796B",
                "order": 2,
                "ai_actions": []
            },
            {
                "label": "Done",
                "color": "#00a300",
                "order": 4,
                "ai_actions": []
            }
        ]
        
        for option_data in status_options:
            option = CustomFieldOption.objects.create(
                field=status_field,
                label=option_data["label"],
                color=option_data["color"],
                order=option_data["order"]
            )
            
            # Create AI actions for the option
            for action_data in option_data["ai_actions"]:
                CustomFieldOptionAIAction.objects.create(
                    option=option,
                    action=action_data["action"],
                    is_enabled=action_data["is_enabled"],
                    configuration=action_data["configuration"]
                )
    
    return workspace

@router.get("/workspaces", response=List[WorkspaceDataSchema])
def list_workspaces(request):
    workspaces = Workspace.objects.filter(
        workspacemember__user=request.user
    )
    return workspaces

@router.get("/workspaces/{uuid:workspace_id}", response=WorkspaceDataSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_workspace(request, workspace_id: UUID):
    # raise HttpError(403, "You are not a member of this workspace")
    workspace = get_object_or_404(Workspace.objects.filter(
        workspacemember__user=request.user
    ), id=workspace_id)
    member = WorkspaceMember.objects.get(workspace=workspace, user=request.user)
    workspace.user_role = member.role
    return workspace


@router.post("/workspaces/{uuid:workspace_id}/update", response=WorkspaceDataSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def update_workspace(
    request, 
    workspace_id: UUID,
    file: Optional[UploadedFile] = File(None),  # Required file upload
    name: Optional[str] = Form(None),  # Optional name update
    description: Optional[str] = Form(None)  # Optional description update
):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Handle file upload
    if file:
        # Delete old avatar if it exists
        if workspace.avatar:
            workspace.avatar.delete(save=False)
        
        # Save new avatar to storage
        staticfiles_storage = storages["staticfiles"]
        file_path = staticfiles_storage.save(
            f'avatars/{file.name}', 
            file
        )
        
        # Update workspace with new avatar path
        workspace.avatar = file_path
    
    # Update name and description if provided
    if name is not None:
        workspace.name = name
    if description is not None:
        workspace.description = description
    
    workspace.save()
    
    return workspace

@router.delete("/workspaces/{uuid:workspace_id}")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def delete_workspace(request, workspace_id: UUID):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    workspace.delete()
    return {"success": True}


# Get workspace members
@router.get("/workspaces/{uuid:workspace_id}/members", response=List[WorkspaceMemberSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_workspace_members(request, workspace_id: UUID):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    members = workspace.workspacemember_set.select_related('user', 'workspace').all()
    print(members)
    return list(members)

# Update workspace member role
@router.put("/workspaces/{uuid:workspace_id}/members/{member_id}", response=WorkspaceMemberSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def update_workspace_member_role(request, workspace_id: UUID, member_id: int, data: WorkspaceMemberUpdateSchema):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    member = get_object_or_404(WorkspaceMember, id=member_id)
    
    # Check if this is the last admin
    if member.role == WorkspaceMember.Role.ADMIN and data.role != WorkspaceMember.Role.ADMIN:
        admin_count = WorkspaceMember.objects.filter(
            workspace=workspace,
            role=WorkspaceMember.Role.ADMIN
        ).count()
        
        if admin_count <= 1:
            raise HttpError(400, "Cannot change role of the only admin")
    
    member.role = data.role
    member.save()
    return member

# Delete workspace member
@router.delete("/workspaces/{uuid:workspace_id}/members/{member_id}")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def delete_workspace_member(request, workspace_id: UUID, member_id: int):
    member = get_object_or_404(WorkspaceMember, id=member_id)
    
    # Check if this is the last admin
    if member.role == WorkspaceMember.Role.ADMIN:
        admin_count = WorkspaceMember.objects.filter(
            workspace=member.workspace,
            role=WorkspaceMember.Role.ADMIN
        ).count()
        
        if admin_count <= 1:
            raise HttpError(400, "Cannot remove the only admin from the workspace")
    
    member.delete()
    return {"success": True}

@router.get("/workspaces/{uuid:workspace_id}/subscription")
def get_subscription(request, workspace_id: UUID):
    logger.info(f"Getting subscription for workspace {workspace_id}")
    workspace = get_object_or_404(Workspace, id=workspace_id)
    workspace_subscription = workspace.subscription
    logger.info(f"Subscription: {workspace_subscription}")

    if not workspace_subscription:
        return {
            "status": "no_subscription",
            "plan": "free"
        }
    
    return {
        "status": workspace_subscription.status,
        "plan": workspace_subscription.products.first().name,
        "next_bill_date": workspace_subscription.data.get('next_billed_at')
    }

@router.post("/workspaces/{uuid:workspace_id}/share")
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

@router.post("/workspaces/{uuid:workspace_id}/invites", response=WorkspaceInviteOut)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def create_workspace_invite(request, workspace_id: UUID, data: WorkspaceInviteSchema):
    workspace = get_object_or_404(Workspace, id=workspace_id)

    invitation = WorkspaceInvitation.objects.create(
        workspace=workspace,
        email=data.email,
        role=data.role,
        invited_by=request.user,
        expires_at=data.expires_at or timezone.now() + timedelta(days=7)
    )
    
    send_invitation_email(invitation)
    
    return invitation

@router.get("/workspaces/{uuid:workspace_id}/invites", response=List[WorkspaceInviteOut])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_workspace_invites(request, workspace_id: UUID):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    invites = WorkspaceInvitation.objects.filter(
        workspace=workspace,
        status='PENDING'
    ).order_by('-created_at')
    
    # Convert each invite to a WorkspaceInviteOut instance
    return invites

@router.delete("/workspaces/{uuid:workspace_id}/invites/{invite_id}")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def cancel_workspace_invite(request, workspace_id: UUID, invite_id: int):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    invitation = get_object_or_404(
        WorkspaceInvitation,
        id=invite_id,
        workspace=workspace,
        status='PENDING'
    )
    
    invitation.status = 'CANCELLED'
    invitation.save()
    
    return {"success": True}

@router.post("/invites/accept")
def accept_workspace_invite(request, data: InviteAcceptSchema):
    invitation = accept_invitation(data.token, request.user)
    
    return Response({
        "workspace_id": str(invitation.workspace.id),
        "role": invitation.role,
        "message": "Successfully joined workspace"
    }, status=200)

@router.get("/invites/{token}/info", auth=None)
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
        "email": invitation.email,
        "expires_at": invitation.expires_at
    }


@router.post("/workspaces/{uuid:workspace_id}/assets/upload", response=UploadResponseSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def upload_file(
    request, 
    workspace_id: UUID,
    file: UploadedFile = File(...),
    board_id: Optional[UUID] = Form(None),
):
    """
    Create an asset and initiate file upload using UploadManager for better performance and reliability.
    Returns presigned URL information for client-side upload.
    """
    logger.info(f"Creating asset for workspace {workspace_id} with board {board_id}")
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Get quick metadata first
    file_metadata = quick_file_metadata(file)
    
    # Check if Transfer Acceleration is enabled
    if not UploadManager.check_transfer_acceleration():
        logger.warning("Transfer Acceleration is not enabled for the bucket. Uploads may be slower.")
    
    try:
        # Create asset with initial metadata first (with temporary file path)
        with transaction.atomic():
            asset = Asset.objects.create(
                workspace=workspace,
                created_by=request.user,
                file="temp",  # Temporary value, will be updated below
                status=Asset.Status.PROCESSING,
                size=file.size,
                file_type=file_metadata.file_type,
                mime_type=file_metadata.mime_type,
                file_extension=file_metadata.file_extension,
                width=file_metadata.dimensions[0] if file_metadata.dimensions else None,
                height=file_metadata.dimensions[1] if file_metadata.dimensions else None,
                name=file_metadata.name
            )
            
            # Generate the correct S3 key using workspace_asset_path
            from .models import workspace_asset_path
            s3_key = workspace_asset_path(asset, file.name)
            
            # Update the asset with the correct file path
            asset.file = s3_key
            asset.save()
            
            # Initiate upload with UploadManager using the correct key
            upload_info = UploadManager.initiate_upload(
                filename=file.name,
                content_type=file_metadata.mime_type,
                size=file.size,
                use_multipart=file.size > UploadManager.DEFAULT_PART_SIZE,
                s3_key=s3_key  # Pass the correct S3 key
            )
            
            # If board_id is provided, create the board-asset relationship
            if board_id:
                board = get_object_or_404(Board, workspace=workspace, id=board_id)
                BoardAsset.objects.create(
                    board=board,
                    asset=asset,
                    added_by=request.user
                )
                
                # Smart Auto-Follow: Follow board when user uploads to it
                from main.services.notifications import NotificationService
                if not NotificationService.is_following_board(request.user, board):
                    NotificationService.follow_board(
                        user=request.user,
                        board=board,
                        include_sub_boards=False  # Conservative default
                    )
                    logger.info(f"Auto-followed board '{board.name}' for user {request.user.email} after uploading asset")
        
        # Add asset_id to the upload info response
        upload_info['asset_id'] = asset.id
        
        logger.debug(f"Asset created: {asset.id} with file: {file.name}")
        logger.debug(f"S3 key: {s3_key}")
        logger.debug(f"Initial metadata extracted: {file_metadata.file_type}, size: {file_metadata.size}")
        
        return upload_info
        
    except Exception as e:
        logger.error(f"Error creating asset: {str(e)}")
        raise HttpError(500, "Failed to create asset")


@router.post("/workspaces/{uuid:workspace_id}/assets/upload/complete")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def complete_upload(
    request,
    workspace_id: UUID,
    data: UploadCompleteSchema,
):
    """
    Complete a multipart upload for an existing asset.
    This is used when upload_file initiated a multipart upload.
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    try:
        # Complete multipart upload if needed
        if data.parts:
            logger.info(f"Completing multipart upload for key: {data.key} with {len(data.parts)} parts")
            UploadManager.complete_multipart_upload(
                upload_id=data.upload_id,
                key=data.key,
                parts=data.parts
            )
            logger.info(f"Multipart upload completed successfully for key: {data.key}")
        
        # The asset should already exist, so just return success
        # The Lambda function will handle updating the asset status
        return {"success": True, "message": "Upload completed successfully"}
        
    except Exception as e:
        logger.error(f"Error completing upload: {str(e)}")
        raise HttpError(500, "Failed to complete upload")

@router.post("/workspaces/{uuid:workspace_id}/upload-folder", response=List[BoardOutSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def upload_folder(
    request,
    workspace_id: UUID,
    files: List[UploadedFile] = File(...),
    parent_board_id: Optional[UUID] = Form(None),
):
    """
    Upload a folder structure, creating boards for each folder and uploading files to their respective boards.
    Since Django strips folder paths from uploaded files, the frontend should send file paths as form data.
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Get parent board if specified
    parent_board = None
    if parent_board_id:
        parent_board = get_object_or_404(
            Board.objects.filter(workspace_id=workspace_id),
            id=parent_board_id
        )
    
    # Track created boards by path
    boards_by_path = {}
    created_boards = []
    
    # Extract file paths from form data
    file_paths = []
    for key, value in request.POST.items():
        if key.startswith('file_paths[') and key.endswith(']'):
            index = int(key[11:-1])  # Extract index from file_paths[0], file_paths[1], etc.
            # Ensure we have enough slots in the list
            while len(file_paths) <= index:
                file_paths.append(None)
            file_paths[index] = value
    
    logger.info(f"Received {len(files)} files with paths: {file_paths}")
    
    with transaction.atomic():
        # Process each uploaded file with its corresponding path
        for i, file in enumerate(files):
            # Get the relative path from form data, fallback to filename
            relative_path = file_paths[i] if i < len(file_paths) and file_paths[i] else file.name
            
            logger.info(f"Processing file {i}: {relative_path}")
            
            # Parse the folder structure from the relative path
            path_parts = relative_path.split('/')
            filename = path_parts[-1]  # The actual filename
            folder_parts = path_parts[:-1]  # All folder parts except the filename
            
            logger.info(f"File: {filename}, folders: {folder_parts}")
            
            # Create boards for each folder in the path
            current_path = ""
            current_parent = parent_board
            
            for folder_name in folder_parts:
                if not folder_name:  # Skip empty parts
                    continue
                    
                current_path = f"{current_path}/{folder_name}" if current_path else folder_name
                
                # Create board if it doesn't exist
                if current_path not in boards_by_path:
                    logger.info(f"Creating board: {folder_name} at path: {current_path}")
                    board = Board.objects.create(
                        workspace=workspace,
                        name=folder_name,
                        parent=current_parent,
                        created_by=request.user
                    )
                    boards_by_path[current_path] = board
                    created_boards.append(board)
                    
                    # Smart Auto-Follow: Follow board when user creates it during folder upload
                    from main.services.notifications import NotificationService
                    if not NotificationService.is_following_board(request.user, board):
                        NotificationService.follow_board(
                            user=request.user,
                            board=board,
                            include_sub_boards=False,  # Conservative default for folder-created boards
                            auto_followed=True  # Mark as auto-followed
                        )
                        logger.info(f"Auto-followed board '{board.name}' for user {request.user.email} after creating it during folder upload")
                else:
                    logger.info(f"Board already exists at path: {current_path}")
                
                current_parent = boards_by_path[current_path]
            
            # Upload the file to the target board (or root if no folders)
            target_board = current_parent if folder_parts else parent_board
            
            # Get quick metadata first
            file_metadata = quick_file_metadata(file)
            
            # Create asset with initial metadata first (with temporary file path)
            asset = Asset.objects.create(
                workspace=workspace,
                created_by=request.user,
                file="temp",  # Temporary value, will be updated below
                status=Asset.Status.PROCESSING,
                size=file.size,
                file_type=file_metadata.file_type,
                mime_type=file_metadata.mime_type,
                file_extension=file_metadata.file_extension,
                width=file_metadata.dimensions[0] if file_metadata.dimensions else None,
                height=file_metadata.dimensions[1] if file_metadata.dimensions else None,
                name=filename
            )
            
            # Generate the correct S3 key using workspace_asset_path
            from .models import workspace_asset_path
            s3_key = workspace_asset_path(asset, filename)
            
            # Update the asset with the correct file path
            asset.file = s3_key
            asset.save()
            
            # Save the file to S3 using Django's storage backend
            # This will automatically use the correct S3 configuration
            saved_path = default_storage.save(s3_key, file)
            asset.file = saved_path
            asset.save()
            
            logger.info(f"Saved file to S3: {saved_path}")
            
            # Add to board if we have one
            if target_board:
                BoardAsset.objects.create(
                    board=target_board,
                    asset=asset,
                    added_by=request.user
                )
                logger.info(f"Added asset {asset.id} to board {target_board.name}")
                
                # Smart Auto-Follow: Follow board when user uploads to it
                from main.services.notifications import NotificationService
                if not NotificationService.is_following_board(request.user, target_board):
                    NotificationService.follow_board(
                        user=request.user,
                        board=target_board,
                        include_sub_boards=False  # Conservative default
                    )
                    logger.info(f"Auto-followed board '{target_board.name}' for user {request.user.email} after folder upload")
            else:
                logger.info(f"Asset {asset.id} added to workspace root (no board)")
    
    return created_boards


@router.get("/workspaces/{uuid:workspace_id}/assets/{uuid:asset_id}", response=AssetSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_asset(request, workspace_id: UUID, asset_id: UUID):
    asset = get_object_or_404(
        Asset.objects.filter(workspace_id=workspace_id),
        id=asset_id
    )
    return asset

@router.post("/workspaces/{uuid:workspace_id}/assets", response=PaginatedAssetResponse)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def list_assets(
    request,
    workspace_id: UUID,
    filters: Optional[AssetListFilters] = None,
):  
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Use defaults if no filters provided
    if not filters:
        filters = AssetListFilters()
    
    # Debug logging
    print(f"DEBUG: Received filters: {filters}")
    print(f"DEBUG: Board ID: {filters.board_id}")
    print(f"DEBUG: Custom fields: {filters.custom_fields}")
    
    # Calculate offset
    offset = (filters.page - 1) * filters.page_size
    
    # Base query with prefetched boards
    query = Asset.objects.filter(workspace_id=workspace_id).prefetch_related('boards')
    
    # Filter by board if specified
    board = None
    if filters.board_id:
        board = get_object_or_404(Board, workspace=workspace, id=filters.board_id)
        query = query.filter(boards=board)
    
    # Add search filter if search term provided
    if filters.search:
        query = query.filter(file__icontains=filters.search)
    
    # Apply custom field filters
    if filters and filters.custom_fields:
        asset_content_type = ContentType.objects.get_for_model(Asset)
        
        for field_filter in filters.custom_fields:
            field_obj = get_object_or_404(CustomField, workspace=workspace, id=field_filter.id)
            filter_criteria = field_filter.filter
            
            if filter_criteria.not_set:
                logger.info(f"Filtering for assets that don't have field {field_obj} set")
                # Filter for assets that don't have this field set
                query = query.exclude(
                    id__in=CustomFieldValue.objects.filter(
                        field=field_obj,
                        content_type=asset_content_type
                    ).values_list('object_id', flat=True)
                )
            
            elif filter_criteria.is_:
                logger.info(f"Filtering for assets that have field {field_obj} set to {filter_criteria.is_}")
                # Filter by specific option value (single-select or multi-select)
                option = get_object_or_404(CustomFieldOption, field=field_obj, id=filter_criteria.is_)
                
                if field_obj.field_type == 'SINGLE_SELECT':
                    query = query.filter(
                        id__in=CustomFieldValue.objects.filter(
                            field=field_obj,
                            content_type=asset_content_type,
                            option_value=option
                        ).values_list('object_id', flat=True)
                    )
                elif field_obj.field_type == 'MULTI_SELECT':
                    query = query.filter(
                        id__in=CustomFieldValue.objects.filter(
                            field=field_obj,
                            content_type=asset_content_type,
                            multi_options=option
                        ).values_list('object_id', flat=True)
                    )
            
            elif filter_criteria.contains and field_obj.field_type == 'TEXT':
                # Text contains filter
                query = query.filter(
                    id__in=CustomFieldValue.objects.filter(
                        field=field_obj,
                        content_type=asset_content_type,
                        text_value__icontains=filter_criteria.contains
                    ).values_list('object_id', flat=True)
                )
            
            elif (filter_criteria.date_from or filter_criteria.date_to) and field_obj.field_type == 'DATE':
                # Date range filter
                date_q = Q()
                if filter_criteria.date_from:
                    date_q &= Q(date_value__gte=filter_criteria.date_from)
                if filter_criteria.date_to:
                    date_q &= Q(date_value__lte=filter_criteria.date_to)
                
                query = query.filter(
                    id__in=CustomFieldValue.objects.filter(
                        field=field_obj,
                        content_type=asset_content_type
                    ).filter(date_q).values_list('object_id', flat=True)
                )
    
    # Apply other filters
    if filters:
        if filters.file_type:
            query = query.filter(file_type__in=filters.file_type)
        
        if filters.favorite is not None:
            query = query.filter(favorite=filters.favorite)
        
        if filters.date_uploaded_from:
            query = query.filter(date_uploaded__gte=filters.date_uploaded_from)
        
        if filters.date_uploaded_to:
            query = query.filter(date_uploaded__lte=filters.date_uploaded_to)
    
    # TODO: Implement tag filtering when tags are ready
    # if filters.tags:
    #     if filters.tags.includes:
    #         query = query.filter(tags__name__in=filters.tags.includes)
    #     if filters.tags.excludes:
    #         query = query.exclude(tags__name__in=filters.tags.excludes)
    
    # Determine the sort order
    order_by = filters.order_by
    
    # If filtering by board and no explicit order_by provided, use board's default_sort
    if board and filters.order_by == '-date_uploaded':  # Default from AssetListFilters
        order_by = board.default_sort
    
    # Handle custom sorting for boards
    if board and order_by == 'custom':
        # For custom sorting, we need to join with BoardAsset table and order by the order field
        query = query.select_related().annotate(
            board_order=models.Subquery(
                BoardAsset.objects.filter(
                    board=board,
                    asset_id=models.OuterRef('id')
                ).values('order')[:1]
            )
        ).order_by('board_order', 'date_uploaded')
    else:
        # Use standard ordering
        query = query.order_by(order_by)
    
    # Get total count before applying pagination
    total_count = query.distinct().count()
    
    # Calculate pagination metadata
    total_pages = (total_count + filters.page_size - 1) // filters.page_size  # Ceiling division
    has_more = filters.page < total_pages
    
    # Get paginated and filtered assets
    assets = query.distinct()[offset:offset + filters.page_size]
    
    return {
        "data": list(assets),
        "pagination": {
            "page": filters.page,
            "page_size": filters.page_size,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_more": has_more
        }
    }

@router.get("/products", response=ProductSubscriptionSchema)
def products(request, workspace_id: str):
    products = Product.objects.values(
        "id", "name", "description", "created_at", "updated_at", "status"
    )
    subscriptions = Subscription.objects.filter(
        account_id=workspace_id
    ).prefetch_related("products").all()
    
    return {
        "products": list(products),
        "subscriptions": list(subscriptions)
    }

@router.get("/subscriptions/plans", response=List[PlanOut])
def get_subscription_plans(request):
    """Get all active subscription plans with their prices"""
    products = Product.objects.filter(
        status='active'
    ).prefetch_related('prices')
    
    plans = []
    for product in products:
        price = product.prices.first()  # Get first price for the product
        if price:
            data = price.get_data()  # Get the Paddle price data
            product_data = product.get_data()  # Get the Paddle product data
            
            # Get billing period from billing_cycle
            billing_period = None
            if data and data.billing_cycle:
                billing_period = data.billing_cycle.interval

            plans.append({
                "id": str(product.id),
                "name": product.name,
                "description": product_data.description if product_data else None,
                "price_id": str(price.id),
                "unit_price": float(data.unit_price.amount) if data and data.unit_price else 0,
                "billing_period": billing_period,
                "features": product.custom_data.get('features', []) if product.custom_data else []
            })
    
    return plans

@router.post("/workspaces/{uuid:workspace_id}/subscription/cancel/{subscription_id}")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def cancel_subscription(request, workspace_id: UUID, subscription_id: str):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    try:
        subscription = Subscription.objects.get(id=subscription_id)
        
        if not subscription:
            raise ValidationError("No matching subscription found")
        request_data = SubscriptionRequest(effective_from="next_billing_period")

        # Cancel the subscription through Paddle        
        response = paddle_client.cancel_subscription(
            subscription_id=subscription_id,
            data=request_data
        )
        
        logger.info(f"Subscription {subscription.id} cancelled successfully: {response}")
        return {"message": "Subscription cancelled successfully"}
        
    except Exception as e:
        logger.error(f"Error cancelling subscription: {str(e)}")
        raise ValidationError("Failed to cancel subscription")

class SubscriptionItemSchema(Schema):
    price_id: str
    quantity: int = 1

class UpdateSubscriptionSchema(Schema):
    items: List[SubscriptionItemSchema]
    proration_billing_mode: str = "prorated_immediately"

@router.post("/workspaces/{uuid:workspace_id}/subscription/{subscription_id}/preview")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def preview_subscription_update(
    request, 
    workspace_id: UUID, 
    subscription_id: str,
    new_plan_price_id: str
):
    """Preview subscription update before confirming"""
    
    try:
        # Create subscription request
        subscription_data = SubscriptionRequest(
            items=[{"price_id": new_plan_price_id, "quantity": 1}],
            proration_billing_mode="prorated_immediately"
        )
        
        # Get preview from Paddle
        preview = paddle_client.preview_update_subscription(
            subscription_id=subscription_id,
            data=subscription_data
        )
        
        return preview
        
    except Exception as e:
        logger.error(f"Error previewing subscription update: {str(e)}")
        raise ValidationError("Failed to preview subscription update")

@router.post("/workspaces/{uuid:workspace_id}/subscription/{subscription_id}/update")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def update_subscription(
    request, 
    workspace_id: UUID, 
    subscription_id: str,
    new_plan_price_id: str
):
    """Confirm and apply subscription update"""
    try:
        # Create subscription request
        subscription_data = SubscriptionRequest(
            items=[{"price_id": new_plan_price_id, "quantity": 1}],
            proration_billing_mode="prorated_immediately"
        )
        
        # Get preview from Paddle
        response = paddle_client.update_subscription(
            subscription_id=subscription_id,
            data=subscription_data
        )
        
        logger.info(f"Subscription {subscription_id} updated successfully: {response}")
        return {"message": "Subscription updated successfully"}
        
    except Exception as e:
        logger.error(f"Error updating subscription: {str(e)}")
        raise ValidationError("Failed to update subscription")

@router.get("/workspaces/{uuid:workspace_id}/subscription/transactions", response=List[TransactionSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def get_subscription_transactions(request, workspace_id: UUID):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    subscriptions = workspace.subscriptions.all()
    if not subscriptions:
        return []
    
    try:
        # Loop through all subscriptions and get transactions 
        transactions = []
        for subscription in subscriptions:
            items = subscription.transactions.all()
            transactions.extend(items)

        print(transactions)
        return transactions
    
    except Exception as e:
        logger.error(f"Error fetching transactions: {str(e)}")
        raise HttpError(400, "Failed to fetch transactions")

@router.get("/workspaces/{uuid:workspace_id}/subscription/update-payment-method")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def get_subscription_update_payment_transaction(request, workspace_id: UUID):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    subscription = workspace.subscriptions.first()
    
    if not subscription:
        raise HttpError(404, "No subscription found")
        
    try:
        logger.info(f"Getting update payment method for subscription {subscription.id}")
        transaction = paddle_client.get_transaction_to_update_payment_method(
            subscription_id=subscription.id
        )
        
        return transaction
        
    except Exception as e:
        logger.error(f"Error getting update payment transaction: {str(e)}")
        raise HttpError(400, "Failed to get update payment transaction")

@router.post("/workspaces/{uuid:workspace_id}/boards", response=BoardOutSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def create_board(request, workspace_id: UUID, data: BoardCreateSchema):
    """Create a new board in the workspace"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # If parent_id is provided, verify it exists and belongs to the same workspace
    parent = None
    if data.parent_id:
        parent = get_object_or_404(
            Board.objects.filter(workspace_id=workspace_id),
            id=data.parent_id
        )
    
    # If kanban_group_by_field_id is provided, verify it exists and belongs to the same workspace
    kanban_group_by_field = None
    if data.kanban_group_by_field_id:
        kanban_group_by_field = get_object_or_404(
            CustomField.objects.filter(workspace_id=workspace_id),
            id=data.kanban_group_by_field_id
        )
        # Validate that it's a single-select field
        if kanban_group_by_field.field_type != 'SINGLE_SELECT':
            raise HttpError(400, "Kanban grouping field must be a single-select field")
    
    board = Board.objects.create(
        workspace=workspace,
        name=data.name,
        description=data.description if data.description else None,
        parent=parent,
        created_by=request.user,
        default_view=data.default_view or 'GALLERY',
        kanban_group_by_field=kanban_group_by_field,
        default_sort=data.default_sort or '-date_uploaded'
    )
    
    # Smart Auto-Follow: Follow board when user creates it
    from main.services.notifications import NotificationService
    if not NotificationService.is_following_board(request.user, board):
        NotificationService.follow_board(
            user=request.user,
            board=board,
            include_sub_boards=True,  # Board creators get sub-board notifications by default
            auto_followed=True  # Mark as auto-followed
        )
        logger.info(f"Auto-followed board '{board.name}' for user {request.user.email} after creating it")
    
    # Trigger sub-board notifications if this is a sub-board
    if parent:
        NotificationService.notify_sub_board_created(board)
    
    return board

@router.get("/workspaces/{uuid:workspace_id}/boards", response=List[BoardOutSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def list_boards(
    request, 
    workspace_id: UUID,
    parent_id: Optional[UUID] = None,
    recursive: bool = False
):
    """
    List boards in the workspace
    - If parent_id is None, returns root boards
    - If parent_id is provided, returns child boards
    - If recursive is True, returns all descendants including the parent board
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Base queryset with optimized fetching
    base_queryset = Board.objects.select_related('kanban_group_by_field').prefetch_related('children')
    
    if parent_id:
        parent = get_object_or_404(Board, workspace=workspace, id=parent_id)
        if recursive:
            # Start with the parent board
            boards = [parent]
            # Add all descendants with optimized query
            descendants = parent.get_descendants().select_related('kanban_group_by_field')
            boards.extend(descendants)
            return boards
        return list(base_queryset.filter(workspace=workspace, parent=parent_id))
    else:
        # Return root boards (no parent)
        logger.info(f"Getting root boards for workspace {workspace.id}")
        root_boards = list(base_queryset.filter(workspace=workspace, parent=None))
        if recursive:
            # When recursive is True, we only want the root boards with their children
            # The children will be included in the response through the schema
            return root_boards
        return root_boards

@router.get("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}", response=BoardOutSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_board(request, workspace_id: UUID, board_id: UUID):
    """Get a specific board"""
    board = get_object_or_404(
        Board.objects.select_related('kanban_group_by_field').filter(workspace_id=workspace_id),
        id=board_id
    )
    return board

@router.get("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}/ancestors", response=List[BoardOutSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_board_ancestors(request, workspace_id: UUID, board_id: UUID):
    """Get all ancestor boards up to root"""
    board = get_object_or_404(
        Board.objects.filter(workspace_id=workspace_id),
        id=board_id
    )
    return board.get_ancestors()

@router.put("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}", response=BoardOutSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def update_board(request, workspace_id: UUID, board_id: UUID, data: BoardUpdateSchema):
    """Update a board"""
    board = get_object_or_404(
        Board.objects.filter(workspace_id=workspace_id),
        id=board_id
    )
    
    if data.name is not None:
        board.name = data.name
    if data.description is not None:
        board.description = data.description
    if data.parent_id is not None:
        # Prevent circular references
        if data.parent_id == board.id:
            raise HttpError(400, "Board cannot be its own parent")
        if isinstance(data.parent_id, UUID) and data.parent_id in [b.id for b in board.get_descendants()]:
            raise HttpError(400, "Cannot set a descendant as parent")
            
        # If parent_id is "root", set parent to None (root level)
        if data.parent_id == "root":
            logger.info(f"Setting board {board.id} to root level")
            board.parent = None
            board.level = 0
        else:
            parent = get_object_or_404(
                Board.objects.filter(workspace_id=workspace_id),
                id=data.parent_id
            )
            board.parent = parent
    
    if data.default_view is not None:
        board.default_view = data.default_view
    
    if data.default_sort is not None:
        board.default_sort = data.default_sort
    
    if data.kanban_group_by_field_id is not None:
        if data.kanban_group_by_field_id == 0:  # Allow setting to None/null
            board.kanban_group_by_field = None
        else:
            kanban_group_by_field = get_object_or_404(
                CustomField.objects.filter(workspace_id=workspace_id),
                id=data.kanban_group_by_field_id
            )
            # Validate that it's a single-select field
            if kanban_group_by_field.field_type != 'SINGLE_SELECT':
                raise HttpError(400, "Kanban grouping field must be a single-select field")
            board.kanban_group_by_field = kanban_group_by_field
        
    board.save()
    return board

@router.delete("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def delete_board(request, workspace_id: UUID, board_id: UUID):
    """Delete a board"""
    board = get_object_or_404(
        Board.objects.filter(workspace_id=workspace_id),
        id=board_id
    )
    board.delete()
    return {"success": True}

@router.post("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}/assets/reorder")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def reorder_board_assets(request, workspace_id: UUID, board_id: UUID, data: AssetReorderRequestSchema):
    """Reorder assets within a board for custom sorting"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    board = get_object_or_404(Board, workspace=workspace, id=board_id)
    
    # Use the board's reorder_assets method
    board.reorder_assets(data.asset_ids)
    
    # Optionally set the board's default_sort to 'custom' if it isn't already
    if board.default_sort != 'custom':
        board.default_sort = 'custom'
        board.save()
    
    return {"success": True, "reordered_count": len(data.asset_ids)}

@router.post("/workspaces/{uuid:workspace_id}/assets/{uuid:asset_id}/download", response=DownloadResponseSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def initiate_download(request, workspace_id: UUID, asset_id: UUID, data: DownloadInitiateSchema):
    """
    Initiate a file download, supporting both single file and multipart downloads.
    For large files (>5MB), multipart download is recommended for better reliability and performance.
    """
    asset = get_object_or_404(
        Asset.objects.filter(workspace_id=workspace_id),
        id=asset_id
    )
    
    try:
        download_info = DownloadManager.initiate_download(
            asset=asset,
            use_multipart=data.use_multipart,
            part_size=data.part_size
        )
        return download_info
    except Exception as e:
        logger.error(f"Error initiating download for asset {asset_id}: {str(e)}")
        raise HttpError(500, "Failed to initiate download")

@router.post("/workspaces/{uuid:workspace_id}/assets/bulk/tags")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def bulk_update_tags(request, workspace_id: UUID, data: AssetBulkTagsSchema):
    """Update tags for multiple assets"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Get assets that belong to this workspace
    assets = Asset.objects.filter(
        workspace=workspace,
        id__in=data.asset_ids
    )
    
    # Update tags for each asset
    for asset in assets:
        asset.metadata = asset.metadata or {}
        asset.metadata["tags"] = data.tags
        asset.save()
    
    return {"success": True, "updated_count": assets.count()}

@router.post("/workspaces/{uuid:workspace_id}/assets/bulk/favorite")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def bulk_toggle_favorite(request, workspace_id: UUID, data: AssetBulkFavoriteSchema):
    """Toggle favorite status for multiple assets"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Get assets that belong to this workspace
    assets = Asset.objects.filter(
        workspace=workspace,
        id__in=data.asset_ids
    )
    
    # Update favorite status for each asset
    for asset in assets:
        asset.favorite = data.favorite
        asset.save()
    
    return {"success": True, "updated_count": assets.count()}

@router.post("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}/assets")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def bulk_add_to_board(request, workspace_id: UUID, board_id: UUID, data: AssetBulkBoardSchema):
    """Add multiple assets to a board"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    board = get_object_or_404(Board, workspace=workspace, id=board_id)
    
    # Get assets that belong to this workspace
    assets = Asset.objects.filter(
        workspace=workspace,
        id__in=data.asset_ids
    )
    
    # Add assets to board
    count = 0
    for asset in assets:
        # Check if the relationship already exists to avoid duplicates
        if not board.assets.filter(id=asset.id).exists():
            board.assets.add(asset)
            count += 1
    
    # Smart Auto-Follow: Follow board when user adds assets to it
    if count > 0:  # Only if we actually added assets
        from main.services.notifications import NotificationService
        if not NotificationService.is_following_board(request.user, board):
            NotificationService.follow_board(
                user=request.user,
                board=board,
                include_sub_boards=False,  # Conservative default
                auto_followed=True  # Mark as auto-followed
            )
            logger.info(f"Auto-followed board '{board.name}' for user {request.user.email} after adding {count} assets")
    
    return {"success": True, "added_count": count}

@router.post("/workspaces/{uuid:workspace_id}/assets/bulk/move")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def bulk_move_assets(request, workspace_id: UUID, data: AssetBulkMoveSchema):
    """Move multiple assets to a destination (workspace root or board)"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Get assets that belong to this workspace
    assets = Asset.objects.filter(
        workspace=workspace,
        id__in=data.asset_ids
    )
    
    if data.destination_type == 'board':
        # Move to a specific board
        board = get_object_or_404(Board, workspace=workspace, id=data.destination_id)
        
        # First remove assets from all boards (if moving between boards)
        for asset in assets:
            asset.boards.clear()
            # Then add to the destination board
            asset.boards.add(board)
        
        # Smart Auto-Follow: Follow board when user moves assets to it
        from main.services.notifications import NotificationService
        if not NotificationService.is_following_board(request.user, board):
            NotificationService.follow_board(
                user=request.user,
                board=board,
                include_sub_boards=False,  # Conservative default
                auto_followed=True  # Mark as auto-followed
            )
            logger.info(f"Auto-followed board '{board.name}' for user {request.user.email} after moving {assets.count()} assets")
            
    elif data.destination_type == 'workspace':
        # Move to workspace root (remove from all boards)
        for asset in assets:
            asset.boards.clear()
    
    return {"success": True, "moved_count": assets.count()}

@router.delete("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}/assets")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def bulk_remove_from_board(request, workspace_id: UUID, board_id: UUID, data: AssetBulkBoardSchema):
    """Remove multiple assets from a board"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    board = get_object_or_404(Board, workspace=workspace, id=board_id)
    
    # Get assets that belong to this workspace
    assets = Asset.objects.filter(
        workspace=workspace,
        id__in=data.asset_ids
    )
    
    # Remove assets from board
    count = 0
    for asset in assets:
        if board.assets.filter(id=asset.id).exists():
            board.assets.remove(asset)
            count += 1
    
    return {"success": True, "removed_count": count}

@router.delete("/workspaces/{uuid:workspace_id}/assets/bulk")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def bulk_delete_assets(request, workspace_id: UUID, data: AssetBulkDeleteSchema):
    """Delete multiple assets"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Get assets that belong to this workspace
    assets = Asset.objects.filter(
        workspace=workspace,
        id__in=data.asset_ids
    )
    
    # Delete assets
    count = assets.count()
    assets.delete()
    
    return {"success": True, "deleted_count": count}

@router.post("/workspaces/{uuid:workspace_id}/assets/bulk/download", response=BulkDownloadResponseSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def bulk_download_assets(request, workspace_id: UUID, data: AssetBulkDownloadSchema):
    """Create a server-side ZIP archive of multiple assets and provide a download link"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Get assets that belong to this workspace
    assets = Asset.objects.filter(
        workspace=workspace,
        id__in=data.asset_ids
    )
    
    if not assets:
        raise HttpError(404, "No assets found for the provided IDs")
    
    try:
        # Generate ZIP archive using AWS Lambda
        zip_result = DownloadManager.create_zip_archive(
            assets=list(assets),
            zip_name=f"workspace-{workspace_id}-assets"
        )
        
        return {
            "download_url": zip_result["download_url"],
            "expires_at": zip_result["expires_at"],
            "asset_count": zip_result["file_count"],
            "zip_size": zip_result["zip_size"]
        }
    except Exception as e:
        logger.error(f"Error creating bulk download: {str(e)}")
        raise HttpError(500, "Failed to create bulk download")

@router.post("/workspaces/{uuid:workspace_id}/boards/reorder", response={200: dict})
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def reorder_boards(request, workspace_id: UUID, data: List[BoardReorderSchema]):
    """Reorder boards in a workspace"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    with transaction.atomic():
        for item in data:
            board = get_object_or_404(Board, workspace=workspace, id=item.board_id)
            board.order = item.new_order
            board.save()
    
    return {"success": True}

@router.get("/workspaces/{uuid:workspace_id}/fields", response=List[CustomFieldSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def list_custom_fields(request, workspace_id: UUID):
    """List all custom fields in a workspace"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    return CustomField.objects.filter(workspace=workspace).prefetch_related(
        'options',
        'options__ai_action_configs'
    ).select_related('workspace')

def _process_field_options(field: CustomField, options_data: List[FieldOption]):
    """Helper function to process field options and AI actions"""
    existing_option_ids = set(field.options.values_list('id', flat=True))
    processed_option_ids = set()

    for option_data in options_data:
        if option_data.should_delete and option_data.id:
            # Delete existing option
            field.options.filter(id=option_data.id).delete()
            continue

        if option_data.id:
            try:
                # Update existing option
                option = field.options.get(id=option_data.id)
                option.label = option_data.label
                option.color = option_data.color
                option.order = option_data.order or 0
                option.save()
                processed_option_ids.add(option.id)
            except CustomFieldOption.DoesNotExist:
                # If option doesn't exist, get or create one with this label
                option, created = CustomFieldOption.objects.get_or_create(
                    field=field,
                    label=option_data.label,
                    defaults={
                        'color': option_data.color,
                        'order': option_data.order or 0
                    }
                )
                if not created:
                    # Option already existed, update its properties
                    option.color = option_data.color
                    option.order = option_data.order or 0
                    option.save()
                processed_option_ids.add(option.id)
        else:
            # Create new option, or get existing one with same label
            option, created = CustomFieldOption.objects.get_or_create(
                field=field,
                label=option_data.label,
                defaults={
                    'color': option_data.color,
                    'order': option_data.order or 0
                }
            )
            if not created:
                # Option already existed, update its properties
                option.color = option_data.color
                option.order = option_data.order or 0
                option.save()
            processed_option_ids.add(option.id)

        # Process AI actions for this option
        if field.field_type == 'SINGLE_SELECT':
            for action_data in option_data.ai_actions:
                action_config, created = CustomFieldOptionAIAction.objects.update_or_create(
                    option=option,
                    action=action_data.action,
                    defaults={
                        'is_enabled': action_data.is_enabled,
                        'configuration': action_data.configuration
                    }
                )

            # Remove any AI actions that weren't in the update
            option.ai_action_configs.exclude(
                action__in=[a.action for a in option_data.ai_actions]
            ).delete()

    # Delete options that weren't processed (i.e., removed from the frontend)
    to_delete = existing_option_ids - processed_option_ids
    if to_delete:
        field.options.filter(id__in=to_delete).delete()

@router.post("/workspaces/{uuid:workspace_id}/fields", response=CustomFieldSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def create_field(request, workspace_id: UUID, data: FieldConfiguration):
    """
    Create a new custom field in a workspace.
    
    This endpoint creates a new field with its options and AI actions. For SINGLE_SELECT
    and MULTI_SELECT fields, you can define options with colors and ordering. For
    SINGLE_SELECT fields, options can also have AI actions that trigger when the option
    is selected.
    
    Available field types:
    - SINGLE_SELECT: Single choice from predefined options
    - MULTI_SELECT: Multiple choices from predefined options
    - TEXT: Plain text input
    - DATE: Date/time input
    
    Available AI actions for SINGLE_SELECT options:
    - grammar: Checks grammar in text
      Config: {"language": "en-US|de|es|fr|it|pt|nl|ar|ja|zh-CN|..."}
      Use GET /ai-actions/language-choices to get full language metadata
    - color_contrast: Analyzes color contrast for accessibility
      Config: {}
    - color_blindness: Analyzes content for color blindness accessibility
      Config: {}
    - image_quality: Checks image resolution and quality
      Config: {}
    - font_size_detection: Detects and analyzes font sizes in text
      Config: {}
    - text_overflow: Detects text that overflows its container
      Config: {}

    - placeholder_detection: Detects placeholder text that should be replaced
      Config: {}
    - repeated_text: Detects repeated or duplicated text content
      Config: {}
    
    Permissions:
    - Requires ADMIN role in the workspace
    
    Returns:
    - The created field with its options and AI actions
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    with transaction.atomic():
        # Check for existing field with same title
        if CustomField.objects.filter(workspace=workspace, title=data.title).exists():
            raise HttpError(400, f"A field with title '{data.title}' already exists")
            
        # Create the field
        field = CustomField.objects.create(
            workspace=workspace,
            title=data.title,
            field_type=data.field_type,
            description=data.description
        )

        # Process options and AI actions
        _process_field_options(field, data.options)
        
        return field

@router.put("/workspaces/{uuid:workspace_id}/fields/{int:field_id}", response=CustomFieldSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def update_field(request, workspace_id: UUID, field_id: int, data: FieldConfiguration):
    """
    Update an existing custom field.
    
    This endpoint updates a field's properties, options, and AI actions. You can:
    - Change the field's title and description
    - Update existing options (requires option ID)
    - Add new options (omit option ID)
    - Delete options (set should_delete=true)
    - Update AI actions for options
    
    When updating options:
    - Include 'id' to update an existing option
    - Omit 'id' to create a new option
    - Set 'should_delete: true' to remove an option
    - Options not included in the request remain unchanged
    - If an option ID doesn't exist, a new option will be created
    
    When updating AI actions:
    - All AI actions for an option must be included
    - AI actions not included will be removed
    - Only applicable for SINGLE_SELECT fields
    
    Permissions:
    - Requires ADMIN role in the workspace
    
    Returns:
    - The updated field with its options and AI actions
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    field = get_object_or_404(CustomField, workspace=workspace, id=field_id)
    
    with transaction.atomic():
        # Check for title uniqueness only if title changed
        if field.title != data.title and CustomField.objects.filter(
            workspace=workspace, 
            title=data.title
        ).exists():
            raise HttpError(400, f"A field with title '{data.title}' already exists")
        
        # Update the field
        field.title = data.title
        field.field_type = data.field_type
        field.description = data.description
        field.save()

        # Process options and AI actions
        _process_field_options(field, data.options)
        
        return field

@router.get("/workspaces/{uuid:workspace_id}/assets/{uuid:asset_id}/field-values", response=List[CustomFieldValueSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_asset_field_values(request, workspace_id: UUID, asset_id: UUID):
    """Get all custom field values for an asset"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    asset = get_object_or_404(Asset, workspace=workspace, id=asset_id)
    content_type = ContentType.objects.get_for_model(Asset)
    
    return CustomFieldValue.objects.filter(
        content_type=content_type,
        object_id=asset.id
    ).select_related(
        'field',
        'option_value'
    ).prefetch_related('multi_options')

@router.get("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}/field-values", response=List[CustomFieldValueSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_board_field_values(request, workspace_id: UUID, board_id: UUID):
    """Get all custom field values for a board"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    board = get_object_or_404(Board, workspace=workspace, id=board_id)
    content_type = ContentType.objects.get_for_model(Board)
    
    return CustomFieldValue.objects.filter(
        content_type=content_type,
        object_id=board.id
    ).select_related(
        'field',
        'option_value'
    ).prefetch_related('multi_options')

@router.post("/workspaces/{uuid:workspace_id}/custom-fields/{int:field_id}/values", response=CustomFieldValueSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def set_field_value(
    request,
    workspace_id: UUID,
    field_id: int,
    data: CustomFieldValueCreate
):
    """Set a custom field value for an asset or board with optional board context for AI actions"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    field = get_object_or_404(CustomField, workspace=workspace, id=field_id)
    
    # Validate content type
    if data.content_type not in ['asset', 'board']:
        raise HTTPException(400, "Invalid content type")
    
    # Get the content type and object
    model = Asset if data.content_type == 'asset' else Board
    content_type_obj = ContentType.objects.get_for_model(model)
    content_object = get_object_or_404(model, workspace=workspace, id=data.object_id)
    
    # Validate board context if provided
    board_context = None
    if data.board_id:
        board_context = get_object_or_404(Board, workspace=workspace, id=data.board_id)
        
        # Validate that the asset belongs to the specified board
        if data.content_type == 'asset':
            asset_in_board = BoardAsset.objects.filter(
                board=board_context, 
                asset_id=data.object_id
            ).exists()
            if not asset_in_board:
                raise HttpError(400, f"Asset does not belong to the specified board")
    
    # Get or create the field value
    field_value, created = CustomFieldValue.objects.get_or_create(
        field=field,
        content_type=content_type_obj,
        object_id=data.object_id
    )
    
    # Update the value based on field type
    if field.field_type == 'TEXT':
        field_value.text_value = data.text_value
    elif field.field_type == 'DATE':
        field_value.date_value = data.date_value
    elif field.field_type == 'SINGLE_SELECT':
        if data.option_value_id:
            option = get_object_or_404(CustomFieldOption, field=field, id=data.option_value_id)
            field_value.option_value = option
    elif field.field_type == 'MULTI_SELECT':
        if data.multi_option_ids:
            options = CustomFieldOption.objects.filter(
                field=field,
                id__in=data.multi_option_ids
            )
            field_value.multi_options.set(options)
    
    # Set flag to prevent signal from triggering, then save
    if field.field_type == 'SINGLE_SELECT' and field_value.option_value:
        from main.services.ai_actions import _thread_local
        _thread_local.api_triggered = True
    
    field_value.save()
    
    # Trigger AI actions with board context if applicable
    if field.field_type == 'SINGLE_SELECT' and field_value.option_value:
        from main.services.ai_actions import trigger_ai_actions
        try:
            trigger_ai_actions(field_value, board_context)
        finally:
            # Clean up the flag
            _thread_local.api_triggered = False
    
    return field_value

@router.get("/workspaces/{uuid:workspace_id}/ai-actions/available", response=List[Dict])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_available_ai_actions(request, workspace_id: UUID):
    """Get list of available AI actions and their configurations"""
    actions = []
    for action, name in AIActionChoices.choices:
        definition = AIActionDefinition.get_definition(action)
        
        # Add language choices for grammar action
        if action == 'grammar':
            definition = definition.copy()
            definition['language_choices'] = AIActionDefinition.get_language_choices()
            
        actions.append({
            'id': action,
            'name': name,
            'definition': definition
        })
    
    return actions

@router.get("/workspaces/{uuid:workspace_id}/ai-actions/language-choices", response=List[Dict])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_language_choices(request, workspace_id: UUID):
    """Get available language choices for grammar checking"""
    return AIActionDefinition.get_language_choices()

@router.get("/workspaces/{uuid:workspace_id}/ai-actions/results", response=List[AIActionResultSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_ai_action_results(
    request,
    workspace_id: UUID,
    content_type: str,
    object_id: UUID
):
    """Get all AI action results for an asset or board"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Validate content type
    if content_type not in ['asset', 'board']:
        raise HTTPException(400, "Invalid content type")
    
    # Get the content type and object
    model = Asset if content_type == 'asset' else Board
    content_type_obj = ContentType.objects.get_for_model(model)
    content_object = get_object_or_404(model, workspace=workspace, id=object_id)
    
    # Get all field values and their AI results
    return AIActionResult.objects.filter(
        field_value__content_type=content_type_obj,
        field_value__object_id=object_id
    ).select_related('field_value').order_by('-created_at')

@router.delete("/workspaces/{uuid:workspace_id}/fields/{int:field_id}")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def delete_field(request, workspace_id: UUID, field_id: int):
    """
    Delete a custom field and all its related data.
    
    This endpoint will:
    - Delete all field values associated with this field
    - Delete all field options and their AI actions
    - Delete the field itself
    
    Permissions:
    - Requires ADMIN role in the workspace
    
    Returns:
    - Success confirmation
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    field = get_object_or_404(CustomField, workspace=workspace, id=field_id)
    
    with transaction.atomic():
        # The field's options and values will be deleted automatically
        # due to CASCADE delete settings in the models
        field.delete()
    
    return {"message": "Field deleted successfully"}


# Notification System Endpoints

# Board Following Endpoints
@router.post("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}/follow", response=BoardFollowerSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def follow_board(request, workspace_id: UUID, board_id: UUID, data: BoardFollowerCreate):
    """Follow a board for notifications"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    board = get_object_or_404(Board, workspace=workspace, id=data.board_id)
    
    from main.services.notifications import NotificationService
    follower = NotificationService.follow_board(
        user=request.user,
        board=board,
        include_sub_boards=data.include_sub_boards,
        auto_followed=False  # Manual follow - clear auto_followed flag
    )
    
    return BoardFollowerSchema.from_orm(follower)


@router.delete("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}/follow")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def unfollow_board(request, workspace_id: UUID, board_id: UUID):
    """Unfollow a board"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    board = get_object_or_404(Board, workspace=workspace, id=board_id)
    
    from main.services.notifications import NotificationService
    NotificationService.unfollow_board(user=request.user, board=board)
    
    return {"message": "Board unfollowed successfully"}


@router.get("/workspaces/{uuid:workspace_id}/followed-boards", response=List[BoardFollowerSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_followed_boards(request, workspace_id: UUID):
    """Get all boards the user is following in this workspace"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    from main.services.notifications import NotificationService
    followed_boards = NotificationService.get_followed_boards(request.user).filter(
        board__workspace=workspace
    )
    
    return [BoardFollowerSchema.from_orm(fb) for fb in followed_boards]


@router.get("/workspaces/{uuid:workspace_id}/boards/{uuid:board_id}/followers", response=List[dict])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_board_followers(request, workspace_id: UUID, board_id: UUID):
    """Get all followers of a board"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    board = get_object_or_404(Board, workspace=workspace, id=board_id)
    
    from main.services.notifications import NotificationService
    followers = NotificationService.get_board_followers(board)
    
    return [
        {
            'user_email': follower.user.email,
            'include_sub_boards': follower.include_sub_boards,
            'created_at': follower.created_at
        }
        for follower in followers
    ]


# Comment Endpoints
@router.post("/workspaces/{uuid:workspace_id}/comments", response=CommentSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def create_comment(request, workspace_id: UUID, data: CommentCreate):
    """Create a comment on an asset or board"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Validate content type and get object
    if data.content_type not in ['asset', 'board']:
        raise HttpError(400, "Invalid content type")
        
    model = Asset if data.content_type == 'asset' else Board
    content_type_obj = ContentType.objects.get_for_model(model)
    content_object = get_object_or_404(model, workspace=workspace, id=data.object_id)
    
    # Get parent comment if specified
    parent = None
    if data.parent_id:
        parent = get_object_or_404(Comment, id=data.parent_id)
    
    # Get board if specified for board-scoped comments
    board = None
    if data.board_id:
        board = get_object_or_404(Board, workspace=workspace, id=data.board_id)
        
        # Validate that the asset belongs to the specified board
        if data.content_type == 'asset':
            asset_in_board = BoardAsset.objects.filter(
                board=board, 
                asset_id=data.object_id
            ).exists()
            if not asset_in_board:
                raise HttpError(400, f"Asset does not belong to the specified board")
    
    # Validate annotation data
    if data.annotation_type not in ['NONE', 'POINT', 'AREA']:
        raise HttpError(400, "Invalid annotation type")
    
    if data.annotation_type == 'POINT':
        if data.x is None or data.y is None:
            raise HttpError(400, "Point annotation requires x and y coordinates")
        if data.width is not None or data.height is not None:
            raise HttpError(400, "Point annotation should not include width and height")
    
    if data.annotation_type == 'AREA':
        if any(v is None for v in [data.x, data.y, data.width, data.height]):
            raise HttpError(400, "Area annotation requires x, y, width, and height")
    
    # Create comment with board context
    comment = Comment.objects.create(
        content_type=content_type_obj,
        object_id=data.object_id,
        board=board,  # Board context - null for global comments
        author=request.user,
        text=data.text,
        parent=parent,
        annotation_type=data.annotation_type,
        x=data.x,
        y=data.y,
        width=data.width,
        height=data.height
    )
    
    # Extract and process mentions
    from main.services.notifications import NotificationService
    mentions = NotificationService.extract_mentions(data.text)
    mentioned_users = NotificationService.get_users_from_mentions(mentions)
    
    if mentioned_users:
        comment.mentioned_users.set(mentioned_users)
    
    # Smart Auto-Follow: Follow boards when user interacts with them
    boards_to_follow = []
    if data.content_type == 'asset':
        # Get all boards containing this asset
        board_assets = content_object.boardasset_set.select_related('board')
        boards_to_follow = [ba.board for ba in board_assets]
    elif data.content_type == 'board':
        # User is commenting directly on a board
        boards_to_follow = [content_object]
    
    # Auto-follow boards (only if not already following AND user hasn't explicitly unfollowed)
    for board in boards_to_follow:
        if (not NotificationService.is_following_board(request.user, board) and 
            not NotificationService.has_explicitly_unfollowed(request.user, board)):
            NotificationService.follow_board(
                user=request.user,
                board=board,
                include_sub_boards=False,  # Conservative default - user can change later
                auto_followed=True  # Mark as auto-followed
            )
            logger.info(f"Auto-followed board '{board.name}' for user {request.user.email} after commenting")
    
    # Trigger notifications
    if data.content_type == 'asset':
        NotificationService.notify_comment_on_asset(comment, content_object)
    
    if mentioned_users:
        NotificationService.notify_mentions(comment, mentioned_users)
    
    if parent:
        NotificationService.notify_thread_reply(comment)
    
    return CommentSchema.from_orm(comment)


@router.get("/workspaces/{uuid:workspace_id}/comments", response=List[CommentSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_comments(
    request, 
    workspace_id: UUID, 
    content_type: str, 
    object_id: UUID,
    board_id: Optional[UUID] = None
):
    """Get comments for an asset or board with optional board context filtering"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Validate content type and object
    if content_type not in ['asset', 'board']:
        raise HttpError(400, "Invalid content type")
        
    model = Asset if content_type == 'asset' else Board
    content_type_obj = ContentType.objects.get_for_model(model)
    content_object = get_object_or_404(model, workspace=workspace, id=object_id)
    
    # Handle board_id parameter
    board = None
    if board_id:
        board = get_object_or_404(Board, workspace=workspace, id=board_id)
        
        # Validate that the asset belongs to the specified board
        if content_type == 'asset':
            asset_in_board = BoardAsset.objects.filter(
                board=board, 
                asset_id=object_id
            ).exists()
            if not asset_in_board:
                raise HttpError(400, f"Asset does not belong to the specified board")
    
    # Get comments filtered by board context
    # board=None returns global comments, board=Board returns board-specific comments
    comments = Comment.objects.filter(
        content_type=content_type_obj,
        object_id=object_id,
        board=board  # This will filter by board context (None for global, board for specific)
    ).select_related('author', 'parent', 'board').prefetch_related('mentioned_users', 'replies').order_by('created_at')
    
    return [CommentSchema.from_orm(comment) for comment in comments]


@router.put("/workspaces/{uuid:workspace_id}/comments/{int:comment_id}", response=CommentSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def update_comment(request, workspace_id: UUID, comment_id: int, data: CommentUpdate):
    """Update a comment (only by the author)"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    comment = get_object_or_404(Comment, id=comment_id)
    
    # Check if user is the author
    if comment.author != request.user:
        raise HttpError(403, "You can only edit your own comments")
    
    # Check if the content object belongs to this workspace
    if hasattr(comment.content_object, 'workspace'):
        if comment.content_object.workspace != workspace:
            raise HttpError(404, "Comment not found")
    
    # Update comment
    comment.text = data.text
    comment.save()
    
    # Update mentions
    from main.services.notifications import NotificationService
    mentions = NotificationService.extract_mentions(data.text)
    mentioned_users = NotificationService.get_users_from_mentions(mentions)
    comment.mentioned_users.set(mentioned_users)
    
    return CommentSchema.from_orm(comment)


@router.delete("/workspaces/{uuid:workspace_id}/comments/{int:comment_id}")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def delete_comment(request, workspace_id: UUID, comment_id: int):
    """Delete a comment (only by the author or workspace admin)"""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    comment = get_object_or_404(Comment, id=comment_id)
    
    # Check permissions
    member = WorkspaceMember.objects.get(workspace=workspace, user=request.user)
    if comment.author != request.user and member.role != WorkspaceMember.Role.ADMIN:
        raise HttpError(403, "You can only delete your own comments or be an admin")
    
    comment.delete()
    return {"message": "Comment deleted successfully"}





# Notification Preference Endpoints
@router.get("/notification-preferences", response=UserNotificationPreferenceSchema)
def get_notification_preferences(request):
    """Get notification preferences for the current user"""
    user_pref = UserNotificationPreference.get_or_create_for_user(request.user)
    return UserNotificationPreferenceSchema.from_orm(user_pref)


@router.put("/notification-preferences", response=UserNotificationPreferenceSchema)
def update_notification_preferences(request, data: UserNotificationPreferenceUpdate):
    """Update notification preferences for the current user"""
    user_pref = UserNotificationPreference.get_or_create_for_user(request.user)
    
    # Update email frequency if provided
    if data.email_frequency is not None:
        user_pref.email_frequency = data.email_frequency
    
    # Update individual event preferences
    for event_type, event_pref in data.event_preferences.items():
        # Validate event type
        from main.models import EventType
        valid_event_types = [choice[0] for choice in EventType.choices]
        if event_type not in valid_event_types:
            continue
        
        user_pref.update_event_preference(
            event_type=event_type,
            in_app_enabled=event_pref.in_app_enabled,
            email_enabled=event_pref.email_enabled
        )
    
    user_pref.save()
    return UserNotificationPreferenceSchema.from_orm(user_pref)


# Notification Endpoints
@router.get("/notifications", response=List[NotificationSchema])
def get_notifications(request, unread_only: bool = False, limit: int = 50):
    """Get notifications for the current user"""
    from notifications.models import Notification
    
    notifications = Notification.objects.filter(recipient=request.user)
    
    if unread_only:
        notifications = notifications.unread()
    
    notifications = notifications.order_by('-timestamp')[:limit]
    
    return [NotificationSchema.from_orm(notification) for notification in notifications]


@router.post("/notifications/{int:notification_id}/mark-read")
def mark_notification_read(request, notification_id: int):
    """Mark a specific notification as read"""
    from notifications.models import Notification
    
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    notification.mark_as_read()
    
    return {"message": "Notification marked as read"}


@router.post("/notifications/mark-all-read")
def mark_all_notifications_read(request):
    """Mark all notifications as read for the current user"""
    from notifications.models import Notification
    
    count = Notification.objects.filter(recipient=request.user, unread=True).count()
    Notification.objects.filter(recipient=request.user, unread=True).mark_all_as_read()
    
    return {"message": f"{count} notifications marked as read"}


@router.get("/notifications/unread-count", response=dict)
def get_unread_notification_count(request):
    """Get count of unread notifications"""
    from notifications.models import Notification
    
    count = Notification.objects.filter(recipient=request.user, unread=True).count()
    return {"count": count}



@router.delete("/workspaces/{uuid:workspace_id}/fields/{int:field_id}")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def delete_field(request, workspace_id: UUID, field_id: int):
    """
    Delete a custom field and all its related data.
    
    This endpoint will:
    - Delete all field values associated with this field
    - Delete all field options and their AI actions
    - Delete the field itself
    
    Permissions:
    - Requires ADMIN role in the workspace
    
    Returns:
    - Success confirmation
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    field = get_object_or_404(CustomField, workspace=workspace, id=field_id)
    
    with transaction.atomic():
        # The field's options and values will be deleted automatically
        # due to CASCADE delete settings in the models
        field.delete()
    
    return {"message": "Field deleted successfully"}
