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
from .services.webhook_models import WebhookPayloadSchema
from datetime import datetime
from django.utils import timezone
logger = logging.getLogger(__name__)

# Create API Key authentication
class ApiKey(APIKeyHeader):
    param_name = "X-API-Key"

    def authenticate(self, request, key):
        logger.info(f"Authenticating with key: {key}")
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

# Asset Checker webhook schemas are handled dynamically now


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
        logger.info(f"Body: {body}")
        
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
            if 'image' in metadata_from_webhook and isinstance(metadata_from_webhook['image'], dict) and 'dimensions' in metadata_from_webhook['image']:
                dimensions = metadata_from_webhook['image']['dimensions']
                if isinstance(dimensions, dict):
                    if dimensions.get('width') is not None:
                        asset.width = dimensions['width']
                    if dimensions.get('height') is not None:
                        asset.height = dimensions['height']
                    
            # Extract dimensions and other video-specific fields from streams
            if 'streams' in metadata_from_webhook and isinstance(metadata_from_webhook['streams'], list):
                for stream in metadata_from_webhook['streams']:
                    if isinstance(stream, dict) and stream.get('type') == 'video':
                        dimensions = stream.get('dimensions', {})
                        if isinstance(dimensions, dict):
                            if dimensions.get('width') is not None:
                                asset.width = dimensions['width']
                            if dimensions.get('height') is not None:
                                asset.height = dimensions['height']
                        if isinstance(stream.get('codec'), dict) and stream.get('codec', {}).get('name') is not None:
                            asset.mime_type = f"video/{stream['codec']['name']}"
            
            # Update format data if available
            if 'format' in metadata_from_webhook and isinstance(metadata_from_webhook['format'], dict):
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
            if 'image' in metadata_from_webhook and isinstance(metadata_from_webhook['image'], dict) and 'codec' in metadata_from_webhook['image']:
                codec = metadata_from_webhook['image']['codec']
                if isinstance(codec, dict) and codec.get('name') is not None:
                    asset.mime_type = f"image/{codec['name']}"
            
            # Extract thumbnails/processed versions
            thumbnails = []
            for version, file_info in processed_files.items():
                # Skip non-dictionary values (like arrays)
                if not isinstance(file_info, dict):
                    continue
                    
                if version in ['thumbnail', 'medium', 'large']:
                    bucket = file_info.get('bucket')
                    key = file_info.get('key')
                    if bucket is not None and key is not None:
                        thumbnails.append(f"https://{bucket}.s3.amazonaws.com/{key}")
            
            if thumbnails:
                asset.thumbnails = thumbnails
            
            # Store analysis data if available
            if analysis_data and isinstance(analysis_data, dict):
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
    "/asset-checker-results/{check_id}",
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
        logger.info(f"Full webhook payload: {json.dumps(body, indent=2)}")
        
        # Extract and validate required fields from the actual payload structure
        # Handle both direct payload and wrapped payload formats
        payload_check_id = body.get('check_id')
        payload_status = body.get('status')
        payload_event = body.get('event')
        
        # Check if the payload is wrapped in a 'data' field
        if not payload_check_id and 'data' in body:
            data_section = body['data']
            payload_check_id = data_section.get('check_id')
            payload_status = data_section.get('status')
            # Use the data section for further processing
            body = data_section
        
        if not payload_check_id:
            logger.error(f"Missing check_id in webhook payload for {check_id}")
            raise HttpError(400, "Missing check_id in webhook payload")
        
        if not payload_status:
            logger.error(f"Missing status in webhook payload for {check_id}")
            raise HttpError(400, "Missing status in webhook payload")
        
        # Use the check_id from URL (our generated one) regardless of Lambda's internal ID
        if payload_check_id != check_id:
            logger.info(f"Lambda using different internal check_id: URL={check_id}, payload={payload_check_id} - using URL check_id")
        
        # Transform the complex webhook payload into structured results
        results = _extract_results_from_webhook_payload(body)
        
        # Process the webhook using the service (use our check_id from URL)
        service = AssetCheckerService()
        webhook_payload = WebhookPayload(
            check_id=check_id,
            status=payload_status,
            results=results,
            error=body.get('error'),
            metadata={
                'event': payload_event,
                'webhook_timestamp': body.get('webhook_timestamp'),
                'execution_info': body.get('execution_info'),
                'asset_info': body.get('asset_info')
            }
        )
        
        success = service.process_webhook_payload(webhook_payload)
        
        if success:
            return {
                "success": True, 
                "message": f"Asset checker webhook processed for {check_id}",
                "status": payload_status,
                "results_extracted": results is not None
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


def _extract_results_from_webhook_payload(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract and structure results from the complex webhook payload.
    Transforms the Lambda webhook format into a structured results object.
    Supports both direct payload and wrapped payload (with 'data' field) formats.
    
    Updated to handle the new standardized 'issues' array format.
    """
    try:
        # Handle both direct payload and wrapped payload formats
        data_section = body.get('data', body)  # Use 'data' if present, otherwise use body directly
        
        # Extract main components from the webhook payload
        summary = data_section.get('summary', {})
        issues = data_section.get('issues', [])  # New standardized issues array
        execution_info = data_section.get('execution_info', {})
        asset_info = data_section.get('asset_info', {})
        checks_summary = data_section.get('checks_summary', [])
        
        # Structure the results in a consistent format
        results = {
            'summary': summary,
            'issues': issues,  # All issues in standardized format
            'checks_summary': checks_summary,
            'execution_info': execution_info,
            'asset_info': asset_info,
            'raw_payload': data_section,  # Keep the data section for debugging
            'original_payload': body,  # Keep the original payload structure
            'processed_at': datetime.now().isoformat()
        }
        
        # Extract key metrics for easy access
        results['metrics'] = {
            'total_issues': summary.get('total_issues', 0),
            'average_score': summary.get('average_score', 0),
            'checks_completed': summary.get('checks_completed', 0),
            'checks_failed': summary.get('checks_failed', 0),
            'checks_skipped': summary.get('checks_skipped', 0),
            'execution_time_ms': execution_info.get('execution_time_ms', 0)
        }
        
        # Group issues by check_type for easy access
        results['issues_by_check_type'] = {}
        for issue in issues:
            check_type = issue.get('check_type', 'unknown')
            if check_type not in results['issues_by_check_type']:
                results['issues_by_check_type'][check_type] = []
            results['issues_by_check_type'][check_type].append(issue)
        
        # Group issues by severity for summary
        results['issues_by_severity'] = {}
        for issue in issues:
            severity = issue.get('severity', 'unknown')
            if severity not in results['issues_by_severity']:
                results['issues_by_severity'][severity] = []
            results['issues_by_severity'][severity].append(issue)
        
        # Create check type summary from checks_summary
        results['check_type_summary'] = {}
        for check_summary in checks_summary:
            check_type = check_summary.get('check_type', 'unknown')
            results['check_type_summary'][check_type] = {
                'score': check_summary.get('score'),
                'issues_found': check_summary.get('issues_found', 0),
                'status': check_summary.get('status', 'unknown')
            }
        
        logger.info(f"Extracted {len(issues)} issues across {len(results['issues_by_check_type'])} check types from webhook payload")
        
        return results
        
    except Exception as e:
        logger.error(f"Error extracting results from webhook payload: {str(e)}")
        # Return a minimal results structure with the error
        return {
            'error': f"Failed to extract results: {str(e)}",
            'raw_payload': body,
            'processed_at': datetime.now().isoformat()
        }




 