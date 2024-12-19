from ninja import Router, Schema
from ninja.security import django_auth
from pydantic import BaseModel
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from .models import CustomUser as User
from .utils import send_verification_email, get_client_ip, send_password_reset_email, send_email_change_verification
from django.utils import timezone
from typing import Optional, Any
from django.core.cache import cache
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.mail import send_mail
from datetime import timedelta
from django.contrib.auth.models import AbstractUser
from django.utils.crypto import get_random_string
from django.http import JsonResponse
from http import HTTPStatus
from ninja.responses import Response
from typing import List
import logging
from main.models import WorkspaceInvitation
from main.utils import accept_invitation

logger = logging.getLogger(__name__)

router = Router(tags=["users"])

class SignInSchema(BaseModel):
    email: str
    password: str
    
class SignUpSchema(BaseModel):
    email: str
    password: str
    invite_token: Optional[str] = None

class ResendVerificationSchema(BaseModel):
    email: str

class ApiResponse(BaseModel):
    status: str  # "success" or "error"
    message: str
    data: Optional[dict] = None
    errors: Optional[list[dict]] = None
    meta: Optional[dict] = None

    def send(self, status_code: int = HTTPStatus.OK) -> JsonResponse:
        """Convert the response to a JsonResponse with appropriate status code"""
        return JsonResponse(self.dict(), status=status_code)

    @classmethod
    def error(cls, message: str, errors: list[dict] = None, status_code: int = HTTPStatus.BAD_REQUEST) -> JsonResponse:
        """Helper method for error responses"""
        return cls(
            status="error",
            message=message,
            errors=errors or []
        ).send(status_code)

    @classmethod
    def success(cls, message: str, data: dict = None, meta: dict = None) -> JsonResponse:
        """Helper method for success responses"""
        return cls(
            status="success",
            message=message,
            data=data,
            meta=meta
        ).send(HTTPStatus.OK)

class PasswordResetRequestSchema(BaseModel):
    email: str

class PasswordResetConfirmSchema(BaseModel):
    token: str
    new_password: str

class EmailChangeSchema(BaseModel):
    new_email: str

class ErrorDetail(Schema):
    code: str
    message: str
    details: dict = None

    class Config:
        json_schema_extra = {
            "example": {
                "code": "invalid_input",
                "message": "Invalid email format",
                "details": {"field": "email"}
            }
        }

class ApiResponseSchema(Schema):
    status: str
    message: str
    data: dict = None
    errors: List[ErrorDetail] = None
    meta: dict = None

    class Config:
        json_schema_extra = {
            "examples": {
                "success": {
                    "summary": "Success Response",
                    "value": {
                        "status": "success",
                        "message": "Operation completed successfully",
                        "data": {"id": 1, "email": "user@example.com"},
                        "errors": None,
                        "meta": None
                    }
                },
                "error": {
                    "summary": "Error Response",
                    "value": {
                        "status": "error",
                        "message": "Operation failed",
                        "data": None,
                        "errors": [{
                            "code": "validation_error",
                            "message": "Invalid input",
                            "details": {"field": "email"}
                        }],
                        "meta": None
                    }
                }
            }
        }

@router.get("/set-csrf-token",
    auth=None,  # Disable authentication for this endpoint
    response={
        200: ApiResponseSchema
    },
    summary="Get CSRF Token",
    description="""
    Get a CSRF token for making authenticated requests.
    
    Usage:
    1. Call this endpoint to get the token
    2. Include the token in subsequent requests:
       - Header: X-CSRFToken: <token>
       - Cookie: csrftoken=<token> (set automatically)
    
    javascript Example:
    
    // Get the token
    const response = await fetch('/api/set-csrf-token');
    const data = await response.json();
    const csrfToken = data.data.csrftoken;
    
    // Use the token in subsequent requests
    await fetch('/api/login', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        credentials: 'include',  // Important! This sends cookies
        body: JSON.stringify({
            email: 'user@example.com',
            password: 'password'
        })
    });
    """
)
def get_csrf_token(request):
    """Get a new CSRF token for making authenticated requests"""
    print("get_csrf_token")
    return ApiResponse.success(
        message="CSRF token generated",
        data={"csrftoken": get_token(request)}
    )
    

