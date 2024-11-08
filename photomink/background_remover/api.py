from ninja import Router, Schema
import settings
from enum import Enum
from typing import Optional, Union
from ninja.files import UploadedFile
from ninja.errors import HttpError
from typing import List, Dict, Any
import re
from ninja.responses import StreamingResponse
from typing import AsyncGenerator, Tuple
import aiohttp
from PIL import Image
import io

router = Router()

class SizeEnum(str, Enum):
    PREVIEW = "preview"
    FULL = "full"
    MP50 = "50MP"
    AUTO = "auto"
    MEDIUM = "medium"
    HD = "hd"
    SMALL = "small"
    REGULAR = "regular"
    FOUR_K = "4k"

class FormatEnum(str, Enum):
    AUTO = "auto"
    PNG = "png"
    JPG = "jpg"
    ZIP = "zip"

class ForegroundTypeEnum(str, Enum):
    AUTO = "auto"
    CAR = "car"
    PRODUCT = "product"
    PERSON = "person"
    ANIMAL = "animal"
    GRAPHIC = "graphic"
    TRANSPORTATION = "transportation"

class TypeLevelEnum(str, Enum):
    NONE = "none"
    LEVEL_1 = "1"
    LEVEL_2 = "2"
    LATEST = "latest"

class ChannelsEnum(str, Enum):
    RGBA = "rgba"
    ALPHA = "alpha"

class ShadowTypeEnum(str, Enum):
    AUTO = "auto"
    CAR = "car"
    THREE_D = "3D"
    DROP = "drop"
    NONE = "none"

class BackgroundRemovalSchema(Schema):
    # Image source (only one should be provided)
    image_file: Optional[UploadedFile] = None
    image_file_b64: Optional[str] = None
    image_url: Optional[str] = None
    
    # Basic processing options
    size: SizeEnum = SizeEnum.PREVIEW
    format: FormatEnum = FormatEnum.AUTO
    type: ForegroundTypeEnum = ForegroundTypeEnum.AUTO
    type_level: TypeLevelEnum = TypeLevelEnum.LATEST
    
    # ROI and cropping
    roi: Optional[str] = None  # Format: "x1 y1 x2 y2" with px or % suffix
    crop: bool = False
    crop_margin: Optional[str] = None  # Format: "30px" or "10%" or "10px 20px" or "10px 20px 30px 40px"
    
    # Scaling and positioning
    scale: Optional[str] = None  # "10%" to "100%" or "original"
    position: Optional[str] = None  # "original", "center", or "x% y%"
    
    # Output options
    channels: ChannelsEnum = ChannelsEnum.RGBA
    semitransparency: bool = True
    
    # Shadow options
    shadow_type: Optional[ShadowTypeEnum] = None
    shadow_opacity: Optional[Union[int, str]] = None  # 0-100 or "auto"
    
    # Background options (only one should be provided)
    bg_color: Optional[str] = None
    bg_image_url: Optional[str] = None
    bg_image_file: Optional[UploadedFile] = None

class BackgroundRemovalError(HttpError):
    """Base exception for background removal errors"""
    def __init__(self, message: str, status_code: int = 400, code: str = None):
        self.code = code
        super().__init__(status_code, {"errors": [{"title": message, "code": code} if code else {"title": message}]})

class MultipleSourcesError(BackgroundRemovalError):
    def __init__(self):
        super().__init__(
            "Multiple image sources given: Please provide either the image_url, image_file or image_file_b64 parameter.",
            400,
            "multiple_sources"
        )

class NoSourceError(BackgroundRemovalError):
    def __init__(self):
        super().__init__(
            "No image source provided: Please provide either image_url, image_file or image_file_b64 parameter.",
            400,
            "no_source"
        )

class ValidationError(BackgroundRemovalError):
    def __init__(self, message: str):
        super().__init__(message, 400, "validation_error")

class WorkerServiceError(BackgroundRemovalError):
    def __init__(self, message: str = "Worker service unavailable"):
        super().__init__(message, 503, "worker_error")

