"""
Asset Checker Service Layer

Provides integration with Asset Checker Lambda service supporting both
webhook callbacks and manual polling for asset analysis.
"""

import json
import uuid
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from django.conf import settings
from django.utils import timezone
import requests
from requests.exceptions import RequestException
from main.models import AssetCheckerAnalysis

logger = logging.getLogger(__name__)


@dataclass
class CheckConfiguration:
    """Configuration for asset checks"""
    spelling_grammar: Optional[Dict[str, Any]] = None
    color_contrast: Optional[Dict[str, Any]] = None
    image_quality: Optional[Dict[str, Any]] = None
    image_artifacts: Optional[Dict[str, Any]] = None
    custom_checks: Optional[List[Dict[str, Any]]] = None


@dataclass
class WebhookConfig:
    """Webhook configuration"""
    url: str
    secret: Optional[str] = None
    headers: Optional[Dict[str, str]] = None


@dataclass
class AnalysisRequest:
    """Request for asset analysis"""
    s3_bucket: str
    s3_key: str
    checks_config: CheckConfiguration
    use_webhook: bool = True
    webhook_config: Optional[WebhookConfig] = None
    callback_url: Optional[str] = None
    timeout: Optional[int] = None


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
        self.api_key = getattr(settings, 'ASSET_CHECKER_API_KEY', None)
        self.webhook_base_url = getattr(settings, 'WEBHOOK_BASE_URL', None)
        
        if not self.api_url:
            raise ValueError("ASSET_CHECKER_API_URL setting is required")
        if not self.api_key:
            raise ValueError("ASSET_CHECKER_API_KEY setting is required")
        if not self.webhook_base_url:
            raise ValueError("WEBHOOK_BASE_URL setting is required")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get standard headers for API requests"""
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'CropsBackend/1.0'
        }
    
    def _generate_webhook_url(self, check_id: str) -> str:
        """Generate webhook URL for this analysis"""
        return f"{self.webhook_base_url}/api/assets/webhook/{check_id}"
    
    def start_analysis(self, request: AnalysisRequest) -> AnalysisResponse:
        """
        Start asset analysis with the Lambda service
        
        Args:
            request: Analysis request configuration
            
        Returns:
            AnalysisResponse with check_id and URLs
            
        Raises:
            RequestException: If API request fails
            ValueError: If request validation fails
        """
        check_id = str(uuid.uuid4())
        
        # Prepare webhook URL if using webhooks
        webhook_url = None
        if request.use_webhook:
            if request.webhook_config and request.webhook_config.url:
                webhook_url = request.webhook_config.url
            else:
                webhook_url = self._generate_webhook_url(check_id)
        
        # Prepare API payload
        payload = {
            'check_id': check_id,
            's3_bucket': request.s3_bucket,
            's3_key': request.s3_key,
            'checks_config': self._serialize_checks_config(request.checks_config),
            'use_webhook': request.use_webhook,
        }
        
        if webhook_url:
            payload['webhook_config'] = {
                'url': webhook_url,
                'secret': request.webhook_config.secret if request.webhook_config else None,
                'headers': request.webhook_config.headers if request.webhook_config else None
            }
        
        if request.callback_url:
            payload['callback_url'] = request.callback_url
        
        if request.timeout:
            payload['timeout'] = request.timeout
        
        try:
            # Make API request
            response = requests.post(
                f"{self.api_url}/analyze",
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Store analysis record in database
            analysis = AssetCheckerAnalysis.objects.create(
                check_id=check_id,
                status='processing',
                s3_bucket=request.s3_bucket,
                s3_key=request.s3_key,
                use_webhook=request.use_webhook,
                webhook_url=webhook_url,
                callback_url=request.callback_url
            )
            
            logger.info(f"Started asset analysis {check_id} for {request.s3_bucket}/{request.s3_key}")
            
            return AnalysisResponse(
                check_id=check_id,
                status=result.get('status', 'processing'),
                webhook_url=webhook_url,
                polling_url=f"{self.webhook_base_url}/api/assets/status/{check_id}",
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
                use_webhook=request.use_webhook
            )
            raise
    
    def get_analysis_status(self, check_id: str) -> Dict[str, Any]:
        """
        Get current status of an analysis
        
        Args:
            check_id: Unique identifier for the analysis
            
        Returns:
            Status information including progress and current state
        """
        try:
            # First check local database
            try:
                analysis = AssetCheckerAnalysis.objects.get(check_id=check_id)
                if analysis.is_complete:
                    return {
                        'check_id': check_id,
                        'status': analysis.status,
                        'progress': 100 if analysis.status == 'completed' else 0,
                        'webhook_received': analysis.webhook_received,
                        'source': 'local'
                    }
            except AssetCheckerAnalysis.DoesNotExist:
                pass
            
            # Fallback to Lambda API
            response = requests.get(
                f"{self.api_url}/status/{check_id}",
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            
            result = response.json()
            result['source'] = 'lambda'
            
            # Update local record if it exists
            try:
                analysis = AssetCheckerAnalysis.objects.get(check_id=check_id)
                analysis.status = result.get('status', analysis.status)
                if result.get('status') in ['completed', 'failed'] and not analysis.completed_at:
                    analysis.completed_at = timezone.now()
                analysis.save()
            except AssetCheckerAnalysis.DoesNotExist:
                logger.warning(f"No local record found for check_id {check_id}")
            
            return result
            
        except RequestException as e:
            logger.error(f"Failed to get analysis status for {check_id}: {str(e)}")
            raise
    
    def get_analysis_results(self, check_id: str) -> Dict[str, Any]:
        """
        Get complete analysis results
        
        Args:
            check_id: Unique identifier for the analysis
            
        Returns:
            Complete analysis results or raises exception if not found
        """
        try:
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
            
            # Fallback to Lambda API
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
    
    def analyze_synchronous(self, request: AnalysisRequest) -> Dict[str, Any]:
        """
        Perform synchronous analysis with polling
        
        Args:
            request: Analysis request (webhook settings ignored)
            
        Returns:
            Complete analysis results or timeout error
        """
        # Force polling mode
        request.use_webhook = False
        
        # Start analysis
        response = self.start_analysis(request)
        check_id = response.check_id
        
        # Poll until completion or timeout
        timeout = request.timeout or 300  # 5 minute default
        poll_interval = 5  # 5 seconds
        max_attempts = timeout // poll_interval
        
        for attempt in range(max_attempts):
            try:
                status = self.get_analysis_status(check_id)
                
                if status['status'] == 'completed':
                    return self.get_analysis_results(check_id)
                elif status['status'] == 'failed':
                    raise Exception(f"Analysis failed: {status.get('error', 'Unknown error')}")
                
                # Wait before next poll
                import time
                time.sleep(poll_interval)
                
            except Exception as e:
                if attempt == max_attempts - 1:  # Last attempt
                    raise
                logger.warning(f"Polling attempt {attempt + 1} failed: {str(e)}")
        
        # Timeout reached
        raise Exception(f"Analysis timed out after {timeout} seconds")
    
    def _serialize_checks_config(self, config: CheckConfiguration) -> Dict[str, Any]:
        """Convert CheckConfiguration to dict for API"""
        result = {}
        
        if config.spelling_grammar:
            result['spelling_grammar'] = config.spelling_grammar
        if config.color_contrast:
            result['color_contrast'] = config.color_contrast
        if config.image_quality:
            result['image_quality'] = config.image_quality
        if config.image_artifacts:
            result['image_artifacts'] = config.image_artifacts
        if config.custom_checks:
            result['custom_checks'] = config.custom_checks
        
        return result