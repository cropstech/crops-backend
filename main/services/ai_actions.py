from typing import Optional, List, Dict, Any
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from main.models import (
    CustomFieldValue,
    CustomFieldOptionAIAction,
    AIActionResult,
    Asset,
    Board
)
from .asset_checker_service import AssetCheckerService, AnalysisRequest
import logging

logger = logging.getLogger(__name__)

def trigger_ai_actions(field_value: CustomFieldValue) -> List[AIActionResult]:
    """
    Trigger AI actions for a field value if it has a single-select option with enabled AI actions.
    Combines all actions into a single Lambda request for efficiency.
    Returns a list of created AIActionResult objects.
    """
    if not field_value.option_value:
        return []

    # Get all enabled AI actions for this option
    enabled_actions = field_value.option_value.ai_action_configs.filter(
        is_enabled=True
    )

    if not enabled_actions.exists():
        return []

    # Get the content object (Asset or Board)
    content_object = field_value.content_object
    
    # Only process Assets for now
    if not isinstance(content_object, Asset):
        logger.warning(f"AssetChecker only supports Asset objects, got {type(content_object)}")
        return []

    # Create AIActionResult entries for all actions
    results = []
    for action_config in enabled_actions:
        result = AIActionResult.objects.create(
            field_value=field_value,
            action=action_config.action,
            status='PENDING'
        )
        results.append(result)

    # Process all actions in a single Lambda request
    try:
        process_combined_ai_actions(results)
    except Exception as e:
        logger.error(f"Failed to process combined AI actions: {str(e)}")
        # Mark all results as failed
        for result in results:
            result.status = 'FAILED'
            result.error_message = str(e)
            result.completed_at = timezone.now()
            result.save()

    return results

def process_combined_ai_actions(results: List[AIActionResult]) -> None:
    """
    Process multiple AI actions in a single Lambda request for efficiency.
    """
    if not results:
        return

    # All results should be for the same field_value and asset
    first_result = results[0]
    content_object = first_result.field_value.content_object
    
    # Mark all results as processing
    for result in results:
        result.status = 'PROCESSING'
        result.save()

    # Get S3 info from asset
    s3_bucket, s3_key = _get_asset_s3_info(content_object)
    
    # Build combined checks_enabled configuration
    checks_enabled = _build_combined_checks_enabled_config(results)
    
    # Start analysis with AssetCheckerService
    service = AssetCheckerService()
    
    # Create analysis request
    analysis_request = AnalysisRequest(
        s3_bucket=s3_bucket,
        s3_key=s3_key
    )
    
    # Store all AIActionResult IDs for later reference
    ai_action_result_ids = [result.id for result in results]
    
    response = service.start_analysis(
        analysis_request, 
        checks_enabled,
        ai_action_result_ids=ai_action_result_ids  # Pass list of IDs
    )
    
    # Store the check_id in all results for tracking
    for result in results:
        result.result = {
            'check_id': response.check_id,
            'status': response.status,
            'webhook_url': response.webhook_url,
            'checks_enabled': checks_enabled
        }
        result.save()
    
    logger.info(f"Started combined asset analysis {response.check_id} for {len(results)} AI actions")

def process_ai_action(result: AIActionResult) -> None:
    """
    Process a single AI action result using AssetCheckerService.
    """
    try:
        result.status = 'PROCESSING'
        result.save()

        # Get the content object (Asset or Board)
        content_object = result.field_value.content_object
        
        # Only process Assets for now
        if not isinstance(content_object, Asset):
            raise ValueError(f"AssetChecker only supports Asset objects, got {type(content_object)}")
        
        # Get the action configuration
        action_config = result.field_value.option_value.ai_action_configs.get(
            action=result.action
        )

        # Build checks_enabled configuration based on action type and config
        checks_enabled = _build_checks_enabled_config(result.action, action_config.configuration)
        
        # Get S3 info from asset
        s3_bucket, s3_key = _get_asset_s3_info(content_object)
        
        # Start analysis with AssetCheckerService
        service = AssetCheckerService()
        
        # Create analysis request
        analysis_request = AnalysisRequest(
            s3_bucket=s3_bucket,
            s3_key=s3_key
        )
        
        # Store the AIActionResult ID in the analysis request for later reference
        response = service.start_analysis(
            analysis_request, 
            checks_enabled,
            ai_action_result_id=result.id
        )
        
        # Store the check_id in the result for tracking
        result.result = {
            'check_id': response.check_id,
            'status': response.status,
            'webhook_url': response.webhook_url,
            'checks_enabled': checks_enabled
        }
        result.save()
        
        logger.info(f"Started asset analysis {response.check_id} for AI action {result.id}")

    except Exception as e:
        result.status = 'FAILED'
        result.error_message = str(e)
        result.completed_at = timezone.now()
        result.save()
        logger.error(f"Failed to process AI action {result.id}: {str(e)}")
        raise

