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
    
    def start_analysis(self, request: AnalysisRequest, checks_enabled: Dict[str, Any], ai_action_result_ids: List[int], board: Optional['Board'] = None) -> AnalysisResponse:
        """
        Start asset analysis with checks_enabled format (used by AI actions)
        
        Args:
            request: Analysis request configuration
            checks_enabled: Dictionary with enabled checks in Lambda format
            ai_action_result_ids: List of AIActionResult IDs to link back to
            board: Optional board context for the analysis
            
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
        
        # --- Multi-page support: add pages if present ---
        # Try to get the Asset object from s3_key (same logic as _get_asset_from_analysis)
        asset = None
        try:
            from main.models import Asset
            s3_key = request.s3_key
            if '/assets/' in s3_key:
                parts = s3_key.split('/assets/')
                if len(parts) > 1:
                    asset_part = parts[1].split('/')[0]
                    try:
                        asset = Asset.objects.get(id=asset_part)
                    except Asset.DoesNotExist:
                        pass
            if not asset:
                # fallback: search by s3_key pattern in file field
                assets = Asset.objects.filter(file__icontains=s3_key.split('/')[-1])
                if assets.exists():
                    asset = assets.first()
        except Exception as e:
            logger.warning(f"Could not resolve asset for s3_key {request.s3_key}: {e}")
        if asset and getattr(asset, 'pages', None):
            payload['pages'] = asset.pages
        # --- End multi-page support ---
        
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
                board=board,  # Board context for the analysis
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
                board=board,  # Board context for the analysis
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
            
            # Create comments for each individual check if completed successfully
            if payload.status == 'completed' and payload.results:
                self._create_comments_from_results(analysis, payload.results)
            
            logger.info(f"Processed webhook for analysis {payload.check_id}, status: {payload.status}")
            return True
            
        except AssetCheckerAnalysis.DoesNotExist:
            logger.error(f"No analysis found for check_id {payload.check_id}")
            return False
        except Exception as e:
            logger.error(f"Error processing webhook payload: {str(e)}")
            return False

    def _create_comments_from_results(self, analysis: 'AssetCheckerAnalysis', results: Dict[str, Any]) -> None:
        """
        Create individual comments for each issue found in the analysis
        
        Args:
            analysis: The AssetCheckerAnalysis record
            results: The structured results from webhook processing with standardized issues
        """
        try:
            from main.models import Comment, Asset
            from django.contrib.contenttypes.models import ContentType
            
            # Get the asset from the S3 key
            asset = self._get_asset_from_analysis(analysis)
            if not asset:
                logger.error(f"Could not find asset for analysis {analysis.check_id}")
                return
            
            # Get all issues from the standardized format
            all_issues = results.get('issues', [])
            content_type = ContentType.objects.get_for_model(Asset)
            comments_created = []

            # If no issues were found, create a simple success comment
            if not all_issues:
                success_text = "✅ Asset analysis complete — no issues found"

                comment = Comment.objects.create(
                    content_type=content_type,
                    object_id=asset.id,
                    board=analysis.board,
                    author=None,
                    text=success_text,
                    comment_type='AI_ANALYSIS',
                    severity='info',
                    annotation_type='NONE',
                )
                comments_created.append(comment)
                logger.info(f"Created success comment for analysis {analysis.check_id} (no issues found)")
            
            # Create one comment per issue
            for issue in all_issues:
                message = issue.get('message', 'Issue detected')
                severity = issue.get('severity', 'info')
                check_type = issue.get('check_type', 'unknown')
                issue_type = issue.get('issue_type', 'unknown')
                location = issue.get('location')
                
                # Prepare annotation data from location if available
                annotation_type = 'NONE'
                x = y = width = height = None
                
                # Handle placeholder detection special case
                if issue_type == 'placeholder_text_detected' and issue.get('details', {}).get('placeholder_blocks'):
                    placeholder_blocks = issue.get('details', {}).get('placeholder_blocks', [])
                    if placeholder_blocks and len(placeholder_blocks) > 0:
                        # Use the first placeholder block's position for annotation
                        first_block = placeholder_blocks[0]
                        position = first_block.get('position', {})
                        
                        if position and asset.width and asset.height:
                            left = position.get('left')
                            top = position.get('top')
                            loc_width = position.get('width')
                            loc_height = position.get('height')
                            
                            # Only set annotation if we have valid coordinates and image dimensions
                            if all(v is not None for v in [left, top, loc_width, loc_height]):
                                annotation_type = 'AREA'
                                # Convert from pixel coordinates to percentages based on image dimensions
                                x = (float(left) / asset.width) * 100
                                y = (float(top) / asset.height) * 100
                                width = (float(loc_width) / asset.width) * 100
                                height = (float(loc_height) / asset.height) * 100
                                logger.info(f"Setting placeholder annotation for {issue_type}: ({x:.1f}%, {y:.1f}%, {width:.1f}%, {height:.1f}%) - converted from pixels ({left}, {top}, {loc_width}, {loc_height}) on {asset.width}x{asset.height} image")
                            elif all(v is not None for v in [left, top]):
                                # If we only have position, create a point annotation
                                annotation_type = 'POINT'
                                x = (float(left) / asset.width) * 100
                                y = (float(top) / asset.height) * 100
                                logger.info(f"Setting placeholder point annotation for {issue_type}: ({x:.1f}%, {y:.1f}%) - converted from pixels ({left}, {top}) on {asset.width}x{asset.height} image")
                
                # Handle standard location field for other issue types
                elif location and isinstance(location, dict):
                    # Map location fields to comment annotation fields
                    left = location.get('left')
                    top = location.get('top')
                    loc_width = location.get('width')
                    loc_height = location.get('height')
                    
                    # Only set annotation if we have valid coordinates
                    if all(v is not None for v in [left, top, loc_width, loc_height]):
                        annotation_type = 'AREA'
                        # Convert from fractional (0.13) to percentage (13.0)
                        x = float(left) * 100
                        y = float(top) * 100
                        width = float(loc_width) * 100
                        height = float(loc_height) * 100
                        logger.info(f"Setting location annotation for {issue_type}: ({x}%, {y}%, {width}%, {height}%)")
                    elif all(v is not None for v in [left, top]):
                        # If we only have position, create a point annotation
                        annotation_type = 'POINT'
                        # Convert from fractional (0.05) to percentage (5.0)
                        x = float(left) * 100
                        y = float(top) * 100
                        logger.info(f"Setting point annotation for {issue_type}: ({x}%, {y}%)")
                
                # Create comment with board context and location annotation if available
                comment = Comment.objects.create(
                    content_type=content_type,
                    object_id=asset.id,
                    board=analysis.board,  # Board context from analysis
                    author=None,  # System comment
                    text=message,
                    comment_type='AI_ANALYSIS',
                    severity=severity,
                    annotation_type=annotation_type,
                    x=x,
                    y=y,
                    width=width,
                    height=height
                )
                comments_created.append(comment)
                
                location_info = f" with {annotation_type.lower()} annotation" if annotation_type != 'NONE' else ""
                logger.info(f"Created {severity} severity comment for {check_type}: {message[:50]}...{location_info}")
            
            logger.info(f"Created {len(comments_created)} AI analysis comment(s) for analysis {analysis.check_id}")
            
            # Trigger notifications for AI analysis completion
            if comments_created:
                from main.services.notifications import NotificationService
                NotificationService.notify_ai_check_completed(comments_created, asset)
                
            # Update any linked AI action results 
            if analysis.ai_action_result_id:
                self._update_ai_action_results(analysis, results)
            
        except Exception as e:
            logger.error(f"Failed to create comments from results: {str(e)}")
    
    def _update_ai_action_results(self, analysis: 'AssetCheckerAnalysis', results: Dict[str, Any]) -> None:
        """Update AI action results without creating duplicate comments"""
        try:
            from .ai_actions import AIActionResult
            from django.utils import timezone
            
            # Find AI action results linked to this analysis
            ai_results = AIActionResult.objects.filter(
                result__check_id=analysis.check_id,
                status='PROCESSING'
            )
            
            for ai_result in ai_results:
                # Update the AI action result status
                ai_result.result.update({
                    'analysis_results': results,
                    'completed_at': timezone.now().isoformat()
                })
                ai_result.status = 'COMPLETED'
                ai_result.completed_at = timezone.now()
                ai_result.save()
                logger.info(f"Updated AI action result {ai_result.id} without creating duplicate comments")
                
        except Exception as e:
            logger.error(f"Failed to update AI action results: {str(e)}")

    def _get_asset_from_analysis(self, analysis: 'AssetCheckerAnalysis') -> Optional['Asset']:
        """
        Get the Asset object from the AssetCheckerAnalysis
        
        Args:
            analysis: The AssetCheckerAnalysis record
            
        Returns:
            Asset object or None if not found
        """
        try:
            from main.models import Asset
            
            # Try to find asset by S3 key pattern
            # The s3_key typically contains the asset ID in the path
            s3_key = analysis.s3_key
            
            # Extract asset ID from S3 key (e.g., "media/workspaces/{workspace_id}/assets/{asset_id}/...")
            if '/assets/' in s3_key:
                parts = s3_key.split('/assets/')
                if len(parts) > 1:
                    asset_part = parts[1].split('/')[0]  # Get the asset ID part
                    try:
                        asset = Asset.objects.get(id=asset_part)
                        return asset
                    except Asset.DoesNotExist:
                        logger.warning(f"Asset with ID {asset_part} not found")
            
            # Fallback: search by s3_key pattern in file field
            assets = Asset.objects.filter(file__icontains=s3_key.split('/')[-1])
            if assets.exists():
                return assets.first()
            
            logger.warning(f"Could not find asset for S3 key: {s3_key}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting asset from analysis: {str(e)}")
            return None

    def _format_check_type_comment(self, check_type: str, issues: List[Dict[str, Any]], summary: Dict[str, Any], results: Dict[str, Any]) -> Optional[str]:
        """
        Format a check type's results into a comment text using the new standardized issues format
        
        Args:
            check_type: The type of check (e.g., 'text_accessibility', 'text_quality')
            issues: List of standardized issues for this check type
            summary: Summary info for this check type from checks_summary
            results: Full results object for additional context
            
        Returns:
            Formatted comment text or None if check should be skipped
        """
        try:
            status = summary.get('status', 'unknown')
            
            # Skip skipped checks
            if status == 'skipped':
                return None
            
            # Start building the comment
            comment_lines = []
            
            # Header with check type and status
            check_display_name = {
                'grammar': 'Grammar Check',
                'image_quality': 'Image Quality Check', 
                'text_accessibility': 'Text Accessibility Check',
                'text_quality': 'Text Quality Check',
                'legacy_color_checks': 'Legacy Color Checks'
            }.get(check_type, check_type.replace('_', ' ').title())
            
            if status == 'completed':
                comment_lines.append(f"✅ **{check_display_name}** - Analysis Complete")
            elif status == 'failed':
                comment_lines.append(f"❌ **{check_display_name}** - Analysis Failed")
            else:
                comment_lines.append(f"⚠️ **{check_display_name}** - Status: {status}")
            
            # Add score if available
            score = summary.get('score')
            if score is not None:
                comment_lines.append(f"📊 **Score:** {score}/100")
            
            # Add issues summary
            total_issues = len(issues)
            if total_issues > 0:
                comment_lines.append(f"🔴 **Issues Found:** {total_issues}")
                
                # Group issues by severity and type
                severity_groups = {}
                issue_type_groups = {}
                
                for issue in issues:
                    severity = issue.get('severity', 'unknown')
                    issue_type = issue.get('issue_type', 'unknown')
                    
                    if severity not in severity_groups:
                        severity_groups[severity] = []
                    severity_groups[severity].append(issue)
                    
                    if issue_type not in issue_type_groups:
                        issue_type_groups[issue_type] = []
                    issue_type_groups[issue_type].append(issue)
                
                # Show severity breakdown
                severity_order = ['high', 'medium', 'low']
                severity_emojis = {'high': '🔴', 'medium': '🟡', 'low': '🟠'}
                
                for severity in severity_order:
                    if severity in severity_groups:
                        count = len(severity_groups[severity])
                        emoji = severity_emojis.get(severity, '⚪')
                        comment_lines.append(f"  {emoji} **{severity.title()} Priority:** {count} issues")
                
                # Show detailed breakdown by issue type (limit to most common)
                sorted_issue_types = sorted(issue_type_groups.items(), key=lambda x: len(x[1]), reverse=True)
                
                comment_lines.append(f"\n**Issue Breakdown:**")
                for issue_type, type_issues in sorted_issue_types[:5]:  # Top 5 issue types
                    count = len(type_issues)
                    display_type = issue_type.replace('_', ' ').title()
                    comment_lines.append(f"• **{display_type}:** {count} instances")
                    
                    # Show a sample issue message
                    sample_issue = type_issues[0]
                    sample_message = sample_issue.get('message', '')
                    if sample_message and len(sample_message) < 100:
                        comment_lines.append(f"  ↳ _{sample_message}_")
                    elif len(type_issues) == 1:
                        # For single issues, show more detail
                        text_content = sample_issue.get('text_content')
                        if text_content:
                            comment_lines.append(f"  ↳ Text: \"{text_content}\"")
                
                if len(sorted_issue_types) > 5:
                    remaining = len(sorted_issue_types) - 5
                    comment_lines.append(f"• ... and {remaining} more issue types")
                    
            else:
                comment_lines.append("✅ **No issues found**")
            
            # Add check-specific recommendations
            if check_type == 'text_accessibility' and issues:
                self._add_accessibility_recommendations(comment_lines, issues)
            elif check_type == 'text_quality' and issues:
                self._add_text_quality_recommendations(comment_lines, issues)
            
            # Add timestamp
            comment_lines.append(f"\n*Analysis completed at {results.get('processed_at', 'unknown time')}*")
            
            return '\n'.join(comment_lines)
            
        except Exception as e:
            logger.error(f"Error formatting {check_type} comment: {str(e)}")
            return f"Error processing {check_type} check: {str(e)}"

    def _add_accessibility_recommendations(self, comment_lines: List[str], issues: List[Dict[str, Any]]) -> None:
        """Add accessibility-specific recommendations based on issues found"""
        has_contrast_issues = any(issue.get('issue_type') == 'color_contrast' for issue in issues)
        has_blindness_issues = any(issue.get('issue_type') == 'color_blindness' for issue in issues)
        
        if has_contrast_issues or has_blindness_issues:
            comment_lines.append(f"\n💡 **Recommendations:**")
            
            if has_contrast_issues:
                comment_lines.append("• Increase contrast ratio between text and background colors")
                comment_lines.append("• Aim for a contrast ratio of at least 4.5:1 for normal text")
                
            if has_blindness_issues:
                comment_lines.append("• Avoid relying solely on color to convey information")
                comment_lines.append("• Test design with color blindness simulators")
                comment_lines.append("• Consider adding patterns, icons, or text labels")

    def _add_text_quality_recommendations(self, comment_lines: List[str], issues: List[Dict[str, Any]]) -> None:
        """Add text quality-specific recommendations based on issues found"""
        issue_types = {issue.get('issue_type') for issue in issues}
        
        recommendations = []
        
        if 'placeholder_text_detected' in issue_types:
            recommendations.append("• Replace placeholder text with final content")
            recommendations.append("• Review all text blocks for lorem ipsum or generic text")
            
        if 'repeated_text_detected' in issue_types:
            recommendations.append("• Review repeated text for intentional vs. accidental duplication")
            recommendations.append("• Consider if repeated content serves a purpose")
            
        if 'text_close_to_edge' in issue_types:
            recommendations.append("• Increase margins around text elements")
            recommendations.append("• Ensure text has adequate breathing room from image edges")
        
        if recommendations:
            comment_lines.append(f"\n💡 **Recommendations:**")
            comment_lines.extend(recommendations)
    
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
    