@router.post("/login", 
    auth=None,
    response={
        200: ApiResponseSchema,
        401: ApiResponseSchema,
        403: ApiResponseSchema,
        429: ApiResponseSchema,
        500: ApiResponseSchema
    },
    summary="User login",
    description="Authenticate a user with email and password"
)
def login_view(request, payload: SignInSchema):
    """
    Login endpoint
    
    Possible responses:
    * 200: Successful login
    * 401: Invalid credentials
    * 403: Email not verified
    * 429: Too many login attempts
    * 500: Server error
    """
    try:
        # Rate limiting check
        ip = get_client_ip(request)
        cache_key = f"login_attempts_{ip}"
        attempts = cache.get(cache_key, 0)
        
        if attempts >= 5:
            return ApiResponse.error(
                message="Too many login attempts",
                errors=[{
                    "code": "rate_limit_exceeded",
                    "message": "Please try again later",
                    "details": {"retry_after": "300 seconds"}
                }],
                status_code=HTTPStatus.TOO_MANY_REQUESTS  # 429
            )

        user = authenticate(request, username=payload.email, password=payload.password)
        if user is None:
            cache.set(cache_key, attempts + 1, 300)
            return ApiResponse.error(
                message="Authentication failed",
                errors=[{
                    "code": "invalid_credentials",
                    "message": "Invalid email or password"
                }],
                status_code=HTTPStatus.UNAUTHORIZED  # 401
            )

        if not user.email_verified:
            login(request, user)  # Log them in anyway
            return ApiResponse.success(
                message="Login successful but email needs verification",
                data={
                    "email": user.email,
                    "username": user.username,
                    "needs_verification": True
                },
                meta={
                    "redirect_to": "/verify-email"  # Frontend can use this to redirect
                }
            )
        
        login(request, user)
        cache.delete(cache_key)
        
        return ApiResponse.success(
            message="Login successful",
            data={
                "email": user.email,
                "username": user.username,
                "needs_verification": False
            }
        )

    except Exception as e:
        return ApiResponse.error(
            message="Internal server error",
            errors=[{
                "code": "internal_error",
                "message": str(e)
            }],
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR  # 500
        )

@router.post("/logout", 
    auth=None,
    response={
        200: ApiResponseSchema,
        401: ApiResponseSchema
    },
    summary="User logout",
    description="Log out the current user"
)
def logout_view(request):
    """
    Logout endpoint
    
    Possible responses:
    * 200: Successfully logged out
    * 401: Not authenticated
    """
    logout(request)
    return ApiResponse.success(message="Logged out successfully")

@router.get("/me", 
    response={
        200: ApiResponseSchema,
        401: ApiResponseSchema
    },
    summary="Get user details",
    description="Get details of the currently authenticated user"
)
def get_user(request):
    """
    Get user details endpoint
    
    Possible responses:
    * 200: User details retrieved successfully
    * 401: Not authenticated
    """
    # Get user details, otherwise return anonymous user
    user = request.user if request.user.is_authenticated else AnonymousUser()
    
    return ApiResponse.success(
        message="User details retrieved",
        data={
            "email": request.user.email,
            "username": request.user.username,
        }
    )