def _build_combined_checks_enabled_config(results: List[AIActionResult]) -> Dict:
    """
    Build combined checks_enabled configuration for multiple AI actions.
    """
    checks_enabled = {
        "grammar": False,
        "color_contrast": False,
        "image_quality": False,
        "color_blindness": False,
        "text_accessibility": {
            "color_contrast": False,
            "color_blindness": False
        },
        "text_quality": {
            "font_size_detection": False,
            "text_overflow": False,
            "mixed_fonts": False,
            "placeholder_detection": False,
            "repeated_text": False
        }
    }
    
    # Process each AI action result
    for result in results:
        action = result.action
        action_config = result.field_value.option_value.ai_action_configs.get(action=action)
        config = action_config.configuration or {}
        
        # Enable checks based on action type
        if action == 'grammar':
            checks_enabled["grammar"] = True
            checks_enabled["language"] = config.get('language', 'en-US')
        
        elif action == 'color_contrast':
            checks_enabled["text_accessibility"]["color_contrast"] = True
        
        elif action == 'color_blindness':
            checks_enabled["text_accessibility"]["color_blindness"] = True
        
        elif action == 'image_quality':
            checks_enabled["image_quality"] = True
        
        elif action == 'font_size_detection':
            checks_enabled["text_quality"]["font_size_detection"] = True
        
        elif action == 'text_overflow':
            checks_enabled["text_quality"]["text_overflow"] = True
        
        elif action == 'mixed_fonts':
            checks_enabled["text_quality"]["mixed_fonts"] = True
        
        elif action == 'placeholder_detection':
            checks_enabled["text_quality"]["placeholder_detection"] = True
        
        elif action == 'repeated_text':
            checks_enabled["text_quality"]["repeated_text"] = True
    
    return checks_enabled

def _build_checks_enabled_config(action: str, config: Dict) -> Dict:
    """
    Build checks_enabled configuration based on action type and config.
    """
    checks_enabled = {
        "grammar": False,
        "color_contrast": False,
        "image_quality": False,
        "color_blindness": False,
        "text_accessibility": {
            "color_contrast": False,
            "color_blindness": False
        },
        "text_quality": {
            "font_size_detection": False,
            "text_overflow": False,
            "mixed_fonts": False,
            "placeholder_detection": False,
            "repeated_text": False
        }
    }
    
    # Enable checks based on action type
    if action == 'grammar':
        checks_enabled["grammar"] = True
        checks_enabled["language"] = config.get('language', 'en-US')
    
    elif action == 'color_contrast':
        checks_enabled["text_accessibility"]["color_contrast"] = True
    
    elif action == 'color_blindness':
        checks_enabled["text_accessibility"]["color_blindness"] = True
    
    elif action == 'image_quality':
        checks_enabled["image_quality"] = True
    
    elif action == 'font_size_detection':
        checks_enabled["text_quality"]["font_size_detection"] = True
    
    elif action == 'text_overflow':
        checks_enabled["text_quality"]["text_overflow"] = True
    
    elif action == 'mixed_fonts':
        checks_enabled["text_quality"]["mixed_fonts"] = True
    
    elif action == 'placeholder_detection':
        checks_enabled["text_quality"]["placeholder_detection"] = True
    
    elif action == 'repeated_text':
        checks_enabled["text_quality"]["repeated_text"] = True
    
    return checks_enabled