def validate_background_removal_request(data: BackgroundRemovalSchema) -> None:
    """Validates the background removal request parameters"""
    
    # Validate image sources
    sources = [data.image_file, data.image_file_b64, data.image_url]
    source_count = len([s for s in sources if s is not None])
    if source_count == 0:
        raise NoSourceError()
    if source_count > 1:
        raise MultipleSourcesError()

    # Validate background options
    bg_sources = [data.bg_color, data.bg_image_url, data.bg_image_file]
    bg_source_count = len([s for s in bg_sources if s is not None])
    if bg_source_count > 1:
        raise ValidationError("Multiple background sources provided: Please provide only one of bg_color, bg_image_url, or bg_image_file")

    # Validate ROI format if provided
    if data.roi:
        roi_pattern = r'^(\d+(?:px|%)\s+){3}\d+(?:px|%)$'
        if not re.match(roi_pattern, data.roi):
            raise ValidationError("Invalid ROI format. Expected format: 'x1 y1 x2 y2' with px or % suffix")

    # Validate crop margin format if provided
    if data.crop_margin:
        margin_pattern = r'^(\d+(?:px|%))(?:\s+\d+(?:px|%)){0,3}$'
        if not re.match(margin_pattern, data.crop_margin):
            raise ValidationError("Invalid crop margin format. Expected format: '30px' or '10%' or '10px 20px' or '10px 20px 30px 40px'")

    # Validate scale format
    if data.scale:
        if data.scale != "original" and not re.match(r'^\d{1,3}%$', data.scale):
            raise ValidationError("Invalid scale format. Expected 'original' or percentage between 10% and 100%")
        if data.scale != "original":
            scale_value = int(data.scale.rstrip('%'))
            if not (10 <= scale_value <= 100):
                raise ValidationError("Scale percentage must be between 10% and 100%")

    # Validate position format
    if data.position and data.position != "original" and data.position != "center":
        pos_pattern = r'^(\d{1,3}%)(?:\s+\d{1,3}%)?$'
        if not re.match(pos_pattern, data.position):
            raise ValidationError("Invalid position format. Expected 'original', 'center', or percentage(s)")
        
    # Validate shadow opacity
    if data.shadow_opacity is not None:
        if isinstance(data.shadow_opacity, str):
            if data.shadow_opacity != "auto":
                raise ValidationError("Shadow opacity string value must be 'auto'")
        elif isinstance(data.shadow_opacity, int):
            if not (0 <= data.shadow_opacity <= 100):
                raise ValidationError("Shadow opacity must be between 0 and 100")

    # Validate hex color format if bg_color provided
    if data.bg_color:
        hex_pattern = r'^#?([0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$'
        if not re.match(hex_pattern, data.bg_color) and not is_valid_color_name(data.bg_color):
            raise ValidationError("Invalid background color format. Expected hex color or valid color name")

def is_valid_color_name(color: str) -> bool:
    """
    Validates if the provided string is a valid CSS color name.
    This is a simplified version - you might want to add a complete list of valid CSS color names.
    """
    # Add more color names as needed
    valid_colors = {
        'black', 'white', 'red', 'green', 'blue', 'yellow', 'purple', 'orange',
        'gray', 'grey', 'pink', 'brown', 'transparent'
    }
    return color.lower() in valid_colors

class BackgroundRemovalResponse:
    """Helper class to handle background removal responses"""
    def __init__(self, content: bytes, headers: Dict[str, str]):
        self.content = content
        self.headers = headers
        self._process_image_metadata()

    def _process_image_metadata(self):
        """Extract image metadata from the content"""
        try:
            img = Image.open(io.BytesIO(self.content))
            self.headers.update({
                'X-Width': str(img.width),
                'X-Height': str(img.height),
                'Content-Type': Image.MIME[img.format],
            })
        except Exception as e:
            raise WorkerServiceError(f"Failed to process image metadata: {str(e)}")

async def stream_file_to_worker(file: UploadedFile) -> AsyncGenerator[bytes, None]:
    """Stream the uploaded file in chunks"""
    chunk_size = 8192  # 8KB chunks
    while True:
        chunk = file.file.read(chunk_size)
        if not chunk:
            break
        yield chunk

async def process_background_removal(
    data: BackgroundRemovalSchema,
    worker_url: str = settings.BACKGROUND_REMOVAL_URL
) -> Tuple[AsyncGenerator[bytes, None], Dict[str, str]]:
    """Process background removal request and return streaming response"""
    
    headers = {
        'Content-Type': 'application/octet-stream',
        'X-Credits-Charged': '1',  # This should be dynamic based on size
    }

    # Prepare the form data
    form_data = aiohttp.FormData()
    
    # Add image source
    if data.image_file:
        form_data.add_field('image', 
                           data.image_file.file,
                           filename=data.image_file.name,
                           content_type=data.image_file.content_type)
    elif data.image_url:
        form_data.add_field('image_url', data.image_url)
    elif data.image_file_b64:
        form_data.add_field('image_file_b64', data.image_file_b64)

    # Add all other parameters
    for field, value in data.dict(exclude_unset=True).items():
        if field not in ['image_file', 'image_url', 'image_file_b64'] and value is not None:
            form_data.add_field(field, str(value))

    async def stream_response() -> AsyncGenerator[bytes, None]:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(worker_url, data=form_data) as response:
                    if response.status != 200:
                        error_data = await response.json()
                        raise WorkerServiceError(error_data.get('errors', [{}])[0].get('title', 'Unknown error'))
                    
                    # Update headers with worker response headers
                    headers.update({
                        k: v for k, v in response.headers.items()
                        if k.startswith('X-') or k in ['Content-Type', 'Content-Length']
                    })
                    
                    # Stream the response content
                    async for chunk in response.content.iter_chunked(8192):
                        yield chunk
            except aiohttp.ClientError as e:
                raise WorkerServiceError(f"Worker service connection error: {str(e)}")

    return stream_response(), headers

@router.post("/remove-background")
async def remove_background(request, data: BackgroundRemovalSchema):
    """
    Remove background from image with streaming support
    """
    try:
        # Validate request parameters
        validate_background_removal_request(data)
        
        # Process the request
        stream, headers = await process_background_removal(data)
        
        # Return streaming response
        return StreamingResponse(
            stream,
            headers=headers,
            media_type=headers.get('Content-Type', 'application/octet-stream')
        )
        
    except BackgroundRemovalError as e:
        # Re-raise background removal specific errors
        raise e
    except Exception as e:
        # Handle unexpected errors
        raise WorkerServiceError(f"Unexpected error: {str(e)}")