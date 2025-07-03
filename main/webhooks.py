from ninja import Router, Schema
from typing import Optional, List, Dict, Any
from uuid import UUID
from django.shortcuts import get_object_or_404
from django.conf import settings
from ninja.errors import HttpError
import json
import logging
from ninja.security import APIKeyHeader
from .models import Asset, AssetAnalysis, AssetCheckerAnalysis
from .services.asset_checker_service import AssetCheckerService, WebhookPayload
from .services.webhook_models import WebhookValidator, WebhookPayloadSchema
from datetime import datetime
from django.utils import timezone
logger = logging.getLogger(__name__)

# Create API Key authentication
class ApiKey(APIKeyHeader):
    param_name = "X-API-Key"

    def authenticate(self, request, key):
        if key == settings.LAMBDA_AUTH_TOKEN:
            return key
        else:
            raise HttpError(401, "Invalid API key")

    def openapi(self):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Lambda authentication token"
        }

header_key = ApiKey()


# Create a router specifically for webhooks
router = Router(tags=["Webhooks"], auth=header_key)

# Define webhook payload schemas
class AssetMetadataSchema(Schema):
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    mime_type: Optional[str] = None
    thumbnails: List[str] = []
    error: Optional[str] = None

class AssetWebhookSchema(Schema):
    asset_id: UUID
    status: str  # 'success' or 'failed'
    metadata: AssetMetadataSchema

# Asset Checker webhook schemas
class AssetCheckerResultsSchema(Schema):
    """Schema for asset checker analysis results"""
    check_id: str
    status: str  # 'pending', 'processing', 'completed', 'failed'
    results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    progress: Optional[int] = None
    estimated_completion: Optional[str] = None

class AssetCheckerStatusResponseSchema(Schema):
    """Response schema for status checks"""
    check_id: str
    status: str
    progress: Optional[int] = None
    webhook_received: bool
    completed_at: Optional[str] = None
    source: str  # 'local' or 'lambda'

class AssetCheckerResultsResponseSchema(Schema):
    """Response schema for results retrieval"""
    check_id: str
    status: str
    results: Optional[Dict[str, Any]] = None
    webhook_received: bool
    completed_at: Optional[str] = None
    source: str  # 'local' or 'lambda'