def _get_asset_s3_info(asset: Asset) -> tuple[str, str]:
    """
    Extract S3 bucket and key from asset.
    Assets follow the pattern: /media/workspace/[workspace_id]/assets/[asset_id]/medium.jpg
    """
    if not asset.file:
        raise ValueError(f"Asset {asset.id} has no file")
    
    from django.conf import settings
    
    # Get bucket from settings
    bucket = getattr(settings, 'AWS_STORAGE_CDN_BUCKET_NAME', 'crops-test')
    
    # Construct S3 key based on the pattern
    # /media/workspace/[workspace_id]/assets/[asset_id]/medium.jpg
    s3_key = f"media/workspaces/{asset.workspace.id}/assets/{asset.id}/medium.jpg"
    
    return bucket, s3_key

def process_asset_checker_webhook_result(check_id: str, results: Dict) -> None:
    """
    Process webhook results from AssetCheckerService and create comments.
    """
    try:
        # Find the AIActionResult that has this check_id in its result
        ai_results = AIActionResult.objects.filter(
            result__check_id=check_id,
            status='PROCESSING'
        )
        
        for ai_result in ai_results:
            try:
                # Update the AI action result
                ai_result.result.update({
                    'analysis_results': results,
                    'completed_at': timezone.now().isoformat()
                })
                ai_result.status = 'COMPLETED'
                ai_result.completed_at = timezone.now()
                ai_result.save()
                
                # Create comments on the asset based on the results
                _create_asset_comments(ai_result, results)
                
                logger.info(f"Processed webhook result for AI action {ai_result.id}")
                
            except Exception as e:
                ai_result.status = 'FAILED'
                ai_result.error_message = str(e)
                ai_result.completed_at = timezone.now()
                ai_result.save()
                logger.error(f"Failed to process webhook result for AI action {ai_result.id}: {str(e)}")
                
    except Exception as e:
        logger.error(f"Failed to process webhook result for check_id {check_id}: {str(e)}")

def _create_asset_comments(ai_result: AIActionResult, results: Dict) -> None:
    """
    Create comments on the asset based on analysis results.
    """
    try:
        content_object = ai_result.field_value.content_object
        if not isinstance(content_object, Asset):
            return
        
        # Extract issues from results based on action type
        issues = _extract_issues_from_results(ai_result.action, results)
        
        if issues:
            # Create a comment with the issues found
            from main.models import Comment
            
            comment_text = f"AI Analysis ({ai_result.get_action_display()}) found {len(issues)} issue(s):\n\n"
            for i, issue in enumerate(issues[:5], 1):  # Limit to first 5 issues
                comment_text += f"{i}. {issue}\n"
            
            if len(issues) > 5:
                comment_text += f"\n... and {len(issues) - 5} more issues."
            
            Comment.objects.create(
                content_object=content_object,
                author=None,  # System comment
                text=comment_text,
                comment_type='AI_ANALYSIS'
            )
            
            logger.info(f"Created comment with {len(issues)} issues for asset {content_object.id}")
        
    except Exception as e:
        logger.error(f"Failed to create asset comments: {str(e)}")