@router.post("/register",
    auth=None,
    response={
        200: ApiResponseSchema,
        400: ApiResponseSchema,
        409: ApiResponseSchema,
        500: ApiResponseSchema
    },
    summary="User registration",
    description="Register a new user account"
)
def register(request, payload: SignUpSchema):
    """
    Register a new user
    
    Possible responses:
    * 201: User successfully registered
    * 400: Invalid input data
    * 409: Email already exists
    * 500: Server error
    """
    try:
        # Validate email format
        if not User.is_valid_email(payload.email):
            return ApiResponse.error(
                message="Invalid email format",
                errors=[{
                    "code": "invalid_email",
                    "message": "Please provide a valid email address"
                }]
            )

        # Check if email already exists
        if User.objects.filter(email=payload.email).exists():
            return ApiResponse.error(
                message="Email already registered",
                errors=[{
                    "code": "email_exists",
                    "message": "This email is already registered"
                }]
            )
        
        verified = False
        if payload.invite_token:
            try:
                # Check if invite token is valid
                invitation = WorkspaceInvitation.objects.get(token=payload.invite_token)
                if invitation.email == payload.email:
                    verified = True
            except WorkspaceInvitation.DoesNotExist:
                # Continue with registration even if invitation is not found
                pass
            
        # Create user
        user = User.objects.create_user(
            username=payload.email, 
            email=payload.email, 
            password=payload.password,
            email_verified=verified
        )
        logger.info(f"User created: {user.email}")
        logger.info(f"Invite token: {payload.invite_token}")
        logger.info(f"Verified: {verified}")
        
        # Handle invitation after user creation
        if payload.invite_token:
            try:
                logger.info(f"Accepting invitation: {payload.invite_token}")
                accept_invitation(payload.invite_token, user)
            except Exception as e:
                logger.error(f"Error accepting invitation: {str(e)}")
                # Continue with registration even if invitation acceptance fails
        
        # Send verification email unless already verified
        if not verified:
            send_verification_email(user)
        
        # Log the user in after registration
        login(request, user)
        
        return ApiResponse.success(
            message="User registered successfully. Please check your email to verify your account.",
            data={
                "email": user.email,
                "username": user.username,
                "needs_verification": not verified
            }
        )

    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return ApiResponse.error(
            message="An error occurred during registration",
            errors=[{
                "code": "registration_error",
                "message": str(e)
            }]
        )

@router.post("/verify-email/{token}",
    auth=None,
    response={
        200: ApiResponseSchema,
        400: ApiResponseSchema,
        404: ApiResponseSchema
    },
    summary="Verify email address",
    description="Verify the user's email address using the token from email"
)
def verify_email(request, token: str):
    """
    Verify email endpoint
    
    Possible responses:
    * 200: Email successfully verified
    * 400: Expired token
    * 404: Invalid token
    """
    try:
        logger.info(f"Verifying email with token: {token}")
        user = User.objects.get(verification_token=token)
        
        if not user.is_verification_token_valid():
            return ApiResponse(
                status="error",
                message="Verification token has expired. Please request a new one.",
                data={"email": user.email}
            ).dict()

        user.email_verified = True
        user.verification_token = None
        user.verification_token_created = None
        user.save()
        
        return ApiResponse.success(
            message="Email verified successfully"
        )
    except User.DoesNotExist:
        return ApiResponse.error(
            message="Invalid verification token"
        )

@router.post("/resend-verification",
    response={
        200: ApiResponseSchema,
        400: ApiResponseSchema,
        429: ApiResponseSchema
    },
    summary="Resend verification email",
    description="Request a new verification email for unverified accounts"
)
def resend_verification(request, payload: ResendVerificationSchema):
    """
    Resend verification email endpoint
    
    Possible responses:
    * 200: Verification email sent or account not found
    * 400: Invalid request
    * 429: Too many verification attempts
    """
    try:
        user = User.objects.get(email=payload.email, email_verified=False)
        
        if not user.can_send_verification_email():
            time_diff = timezone.now() - user.last_verification_email_sent
            wait_time = 24 - (time_diff.total_seconds() / 3600)  # Convert seconds to hours
            return ApiResponse(
                status="error",
                message=f"Too many verification emails sent. Please wait {int(wait_time)} hours before requesting another."
            ).dict()

        send_verification_email(user)
        return ApiResponse.success(
            message="Verification email sent successfully"
        )
    
    except User.DoesNotExist:
        return ApiResponse.success(
            message="If this email exists and is unverified, a verification email has been sent."
        )
    except ValueError as e:
        return ApiResponse(
            status="error",
            message=str(e)
        ).dict()

@router.post("/password-reset-request",
    response={
        200: ApiResponseSchema,
        400: ApiResponseSchema,
        429: ApiResponseSchema
    },
    summary="Request password reset",
    description="Request a password reset email"
)
def password_reset_request(request, payload: PasswordResetRequestSchema):
    """
    Password reset request endpoint
    
    Possible responses:
    * 200: Reset email sent or account not found
    * 400: Invalid email format
    * 429: Too many reset attempts
    """
    try:
        user = User.objects.get(email=payload.email)
        send_password_reset_email(user)
        return ApiResponse.success(
            message="If an account exists with this email, a password reset link has been sent."
        )
    except User.DoesNotExist:
        return ApiResponse.success(
            message="If an account exists with this email, a password reset link has been sent."
        )

