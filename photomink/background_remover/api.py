from ninja import Router, Form, File
from ninja.files import UploadedFile
from django.conf import settings
from django.http import FileResponse
import io
import httpx
from httpx import TimeoutException, ConnectError
import base64
from enum import Enum
from typing import Optional
import logging

# Set up logging
logger = logging.getLogger(__name__)

router = Router(tags=["background-removal"])

class ImageSize(str, Enum):
    PREVIEW = "preview"
    FULL = "full"
    MP_50 = "50MP"
    AUTO = "auto"
    # Aliases
    SMALL = "small"
    REGULAR = "regular"
    MEDIUM = "medium"
    HD = "hd"
    _4K = "4k"

    @classmethod
    def get_canonical_size(cls, size: str) -> str:
        """Convert aliases to canonical size names"""
        logger.debug(f"Converting size: {size}")
        alias_map = {
            "small": "preview",
            "regular": "preview",
            "4k": "full",
        }
        canonical = alias_map.get(size, size)
        logger.debug(f"Converted to: {canonical}")
        return canonical

class ForegroundType(str, Enum):
    AUTO = "auto"
    CAR = "car"
    PRODUCT = "product"
    PERSON = "person"
    ANIMAL = "animal"
    GRAPHIC = "graphic"
    TRANSPORTATION = "transportation"

class ImageFormat(str, Enum):
    AUTO = "auto"
    PNG = "png"
    JPG = "jpg"
    ZIP = "zip"

@router.post("/remove-background", summary="Remove background from image")
async def remove_background(
    request,
    image_file: UploadedFile = File(
        None, 
        description="Image file to remove background from"
    ),
    image_url: str = Form(
        '', 
        description="URL of image to remove background from",
        example=""
    ),
    image_file_b64: str = Form(
        '', 
        description="Base64 encoded image to remove background from",
        example=""
    ),
    size: ImageSize = Form(
        ImageSize.PREVIEW,
        description="Output image resolution:\n"
        "- preview (default): 0.25 megapixels (e.g., 625×400)\n"
        "- full: Up to 25MP (ZIP/JPG) or 10MP (PNG)\n"
        "- 50MP: Up to 50MP (ZIP/JPG) or 10MP (PNG)\n"
        "- auto: Highest available up to 25MP\n"
        "- medium: Up to 1.5MP (legacy)\n"
        "- hd: Up to 4MP (legacy)"
    ),
    type: ForegroundType = Form(
        ForegroundType.AUTO,
        description="Detect or set a foreground type:\n"
        "- auto (default): Automatically detect the type\n"
        "- car: Vehicle detection\n"
        "- product: Product detection\n"
        "- person: Person detection\n"
        "- animal: Animal detection\n"
        "- graphic: Graphic/illustration detection\n"
        "- transportation: Any transportation method"
    ),
    format: ImageFormat = Form(
        ImageFormat.AUTO,
        description="Result image format:\n"
        "- auto (default): Use PNG if transparent regions exist, otherwise use JPG\n"
        "- png: PNG format with alpha transparency\n"
        "- jpg: JPG format, no transparency\n"
        "- zip: ZIP format with color image and alpha matte (recommended)"
    ),
    roi: Optional[str] = Form(
        None,
        description="Region of interest: Rectangular region for foreground detection.\n"
        "Format: 'x1 y1 x2 y2' with suffix 'px' or '%'.\n"
        "Example: '10% 20% 90% 80%' or '100px 200px 800px 600px'\n"
        "Default: '0% 0% 100% 100%' (whole image)",
        example="0% 0% 100% 100%"
    ),
    crop: bool = Form(
        False,
        description="Whether to crop off all empty regions"
    ),
    crop_margin: Optional[str] = Form(
        '',
        description="Margin around the cropped subject. Only applies when crop=true.\n"
        "Format: Single value (all sides), two values (top/bottom left/right),\n"
        "or four values (top right bottom left) with 'px' or '%' suffix.\n"
        "Examples: '30px', '10%', '10px 20px', '10px 20px 10px 20px'\n"
        "Max: 50% of subject size or 500px per side.\n"
        "Default: '0'"
    )
) -> FileResponse:
    """Remove background from image."""
    
    try:
        # Validate input
        provided = sum(1 for x in [image_file, image_url, image_file_b64] 
                      if x is not None and x != '')
        if provided != 1:
            raise Exception("Please provide exactly one of: image file, image URL, or base64 image")

        # Convert size alias to canonical value and log it
        logger.info(f"Original size parameter: {size}")
        canonical_size = ImageSize.get_canonical_size(size.value)
        logger.info(f"Canonical size: {canonical_size}")
        logger.info(f"Foreground type: {type}")

        params = {
            'size': canonical_size,
            'type': type.value,
            'format': format.value,
            'crop': crop,
        }
        if roi is not None:
            params['roi'] = roi
        if crop_margin is not None:
            params['crop_margin'] = crop_margin

        async with httpx.AsyncClient(timeout=180.0) as client:
            if image_file:
                files = {'image_file': (image_file.name, image_file.file, image_file.content_type)}
                response = await client.post(
                    settings.BACKGROUND_REMOVAL_URL,
                    files=files,
                    params=params
                )
            elif image_url:
                body = {'image_url': image_url.strip()}
                headers = {'Content-Type': 'application/json'}
                response = await client.post(
                    settings.BACKGROUND_REMOVAL_URL,
                    json=body,
                    headers=headers,
                    params=params
                )
            else:
                body = {'image_file_b64': image_file_b64}
                headers = {'Content-Type': 'application/json'}
                response = await client.post(
                    settings.BACKGROUND_REMOVAL_URL,
                    json=body,
                    headers=headers,
                    params=params
                )

            if response.status_code != 200:
                error_detail = response.json().get('detail', response.text)
                logger.error(f"Worker service error: {error_detail}")
                raise Exception(f"Worker service error: {error_detail}")

            # Create a file-like object from the response content
            file_obj = io.BytesIO(response.content)
            file_obj.seek(0)

            # Return the processed image
            return FileResponse(
                file_obj,
                content_type=response.headers.get('Content-Type', 'application/octet-stream')
            )

    except Exception as e:
        # Log the error for debugging
        logger.error(f"Background removal failed: {str(e)}")
        # Re-raise the exception with a clean error message
        raise Exception(f"Background removal failed: {str(e)}")