def _extract_issues_from_results(action: str, results: Dict) -> List[str]:
    """
    Extract issues from analysis results based on action type.
    Updated to handle the new structured results format from webhook processing.
    """
    issues = []
    
    try:
        # Handle both old and new result formats
        # New format has structured data with 'individual_checks', 'all_issues', etc.
        # Old format might have 'data' with 'individual_checks' array
        
        individual_checks = []
        
        # Try new format first (from updated webhook processing)
        if 'individual_checks' in results:
            individual_checks = results['individual_checks']
        # Fall back to old format if available
        elif 'data' in results and 'individual_checks' in results['data']:
            individual_checks = results['data']['individual_checks']
        
        # If we have pre-extracted issues, use them for quick filtering
        if 'all_issues' in results:
            all_issues = results['all_issues']
            # Filter issues based on action type
            if action == 'grammar':
                issues = [issue for issue in all_issues if issue.startswith('Grammar:')]
            elif action == 'color_contrast':
                issues = [issue for issue in all_issues if 'Color Contrast' in issue or 'color_contrast' in issue]
            elif action == 'color_blindness':
                issues = [issue for issue in all_issues if 'Color Blindness' in issue or 'color_blindness' in issue]
            elif action == 'image_quality':
                issues = [issue for issue in all_issues if 'Image Quality' in issue]
            elif action in ['font_size_detection', 'text_overflow', 'mixed_fonts', 'placeholder_detection', 'repeated_text']:
                issues = [issue for issue in all_issues if f'Text Quality ({action})' in issue]
            else:
                # For unknown actions, return all issues
                issues = all_issues
        else:
            # Fall back to manual extraction from individual_checks
            for check in individual_checks:
                if action == 'grammar' and check.get('check_type') == 'grammar':
                    grammar_result = check.get('grammar_result', {})
                    grammar_issues = grammar_result.get('issues', [])
                    issues.extend([f"Grammar: {issue}" for issue in grammar_issues])
                
                elif action == 'color_contrast' and check.get('check_type') == 'text_accessibility':
                    body = check.get('body', {})
                    accessibility_issues = body.get('issues', [])
                    for issue in accessibility_issues:
                        if isinstance(issue, dict) and issue.get('type') == 'color_contrast':
                            message = issue.get('message', str(issue))
                            issues.append(f"Color Contrast: {message}")
                
                elif action == 'color_blindness' and check.get('check_type') == 'text_accessibility':
                    body = check.get('body', {})
                    accessibility_issues = body.get('issues', [])
                    for issue in accessibility_issues:
                        if isinstance(issue, dict) and issue.get('type') == 'color_blindness':
                            subtype = issue.get('subtype', 'color blindness')
                            message = issue.get('message', str(issue))
                            issues.append(f"Color Blindness ({subtype}): {message}")
                
                elif action == 'image_quality' and check.get('check_type') == 'image_quality':
                    image_result = check.get('image_quality_result', {})
                    quality_issues = image_result.get('issues', [])
                    issues.extend([f"Image Quality: {issue}" for issue in quality_issues])
                    
                    # Also check recommendations if no issues
                    if not quality_issues:
                        recommendations = image_result.get('recommendations', [])
                        issues.extend([f"Image Quality Recommendation: {rec}" for rec in recommendations[:3]])
                
                # Text quality checks
                elif action in ['font_size_detection', 'text_overflow', 'mixed_fonts', 'placeholder_detection', 'repeated_text']:
                    if check.get('check_type') == 'text_quality':
                        text_quality_result = check.get('text_quality_result', {})
                        quality_issues = text_quality_result.get('issues', [])
                        for issue in quality_issues:
                            if isinstance(issue, dict):
                                issue_type = issue.get('type', 'text quality')
                                if issue_type == action:  # Only show issues for this specific action
                                    message = issue.get('message', str(issue))
                                    issues.append(f"Text Quality ({issue_type}): {message}")
                            else:
                                issues.append(f"Text Quality: {issue}")
    
    except Exception as e:
        logger.error(f"Failed to extract issues from results: {str(e)}")
        issues.append(f"Error parsing results: {str(e)}")
    
    return issues

def get_ai_action_results(content_object: Any) -> Dict[str, List[Dict]]:
    """
    Get all AI action results for a content object (Asset or Board).
    Returns a dictionary mapping field names to lists of results.
    """
    content_type = ContentType.objects.get_for_model(content_object)
    
    # Get all field values for this object
    field_values = CustomFieldValue.objects.filter(
        content_type=content_type,
        object_id=content_object.id
    ).select_related('field', 'option_value')

    results = {}
    for field_value in field_values:
        if field_value.field.field_type == 'SINGLE_SELECT' and field_value.option_value:
            field_results = field_value.ai_results.all().order_by('-created_at')
            if field_results.exists():
                results[field_value.field.title] = [
                    {
                        'action': result.get_action_display(),
                        'status': result.status,
                        'result': result.result,
                        'created_at': result.created_at,
                        'completed_at': result.completed_at,
                        'error_message': result.error_message
                    }
                    for result in field_results
                ]

    return results 