@router.post("/password-reset-confirm",
    response={
        200: ApiResponseSchema,
        400: ApiResponseSchema,
        404: ApiResponseSchema
    },
    summary="Confirm password reset",
    description="Reset password using the token from email"
)
def password_reset_confirm(request, payload: PasswordResetConfirmSchema):
    """
    Password reset confirmation endpoint
    
    Possible responses:
    * 200: Password successfully reset
    * 400: Invalid password or expired token
    * 404: Invalid token
    """
    try:
        user = User.objects.get(password_reset_token=payload.token)
        
        # Check token expiration (1 hour)
        if not user.password_reset_token_created or \
           timezone.now() - user.password_reset_token_created > timedelta(hours=1):
            return ApiResponse(
                status="error",
                message="Password reset link has expired. Please request a new one."
            ).dict()

        # Validate new password
        try:
            validate_password(payload.new_password)
        except ValidationError as e:
            return ApiResponse(
                status="error",
                message="Invalid password",
                errors={"password": list(e.messages)}
            ).dict()

        # Set new password
        user.set_password(payload.new_password)
        user.password_reset_token = None
        user.password_reset_token_created = None
        user.save()

        return ApiResponse(
            status="success",
            message="Password has been reset successfully"
        ).dict()
    except User.DoesNotExist:
        return ApiResponse(
            status="error",
            message="Invalid reset token"
        ).dict()

@router.post("/change-email", 
    response={
        200: ApiResponseSchema,
        400: ApiResponseSchema,
        401: ApiResponseSchema,
        409: ApiResponseSchema
    },
    summary="Change email address",
    description="Request to change the user's email address"
)
def change_email(request, payload: EmailChangeSchema):
    """
    Change email endpoint
    
    Possible responses:
    * 200: Verification email sent to new address
    * 400: Invalid email format
    * 401: Not authenticated
    * 409: Email already in use
    """
    try:
        user = request.user
        new_email = payload.new_email

        # Validate new email
        if not User.is_valid_email(new_email):
            return ApiResponse(
                status="error",
                message="Invalid email format"
            ).dict()

        # Check if email is already in use
        if User.objects.filter(email=new_email).exists():
            return ApiResponse(
                status="error",
                message="This email is already registered"
            ).dict()

        # Store new email temporarily
        user.new_email = new_email
        user.save()
        
        # Send verification email
        send_email_change_verification(user, new_email)

        return ApiResponse(
            status="success",
            message="Please check your new email address for verification"
        ).dict()
    except Exception as e:
        return ApiResponse(
            status="error",
            message="An error occurred",
            errors={"detail": str(e)}
        ).dict()

@router.get("/verify-email-change/{token}",
    response={
        200: ApiResponseSchema,
        400: ApiResponseSchema,
        404: ApiResponseSchema
    },
    summary="Verify email change",
    description="Verify the new email address using the token from email"
)
def verify_email_change(request, token: str):
    """
    Verify email change endpoint
    
    Possible responses:
    * 200: Email successfully changed
    * 400: Expired token
    * 404: Invalid token
    """
    try:
        user = User.objects.get(new_email_token=token)
        
        # Check token expiration (24 hours)
        if not user.new_email_token_created or \
           timezone.now() - user.new_email_token_created > timedelta(hours=24):
            return ApiResponse(
                status="error",
                message="Email verification link has expired. Please try again."
            ).dict()

        # Update email
        old_email = user.email
        user.email = user.new_email
        user.new_email = None
        user.new_email_token = None
        user.new_email_token_created = None
        user.save()

        # Notify old email about the change
        send_mail(
            'Email address changed',
            f'Your email address has been changed to {user.email}.',
            settings.DEFAULT_FROM_EMAIL,
            [old_email],
            fail_silently=False,
        )

        return ApiResponse(
            status="success",
            message="Email address has been changed successfully"
        ).dict()
    except User.DoesNotExist:
        return ApiResponse(
            status="error",
            message="Invalid verification token"
        ).dict()

@router.get("/debug-session")
def debug_session(request):
    return {
        "session_id": request.session.session_key,
        "is_authenticated": request.user.is_authenticated,
        "session_data": dict(request.session),
    }