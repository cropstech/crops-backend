"""
Asset Checker Service Layer

Provides integration with Asset Checker Lambda service supporting both
webhook callbacks and manual polling for asset analysis.
"""

import json
import uuid
import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from django.conf import settings
from django.utils import timezone
import requests
from requests.exceptions import RequestException
from main.models import AssetCheckerAnalysis

logger = logging.getLogger(__name__)


@dataclass
class AnalysisRequest:
    """Request for asset analysis"""
    s3_bucket: str
    s3_key: str


@dataclass
class AnalysisResponse:
    """Response from analysis initiation"""
    check_id: str
    status: str
    webhook_url: Optional[str] = None
    polling_url: Optional[str] = None
    estimated_completion: Optional[str] = None


@dataclass
class WebhookPayload:
    """Webhook payload structure"""
    check_id: str
    status: str
    results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AssetCheckerService:
    """Service for interacting with Asset Checker Lambda API"""
    
    def __init__(self):
        self.api_url = getattr(settings, 'ASSET_CHECKER_API_URL', None)
        self.api_key = getattr(settings, 'LAMBDA_AUTH_TOKEN', None)
        self.webhook_base_url = getattr(settings, 'WEBHOOK_BASE_URL', None)
        
        if not self.api_url:
            raise ValueError("ASSET_CHECKER_API_URL setting is required")
        if not self.api_key:
            raise ValueError("LAMBDA_AUTH_TOKEN setting is required")
        if not self.webhook_base_url:
            raise ValueError("WEBHOOK_BASE_URL setting is required")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get standard headers for API requests"""
        return {
            'X-API-Key': self.api_key,
            'Content-Type': 'application/json',
            'User-Agent': 'CropsBackend/1.0'
        }
    
    def _generate_webhook_url(self, check_id: str) -> str:
        """Generate webhook URL for this analysis"""
        base_url = self.webhook_base_url.rstrip('/')
        return f"{base_url}/asset-checker-results/{check_id}"
    
    def get_analysis_results(self, check_id: str) -> Dict[str, Any]:
        """
        Get complete analysis results
        
        Args:
            check_id: Unique identifier for the analysis
            
        Returns:
            Complete analysis results or raises exception if not found
        """
        try:
            logger.info(f"Getting analysis results for check_id: {check_id}")
            # First check local cache/database
            try:
                analysis = AssetCheckerAnalysis.objects.get(check_id=check_id)
                if analysis.results and analysis.status == 'completed':
                    return {
                        'check_id': check_id,
                        'status': analysis.status,
                        'results': analysis.results,
                        'webhook_received': analysis.webhook_received,
                        'completed_at': analysis.completed_at.isoformat() if analysis.completed_at else None,
                        'source': 'local'
                    }
            except AssetCheckerAnalysis.DoesNotExist:
                pass
            
            # Get results from Lambda API
            response = requests.get(
                f"{self.api_url}/results/{check_id}",
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            
            result = response.json()
            result['source'] = 'lambda'
            
            # Cache results locally
            try:
                analysis = AssetCheckerAnalysis.objects.get(check_id=check_id)
                analysis.results = result.get('results')
                analysis.status = result.get('status', analysis.status)
                if result.get('status') == 'completed' and not analysis.completed_at:
                    analysis.completed_at = timezone.now()
                analysis.save()
            except AssetCheckerAnalysis.DoesNotExist:
                logger.warning(f"No local record found for check_id {check_id}")
            
            return result
            
        except RequestException as e:
            logger.error(f"Failed to get analysis results for {check_id}: {str(e)}")
            raise
    
    def start_analysis(self, request: AnalysisRequest, checks_enabled: Dict[str, Any], ai_action_result_ids: List[int]) -> AnalysisResponse:
        """
        Start asset analysis with checks_enabled format (used by AI actions)
        
        Args:
            request: Analysis request configuration
            checks_enabled: Dictionary with enabled checks in Lambda format
            ai_action_result_ids: List of AIActionResult IDs to link back to
            
        Returns:
            AnalysisResponse with check_id and URLs
        """
        check_id = str(uuid.uuid4())
        
        # Prepare webhook URL
        webhook_url = self._generate_webhook_url(check_id)
        
        # Prepare API payload with simplified format
        payload = {
            's3_bucket': request.s3_bucket,
            's3_key': request.s3_key,
            'checks_enabled': checks_enabled,
            'webhook_url': webhook_url
        }
        
        try:
            # Log the payload for debugging
            logger.info(f"Sending payload to Lambda API: {json.dumps(payload, indent=2)}")
            
            # Make API request
            response = requests.post(
                f"{self.api_url}/analyze",
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )
            
            # Log response details for debugging
            logger.info(f"Lambda API response status: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"Lambda API error response: {response.text}")
            
            response.raise_for_status()
            
            result = response.json()
            
            # Extract check_id from response (Lambda should return it)
            returned_check_id = result.get('check_id', check_id)
            
            # Store analysis record in database
            AssetCheckerAnalysis.objects.create(
                check_id=returned_check_id,
                status='processing',
                s3_bucket=request.s3_bucket,
                s3_key=request.s3_key,
                use_webhook=True,
                webhook_url=webhook_url,
                ai_action_result_id=ai_action_result_ids[0] if ai_action_result_ids else None
            )
            
            logger.info(f"Started asset analysis {returned_check_id} for {request.s3_bucket}/{request.s3_key} with checks_enabled")
            
            return AnalysisResponse(
                check_id=returned_check_id,
                status=result.get('status', 'processing'),
                webhook_url=webhook_url,
                polling_url=f"{self.api_url}/results/{returned_check_id}",
                estimated_completion=result.get('estimated_completion')
            )
            
        except RequestException as e:
            logger.error(f"Failed to start analysis: {str(e)}")
            # Create failed record
            AssetCheckerAnalysis.objects.create(
                check_id=check_id,
                status='failed',
                s3_bucket=request.s3_bucket,
                s3_key=request.s3_key,
                error_message=str(e),
                use_webhook=True,
                ai_action_result_id=ai_action_result_ids[0] if ai_action_result_ids else None
            )
            raise
    
    def process_webhook_payload(self, payload: WebhookPayload) -> bool:
        """
        Process incoming webhook payload and update local database
        
        Args:
            payload: Webhook payload from Lambda service
            
        Returns:
            True if processed successfully, False otherwise
        """
        try:
            analysis = AssetCheckerAnalysis.objects.get(check_id=payload.check_id)
            
            # Update analysis record
            analysis.status = payload.status
            analysis.webhook_received = True
            analysis.results = payload.results
            analysis.error_message = payload.error
            
            if payload.status in ['completed', 'failed'] and not analysis.completed_at:
                analysis.completed_at = timezone.now()
            
            analysis.save()
            
            # If this analysis is linked to an AI action, process the results
            if analysis.ai_action_result_id and payload.status == 'completed' and payload.results:
                try:
                    from .ai_actions import process_asset_checker_webhook_result
                    process_asset_checker_webhook_result(payload.check_id, payload.results)
                except Exception as e:
                    logger.error(f"Failed to process AI action webhook result: {str(e)}")
            
            logger.info(f"Processed webhook for analysis {payload.check_id}, status: {payload.status}")
            return True
            
        except AssetCheckerAnalysis.DoesNotExist:
            logger.error(f"No analysis found for check_id {payload.check_id}")
            return False
        except Exception as e:
            logger.error(f"Error processing webhook payload: {str(e)}")
            return False
    
    def start_polling_fallback(self, check_id: str) -> None:
        """
        Start background polling for analysis that didn't receive webhook
        
        Args:
            check_id: Analysis to poll for
        """
        from .tasks import poll_analysis_status
        
        try:
            analysis = AssetCheckerAnalysis.objects.get(check_id=check_id)
            if not analysis.webhook_received and not analysis.is_complete:
                # Schedule background task
                poll_analysis_status.delay(check_id)
                logger.info(f"Started polling fallback for analysis {check_id}")
        except AssetCheckerAnalysis.DoesNotExist:
            logger.error(f"No analysis found for polling fallback: {check_id}")
    