@router.post(
    "/asset-processed", 
    summary="Asset Processing Webhook",
    description="""
    Webhook endpoint that receives processing results from Lambda function.
    Requires authentication via X-API-Key header.
    Updates asset records with processing results.
    """
)
def asset_processed_webhook(request):
    """
    Process asset metadata webhooks from Lambda function
    """
    try:
        # Parse the JSON body
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook request body")
            raise HttpError(400, "Invalid JSON in request body")

        logger.info(f"Received webhook for asset processing")
        # logger.info(f"Body: {body}")
        
        # Validate required fields
        asset_id = body.get('asset_id')
        if not asset_id:
            raise HttpError(400, "Missing asset_id in webhook payload")
            
        # Get status (completed or failed)
        status = body.get('status')
        if not status:
            raise HttpError(400, "Missing status in webhook payload")
        
        # Get the asset
        asset = get_object_or_404(Asset, id=asset_id)
        
        # Process based on status
        if status == 'completed':
            # Extract the entire metadata object directly from the body
            metadata_from_webhook = body.get('metadata', {})
            processed_files = body.get('processed', {})
            analysis_data = body.get('analysis', {})
            
            # Set status to COMPLETED
            asset.status = Asset.Status.COMPLETED
            
            # Assign metadata directly as it is in the webhook payload
            if metadata_from_webhook:
                asset.metadata = metadata_from_webhook
            
            # Extract dimensions for specific fields if needed
            if 'image' in metadata_from_webhook and 'dimensions' in metadata_from_webhook['image']:
                dimensions = metadata_from_webhook['image']['dimensions']
                if dimensions.get('width') is not None:
                    asset.width = dimensions['width']
                if dimensions.get('height') is not None:
                    asset.height = dimensions['height']
                    
            # Extract dimensions and other video-specific fields from streams
            if 'streams' in metadata_from_webhook:
                for stream in metadata_from_webhook['streams']:
                    if stream.get('type') == 'video':
                        dimensions = stream.get('dimensions', {})
                        if dimensions.get('width') is not None:
                            asset.width = dimensions['width']
                        if dimensions.get('height') is not None:
                            asset.height = dimensions['height']
                        if stream.get('codec', {}).get('name') is not None:
                            asset.mime_type = f"video/{stream['codec']['name']}"
            
            # Update format data if available
            if 'format' in metadata_from_webhook:
                format_data = metadata_from_webhook['format']
                if format_data.get('size') is not None:
                    asset.size = format_data['size']
                if format_data.get('duration') is not None:
                    asset.duration = format_data['duration']
                # Check for both None and empty string for creation_time
                if format_data.get('creation_time') and format_data.get('creation_time').strip():
                    asset.date_created = format_data['creation_time']
                else:
                    asset.date_created = timezone.now()

            
            # Update mime type from codec if available
            if 'image' in metadata_from_webhook and 'codec' in metadata_from_webhook['image']:
                codec = metadata_from_webhook['image']['codec']
                if codec.get('name') is not None:
                    asset.mime_type = f"image/{codec['name']}"
            
            # Extract thumbnails/processed versions
            thumbnails = []
            for version, file_info in processed_files.items():
                if version in ['thumbnail', 'medium', 'large']:
                    bucket = file_info.get('bucket')
                    key = file_info.get('key')
                    if bucket is not None and key is not None:
                        thumbnails.append(f"https://{bucket}.s3.amazonaws.com/{key}")
            
            if thumbnails:
                asset.thumbnails = thumbnails
            
            # Store analysis data if available
            if analysis_data:
                # Create or update the AssetAnalysis record
                analysis, created = AssetAnalysis.objects.update_or_create(
                    asset=asset,
                    defaults={
                        'raw_analysis': analysis_data,
                        'labels': analysis_data.get('labels', []) if analysis_data.get('labels') is not None else [],
                        'moderation_labels': analysis_data.get('moderation_labels', []) if analysis_data.get('moderation_labels') is not None else [],
                    }
                )
            
        else:
            # Handle processing failure
            asset.status = Asset.Status.FAILED
            asset.processing_error = "Processing failed"
            
        asset.save()
        
        return {"success": True, "message": f"Asset {asset_id} updated successfully"}
        
    except HttpError as e:
        # Let HTTP errors pass through
        raise
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HttpError(500, f"Webhook processing failed: {str(e)}")


# Asset Checker webhook endpoints
@router.post(
    "/assets/webhook/{check_id}",
    summary="Asset Checker Webhook",
    description="""
    Webhook endpoint that receives analysis results from Asset Checker Lambda service.
    Called when asset analysis is complete or fails.
    """
)
def asset_checker_webhook(request, check_id: str):
    """
    Process asset checker analysis results from Lambda service
    """
    try:
        # Parse the JSON body
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in asset checker webhook for {check_id}")
            raise HttpError(400, "Invalid JSON in request body")

        logger.info(f"Received asset checker webhook for check_id: {check_id}")
        
        # Validate webhook payload
        validation_result = WebhookValidator.validate_payload(body)
        if not validation_result.is_valid:
            logger.error(f"Invalid webhook payload for {check_id}: {validation_result.error_message}")
            raise HttpError(400, f"Invalid payload: {validation_result.error_message}")
        
        # Ensure check_id matches URL parameter
        if validation_result.payload.check_id != check_id:
            logger.error(f"Check ID mismatch: URL={check_id}, payload={validation_result.payload.check_id}")
            raise HttpError(400, "Check ID mismatch between URL and payload")
        
        # Process the webhook using the service
        service = AssetCheckerService()
        webhook_payload = WebhookPayload(
            check_id=validation_result.payload.check_id,
            status=validation_result.payload.status,
            results=validation_result.payload.results,
            error=validation_result.payload.error,
            metadata=validation_result.payload.metadata
        )
        
        success = service.process_webhook_payload(webhook_payload)
        
        if success:
            return {
                "success": True, 
                "message": f"Asset checker webhook processed for {check_id}",
                "status": validation_result.payload.status
            }
        else:
            logger.error(f"Failed to process webhook for {check_id}")
            raise HttpError(500, "Failed to process webhook")
        
    except HttpError as e:
        # Let HTTP errors pass through
        raise
    except Exception as e:
        logger.error(f"Error processing asset checker webhook for {check_id}: {str(e)}")
        raise HttpError(500, f"Webhook processing failed: {str(e)}")


