"""
Webhook Models for Asset Checker Service

Defines data models for webhook payloads and validation.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from ninja import Schema


class WebhookPayloadSchema(Schema):
    """Schema for incoming webhook payloads"""
    check_id: str
    status: str  # 'pending', 'processing', 'completed', 'failed'
    results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    progress: Optional[int] = None
    estimated_completion: Optional[str] = None


class AnalysisRequestSchema(Schema):
    """Schema for analysis requests"""
    s3_bucket: str
    s3_key: str
    checks_config: Dict[str, Any]
    use_webhook: bool = True
    callback_url: Optional[str] = None
    timeout: Optional[int] = None


class AnalysisResponseSchema(Schema):
    """Schema for analysis responses"""
    check_id: str
    status: str
    webhook_url: Optional[str] = None
    polling_url: Optional[str] = None
    estimated_completion: Optional[str] = None


class StatusResponseSchema(Schema):
    """Schema for status check responses"""
    check_id: str
    status: str
    progress: Optional[int] = None
    webhook_received: Optional[bool] = None
    source: Optional[str] = None  # 'local' or 'lambda'


class ResultsResponseSchema(Schema):
    """Schema for results responses"""
    check_id: str
    status: str
    results: Optional[Dict[str, Any]] = None
    webhook_received: Optional[bool] = None
    completed_at: Optional[str] = None
    source: Optional[str] = None


class SyncAnalysisRequestSchema(Schema):
    """Schema for synchronous analysis requests"""
    s3_bucket: str
    s3_key: str
    checks_config: Dict[str, Any]
    timeout: Optional[int] = 300  # 5 minutes default


class CallbackAnalysisRequestSchema(Schema):
    """Schema for analysis with custom callback"""
    s3_bucket: str
    s3_key: str
    checks_config: Dict[str, Any]
    callback_endpoint: str
    use_webhook: bool = True


@dataclass
class WebhookValidationResult:
    """Result of webhook validation"""
    is_valid: bool
    error_message: Optional[str] = None
    payload: Optional[WebhookPayloadSchema] = None


class WebhookValidator:
    """Validator for incoming webhook payloads"""
    
    VALID_STATUSES = {'pending', 'processing', 'completed', 'failed', 'no_checks_enabled'}
    
    @classmethod
    def validate_payload(cls, data: Dict[str, Any]) -> WebhookValidationResult:
        """
        Validate incoming webhook payload
        
        Args:
            data: Raw payload data
            
        Returns:
            WebhookValidationResult with validation status
        """
        try:
            # Check required fields
            if 'check_id' not in data:
                return WebhookValidationResult(
                    is_valid=False,
                    error_message="Missing required field: check_id"
                )
            
            if 'status' not in data:
                return WebhookValidationResult(
                    is_valid=False,
                    error_message="Missing required field: status"
                )
            
            # Validate status
            if data['status'] not in cls.VALID_STATUSES:
                return WebhookValidationResult(
                    is_valid=False,
                    error_message=f"Invalid status: {data['status']}. Must be one of {cls.VALID_STATUSES}"
                )
            
            # Validate check_id format
            check_id = data['check_id']
            if not isinstance(check_id, str) or len(check_id.strip()) == 0:
                return WebhookValidationResult(
                    is_valid=False,
                    error_message="check_id must be a non-empty string"
                )
            
            # Validate progress if present
            if 'progress' in data:
                progress = data['progress']
                if not isinstance(progress, int) or progress < 0 or progress > 100:
                    return WebhookValidationResult(
                        is_valid=False,
                        error_message="progress must be an integer between 0 and 100"
                    )
            
            # Create schema instance
            payload = WebhookPayloadSchema(**data)
            
            return WebhookValidationResult(
                is_valid=True,
                payload=payload
            )
            
        except Exception as e:
            return WebhookValidationResult(
                is_valid=False,
                error_message=f"Validation error: {str(e)}"
            )
    
    @classmethod
    def validate_signature(cls, payload: str, signature: str, secret: str) -> bool:
        """
        Validate webhook signature for security
        
        Args:
            payload: Raw payload string
            signature: Signature from webhook headers
            secret: Shared secret for validation
            
        Returns:
            True if signature is valid, False otherwise
        """
        import hmac
        import hashlib
        
        if not secret or not signature:
            return False
        
        # Calculate expected signature
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures
        return hmac.compare_digest(signature, expected_signature)


class ChecksConfigBuilder:
    """Builder for creating analysis configuration matching the new lambda API"""
    
    def __init__(self):
        self.config = {
            "grammar": False,
            "language": "en-US",
            "image_quality": False,
            "text_accessibility": {
                "color_contrast": False,
                "color_blindness": False
            },
            "text_quality": {
                "font_size_detection": False,
                "text_overflow": False,
                "placeholder_detection": False,
                "repeated_text": False
            }
        }
    
    def grammar(self, enabled: bool = True, language: str = 'en-US'):
        """Enable grammar check"""
        self.config['grammar'] = enabled
        self.config['language'] = language
        return self
    
    def image_quality(self, enabled: bool = True):
        """Enable image quality check"""
        self.config['image_quality'] = enabled
        return self
    
    def color_contrast(self, enabled: bool = True):
        """Enable color contrast check"""
        self.config['text_accessibility']['color_contrast'] = enabled
        return self
    
    def color_blindness(self, enabled: bool = True):
        """Enable color blindness check"""
        self.config['text_accessibility']['color_blindness'] = enabled
        return self
    
    def font_size_detection(self, enabled: bool = True):
        """Enable font size detection"""
        self.config['text_quality']['font_size_detection'] = enabled
        return self
    
    def text_overflow(self, enabled: bool = True):
        """Enable text overflow detection"""
        self.config['text_quality']['text_overflow'] = enabled
        return self
    
    def mixed_fonts(self, enabled: bool = True):
        """Enable mixed fonts detection"""
        self.config['text_quality']['mixed_fonts'] = enabled
        return self
    
    def placeholder_detection(self, enabled: bool = True):
        """Enable placeholder text detection"""
        self.config['text_quality']['placeholder_detection'] = enabled
        return self
    
    def repeated_text(self, enabled: bool = True):
        """Enable repeated text detection"""
        self.config['text_quality']['repeated_text'] = enabled
        return self
    
    def custom_check(self, check_type: str, config: Dict[str, Any]):
        """Add custom check (for future extensibility)"""
        if 'custom_checks' not in self.config:
            self.config['custom_checks'] = []
        
        self.config['custom_checks'].append({
            'type': check_type,
            'config': config
        })
        return self
    
    def build(self) -> Dict[str, Any]:
        """Build the final configuration"""
        return self.config.copy()