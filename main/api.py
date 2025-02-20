from ninja import Router, Schema, File, Form, UploadedFile
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
from ninja.files import UploadedFile
from django.db import transaction
from django.core.files.storage import default_storage
from concurrent.futures import ThreadPoolExecutor
import logging
import boto3
from botocore.exceptions import ClientError
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from apiclient import HeaderAuthentication
from .models import Workspace, WorkspaceInvitation, ShareLink, WorkspaceMember, Asset
from .schemas import (
    WorkspaceInviteSchema, ShareLinkSchema, WorkspaceCreateSchema, 
    WorkspaceDataSchema, WorkspaceUpdateSchema, 
    WorkspaceInviteIn, WorkspaceInviteOut, InviteAcceptSchema,
    AssetSchema, WorkspaceUpdateForm, WorkspaceMemberUpdateSchema,
    WorkspaceMemberSchema,
    ProductSubscriptionSchema,
    PlanOut,
    TransactionSchema
)
from .utils import send_invitation_email, process_file_metadata, process_file_metadata_background, executor, accept_invitation
from .decorators import check_workspace_permission
from django_paddle_billing.models import Product, Subscription, Price, paddle_client
from paddle_billing_client.models.subscription import SubscriptionRequest

router = Router(tags=["main"], auth=django_auth)

logger = logging.getLogger(__name__)



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
    member = WorkspaceMember.objects.get(workspace=workspace, user=request.user)
    workspace.user_role = member.role
    return workspace


@router.post("/workspaces/{workspace_id}/update", response=WorkspaceDataSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def update_workspace(
    request, 
    workspace_id: UUID,
    file: UploadedFile = File(...),  # Required file upload
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
        file_path = default_storage.save(
            f'workspaces/{workspace.id}/avatars/{file.name}', 
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

@router.delete("/workspaces/{workspace_id}")
@decorate_view(check_workspace_permission(WorkspaceMember.Role.ADMIN))
def delete_workspace(request, workspace_id: UUID):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    workspace.delete()
    return {"success": True}


# Get workspace members
@router.get("/workspaces/{workspace_id}/members", response=List[WorkspaceMemberSchema])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_workspace_members(request, workspace_id: UUID):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    members = workspace.workspacemember_set.select_related('user', 'workspace').all()
    print(members)
    return list(members)

# Update workspace member role
@router.put("/workspaces/{workspace_id}/members/{member_id}", response=WorkspaceMemberSchema)
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
@router.delete("/workspaces/{workspace_id}/members/{member_id}")
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

@router.get("/workspaces/{workspace_id}/subscription")
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
    workspace = get_object_or_404(Workspace, id=workspace_id)

    invitation = WorkspaceInvitation.objects.create(
        workspace=workspace,
        email=data.email,
        role=data.role,
        invited_by=request.user,
        expires_at=data.expires_at or datetime.now() + timedelta(days=7)
    )
    
    send_invitation_email(invitation)
    
    return invitation

@router.get("/workspaces/{workspace_id}/invites", response=List[WorkspaceInviteOut])
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_workspace_invites(request, workspace_id: UUID):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    invites = WorkspaceInvitation.objects.filter(
        workspace=workspace,
        status='PENDING'
    ).order_by('-created_at')
    
    # Convert each invite to a WorkspaceInviteOut instance
    return invites

@router.delete("/workspaces/{workspace_id}/invites/{invite_id}")
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


@router.post("/workspaces/{workspace_id}/assets", response=AssetSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.EDITOR))
def create_asset(
    request, 
    workspace_id: UUID,
    file: UploadedFile = File(...),
):
    workspace = get_object_or_404(Workspace, id=workspace_id)
    
    # Create asset with initial status
    with transaction.atomic():
        asset = Asset.objects.create(
            workspace=workspace,
            created_by=request.user,
            file=file,
            status=Asset.Status.PROCESSING,
            size=file.size,
        )
        
        # Save file to storage
        file_path = default_storage.save(
            f'workspaces/{workspace_id}/assets/{asset.id}/{file.name}', 
            file
        )
        
        # Submit background task
        executor.submit(
            process_file_metadata_background,
            asset_id=asset.id,
            file_path=file_path,
            user=request.user
        )
    
    return asset

@router.get("/workspaces/{workspace_id}/assets/{asset_id}", response=AssetSchema)
@decorate_view(check_workspace_permission(WorkspaceMember.Role.COMMENTER))
def get_asset(request, workspace_id: UUID, asset_id: UUID):
    asset = get_object_or_404(
        Asset.objects.filter(workspace_id=workspace_id),
        id=asset_id
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

@router.post("/workspaces/{workspace_id}/subscription/cancel/{subscription_id}")
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

@router.post("/workspaces/{workspace_id}/subscription/{subscription_id}/preview")
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

@router.post("/workspaces/{workspace_id}/subscription/{subscription_id}/update")
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

@router.get("/workspaces/{workspace_id}/subscription/transactions", response=List[TransactionSchema])
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

@router.get("/workspaces/{workspace_id}/subscription/update-payment-method")
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