@router.get(
    "/assets/status/{check_id}",
    response=AssetCheckerStatusResponseSchema,
    summary="Asset Checker Status",
    description="""
    Get the current status of an asset analysis.
    Used for polling when webhooks are not available.
    """
)
def get_asset_checker_status(request, check_id: str):
    """
    Get status of asset checker analysis
    """
    try:
        service = AssetCheckerService()
        status_data = service.get_analysis_status(check_id)
        
        return AssetCheckerStatusResponseSchema(
            check_id=check_id,
            status=status_data.get('status', 'unknown'),
            progress=status_data.get('progress'),
            webhook_received=status_data.get('webhook_received', False),
            completed_at=status_data.get('completed_at'),
            source=status_data.get('source', 'lambda')
        )
        
    except Exception as e:
        logger.error(f"Error getting status for {check_id}: {str(e)}")
        raise HttpError(500, f"Failed to get analysis status: {str(e)}")


@router.get(
    "/assets/results/{check_id}",
    response=AssetCheckerResultsResponseSchema,
    summary="Asset Checker Results",
    description="""
    Get the complete analysis results for a completed asset check.
    Returns detailed analysis data including all check results.
    """
)
def get_asset_checker_results(request, check_id: str):
    """
    Get complete asset checker analysis results
    """
    try:
        service = AssetCheckerService()
        results_data = service.get_analysis_results(check_id)
        
        return AssetCheckerResultsResponseSchema(
            check_id=check_id,
            status=results_data.get('status', 'unknown'),
            results=results_data.get('results'),
            webhook_received=results_data.get('webhook_received', False),
            completed_at=results_data.get('completed_at'),
            source=results_data.get('source', 'lambda')
        )
        
    except Exception as e:
        logger.error(f"Error getting results for {check_id}: {str(e)}")
        raise HttpError(500, f"Failed to get analysis results: {str(e)}")


# Generic webhook endpoint for Asset Checker (alternative URL pattern)
@router.post(
    "/asset-checker",
    summary="Asset Checker Generic Webhook",
    description="""
    Generic webhook endpoint for Asset Checker Lambda service.
    Can handle multiple check IDs in a single webhook call.
    """
)
def asset_checker_generic_webhook(request):
    """
    Generic asset checker webhook handler
    """
    try:
        # Parse the JSON body
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            logger.error("Invalid JSON in generic asset checker webhook")
            raise HttpError(400, "Invalid JSON in request body")

        logger.info(f"Received generic asset checker webhook")
        
        # Handle batch webhooks (multiple check results)
        if isinstance(body, list):
            results = []
            for item in body:
                validation_result = WebhookValidator.validate_payload(item)
                if validation_result.is_valid:
                    service = AssetCheckerService()
                    webhook_payload = WebhookPayload(
                        check_id=validation_result.payload.check_id,
                        status=validation_result.payload.status,
                        results=validation_result.payload.results,
                        error=validation_result.payload.error,
                        metadata=validation_result.payload.metadata
                    )
                    success = service.process_webhook_payload(webhook_payload)
                    results.append({
                        "check_id": validation_result.payload.check_id,
                        "success": success
                    })
                else:
                    results.append({
                        "check_id": item.get('check_id', 'unknown'),
                        "success": False,
                        "error": validation_result.error_message
                    })
            
            return {
                "success": True,
                "message": f"Processed {len(results)} webhook items",
                "results": results
            }
        
        # Handle single webhook
        else:
            validation_result = WebhookValidator.validate_payload(body)
            if not validation_result.is_valid:
                logger.error(f"Invalid webhook payload: {validation_result.error_message}")
                raise HttpError(400, f"Invalid payload: {validation_result.error_message}")
            
            service = AssetCheckerService()
            webhook_payload = WebhookPayload(
                check_id=validation_result.payload.check_id,
                status=validation_result.payload.status,
                results=validation_result.payload.results,
                error=validation_result.payload.error,
                metadata=validation_result.payload.metadata
            )
            
            success = service.process_webhook_payload(webhook_payload)
            
            return {
                "success": success,
                "message": f"Processed webhook for {validation_result.payload.check_id}",
                "check_id": validation_result.payload.check_id
            }
        
    except HttpError as e:
        # Let HTTP errors pass through
        raise
    except Exception as e:
        logger.error(f"Error processing generic asset checker webhook: {str(e)}")
        raise HttpError(500, f"Webhook processing failed: {str(e)}") 