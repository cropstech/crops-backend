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

@router.post("/remove-background", summary="Remove background from image")
async def remove_background(
    request,
    image_file: UploadedFile = File(
        None, 
        description="Image file to remove background from"
    ),
    image_url: str = Form(
        None, 
        description="URL of image to remove background from"
    ),
    image_file_b64: str = Form(
        None, 
        description="Base64 encoded image to remove background from"
    ),
    size: str = Form(
        "preview",
        description="Output image resolution:\n"
        "- preview (default): 0.25 megapixels (e.g., 625×400)\n"
        "- full: Up to 25MP (ZIP/JPG) or 10MP (PNG)\n"
        "- 50MP: Up to 50MP (ZIP/JPG) or 10MP (PNG)\n"
        "- auto: Highest available up to 25MP\n"
        "- medium: Up to 1.5MP (legacy)\n"
        "- hd: Up to 4MP (legacy)"
    ),
    type: str = Form(
        "auto",
        description="Detect or set a foreground type:\n"
        "- auto (default): Automatically detect the type\n"
        "- car: Vehicle detection\n"
        "- product: Product detection\n"
        "- person: Person detection\n"
        "- animal: Animal detection\n"
        "- graphic: Graphic/illustration detection\n"
        "- transportation: Any transportation method"
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
        canonical_size = ImageSize.get_canonical_size(size)
        logger.info(f"Canonical size: {canonical_size}")
        logger.info(f"Foreground type: {type}")

        async with httpx.AsyncClient(timeout=180.0) as client:
            if image_file:
                files = {'image_file': (image_file.name, image_file.file, image_file.content_type)}
                response = await client.post(
                    settings.BACKGROUND_REMOVAL_URL,
                    files=files,
                    params={'size': canonical_size, 'type': type}
                )
            elif image_url:
                body = {'image_url': image_url.strip()}
                headers = {'Content-Type': 'application/json'}
                response = await client.post(
                    settings.BACKGROUND_REMOVAL_URL,
                    json=body,
                    headers=headers,
                    params={'size': canonical_size, 'type': type}
                )
            else:
                body = {'image_file_b64': image_file_b64}
                headers = {'Content-Type': 'application/json'}
                response = await client.post(
                    settings.BACKGROUND_REMOVAL_URL,
                    json=body,
                    headers=headers,
                    params={'size': canonical_size, 'type': type}
                )

            if response.status_code != 200:
                # Parse error response
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
