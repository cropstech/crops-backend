from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.http import JsonResponse
import os
import mimetypes
from PIL import Image
from datetime import datetime
import filetype
from pydantic import BaseModel
from typing import Optional, Dict, Tuple
import mutagen
from django.core.files.uploadedfile import UploadedFile
from django.contrib.auth import get_user_model
from ninja import Schema
from typing import Optional
import asyncio
from django.core.files.storage import default_storage, storages
from concurrent.futures import ThreadPoolExecutor
from main.models import Asset
from uuid import UUID
from tempfile import NamedTemporaryFile
import logging
from django.utils import timezone
from ninja.errors import HttpError
from django.shortcuts import get_object_or_404
from .models import WorkspaceInvitation, WorkspaceMember
import PIL.Image
import os
from dicebear import DAvatar, DStyle, DOptions, DColor, DFormat, bulk_create
from django.core.files.base import ContentFile
import io
import uuid


logger = logging.getLogger(__name__)

class FileMetadata(Schema):
    name: str
    file_type: str
    mime_type: str
    file_extension: str
    size: int
    dimensions: Optional[tuple[int, int]]
    duration: Optional[float]
    date_created: Optional[datetime]
    metadata: dict

def send_invitation_email(invitation):
    """
    Send workspace invitation email
    """
    subject = f"You've been invited to join {invitation.workspace.name}"
    
    context = {
        'workspace_name': invitation.workspace.name,
        'invited_by': invitation.invited_by.get_full_name() or invitation.invited_by.email,
        'role': invitation.get_role_display(),
        'accept_url': f"{settings.FRONTEND_URL}/invite/{invitation.token}",
        'expires_at': invitation.expires_at,
    }
    
    # You can create an HTML email template at templates/emails/workspace_invitation.html
    html_message = render_to_string('emails/workspace_invitation.html', context)
    plain_message = f"""
    You've been invited to join {invitation.workspace.name} by {invitation.invited_by.get_full_name() or invitation.invited_by.email}.
    Role: {invitation.get_role_display()}
    Click here to accept: {settings.FRONTEND_URL}/invite/{invitation.token}
    This invitation expires on {invitation.expires_at}
    """
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        # Log the error
        print(f"Failed to send invitation email: {e}")
        return False

def create_error_response(message, status=403):
    return JsonResponse(
        {"detail": message},
        status=status
    )

def clean_metadata_for_json(value):
    """
    Recursively clean metadata to ensure JSON serialization works
    """
    if isinstance(value, dict):
        return {k: clean_metadata_for_json(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [clean_metadata_for_json(v) for v in value]
    elif hasattr(value, 'numerator') and hasattr(value, 'denominator'):
        # Handle IFDRational and similar fraction types
        return float(value.numerator) / float(value.denominator)
    elif hasattr(value, '_getexif'):
        # Handle EXIF data
        return clean_metadata_for_json(value._getexif())
    elif isinstance(value, (int, float, str, bool)) or value is None:
        return value
    else:
        # Convert any other types to strings
        return str(value)

def process_file_metadata(file_or_path, user) -> FileMetadata:
    """
    Extract comprehensive metadata from an uploaded file or file path
    """
    # Handle both string paths and UploadedFile objects
    if isinstance(file_or_path, str):
        filename = os.path.basename(file_or_path)
        file_size = os.path.getsize(file_or_path)
        # Open the file for reading
        file = open(file_or_path, 'rb')
    else:
        filename = file_or_path.name
        file_size = file_or_path.size
        file = file_or_path

    try:
        # Basic file info
        name, ext = os.path.splitext(filename)
        file_extension = ext.lower().lstrip('.')
        
        # Get MIME type using filetype
        kind = filetype.guess(file.read(2048))
        mime_type = kind.mime if kind else mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        file.seek(0)  # Reset file pointer
        
        # Initialize metadata dict for additional info
        metadata = {}
        dimensions = None
        duration = None
        
        # Determine file type and extract specific metadata
        if mime_type.startswith('image/'):
            file_type = 'IMAGE'
            try:
                with Image.open(file) as img:
                    dimensions = img.size
                    metadata.update({
                        'format': img.format,
                        'mode': img.mode,
                        'is_animated': getattr(img, 'is_animated', False),
                        'n_frames': getattr(img, 'n_frames', 1),
                        'dpi': img.info.get('dpi'),
                        'exif': clean_metadata_for_json(img._getexif()) if hasattr(img, '_getexif') and img._getexif() else None
                    })
            except Exception as e:
                metadata['error'] = str(e)
                
        elif mime_type.startswith('video/'):
            file_type = 'VIDEO'
            try:
                video = mutagen.File(file_or_path if isinstance(file_or_path, str) else file_or_path.temporary_file_path())
                if video:
                    duration = video.info.length if hasattr(video.info, 'length') else None
                    metadata.update({
                        'bitrate': getattr(video.info, 'bitrate', None),
                        'fps': getattr(video.info, 'fps', None),
                        'codec': getattr(video.info, 'codec', None)
                    })
            except Exception as e:
                metadata['error'] = str(e)
                
        elif mime_type.startswith('audio/'):
            file_type = 'AUDIO'
            try:
                audio = mutagen.File(file_or_path if isinstance(file_or_path, str) else file_or_path.temporary_file_path())
                if audio:
                    duration = audio.info.length if hasattr(audio.info, 'length') else None
                    metadata.update({
                        'bitrate': getattr(audio.info, 'bitrate', None),
                        'channels': getattr(audio.info, 'channels', None),
                        'sample_rate': getattr(audio.info, 'sample_rate', None),
                        'tags': dict(audio.tags) if hasattr(audio, 'tags') and audio.tags else {}
                    })
            except Exception as e:
                metadata['error'] = str(e)
                
        else:
            file_type = 'OTHER'

        # Try to get file creation date
        try:
            if isinstance(file_or_path, str):
                date_created = datetime.fromtimestamp(os.path.getctime(file_or_path))
            else:
                date_created = datetime.fromtimestamp(os.path.getctime(file_or_path.temporary_file_path()))
        except:
            date_created = timezone.now()

        # Clean all metadata before returning
        metadata = clean_metadata_for_json(metadata)
        
        return FileMetadata(
            name=name,
            file_type=file_type,
            mime_type=mime_type,
            file_extension=file_extension,
            size=file_size,
            dimensions=dimensions,
            duration=duration,
            date_created=date_created,
            metadata=metadata
        )
    finally:
        # Close the file if we opened it
        if isinstance(file_or_path, str):
            file.close()

def process_file_metadata_background(asset_id: UUID, file_path: str, user) -> None:
    """
    Background processing function for S3-stored files
    """
    try:
        asset = Asset.objects.get(id=asset_id)
        
        # Create a temporary file to process the metadata
        with default_storage.open(file_path, 'rb') as remote_file:
            # Create a temporary file
            with NamedTemporaryFile(delete=False) as temp_file:
                # Copy the remote file to a temporary local file
                temp_file.write(remote_file.read())
                temp_file.flush()
                
                # Process the metadata using the temporary file
                file_metadata = process_file_metadata(temp_file.name, user)
            
            # Clean up the temporary file
            os.unlink(temp_file.name)
        
        # Update asset with metadata
        asset.file_type = file_metadata.file_type
        asset.mime_type = file_metadata.mime_type
        asset.file_extension = file_metadata.file_extension
        
        if file_metadata.dimensions:
            asset.width = file_metadata.dimensions[0]
            asset.height = file_metadata.dimensions[1]
        
        asset.duration = file_metadata.duration
        asset.metadata = file_metadata.metadata
        asset.status = Asset.Status.COMPLETED
        
        asset.save()
        
    except Exception as e:
        logger.exception(f"Error processing file metadata for asset {asset_id}: {str(e)}")
        asset = Asset.objects.get(id=asset_id)
        asset.status = Asset.Status.FAILED
        asset.processing_error = str(e)
        asset.save()

# Create a thread pool executor
executor = ThreadPoolExecutor(max_workers=3)

def accept_invitation(token, user):
    invitation = get_object_or_404(WorkspaceInvitation, token=token)
    
    if invitation.status != 'PENDING':
        raise HttpError(400, "This invitation has already been used or expired")
    
    if invitation.expires_at < timezone.now():
        invitation.status = 'EXPIRED'
        invitation.save()
        raise HttpError(400, "This invitation has expired")
    
    if WorkspaceMember.objects.filter(workspace=invitation.workspace, user=user).exists():
        raise HttpError(400, "You are already a member of this workspace")
    
    WorkspaceMember.objects.create(
        workspace=invitation.workspace,
        user=user,
        role=invitation.role,
        invited_by=invitation.invited_by
    )
    
    invitation.status = 'ACCEPTED'
    invitation.save()
    return invitation

def quick_file_metadata(file_or_path) -> FileMetadata:
    """
    Quickly extract basic metadata from an uploaded file
    Only gets essential info needed at upload time
    More intensive processing is handled later by Lambda
    """
    # Handle both string paths and UploadedFile objects
    if isinstance(file_or_path, str):
        filename = os.path.basename(file_or_path)
        file_size = os.path.getsize(file_or_path)
        file = open(file_or_path, 'rb')
    else:
        filename = file_or_path.name
        file_size = file_or_path.size
        file = file_or_path

    try:
        # Basic file info
        name, ext = os.path.splitext(filename)
        file_extension = ext.lower().lstrip('.')
        
        # Quick MIME type check - only read first 2048 bytes
        kind = filetype.guess(file.read(2048))
        mime_type = kind.mime if kind else mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        file.seek(0)
        
        dimensions = None
        file_type = 'OTHER'
        
        # Only do quick image dimensions check for images
        if mime_type.startswith('image/'):
            file_type = 'IMAGE'
            try:
                # PIL's open doesn't read the whole file immediately
                with Image.open(file) as img:
                    dimensions = img.size
            except Exception:
                pass
        elif mime_type.startswith('video/'):
            file_type = 'VIDEO'
        elif mime_type.startswith('audio/'):
            file_type = 'AUDIO'

        return FileMetadata(
            name=name,
            file_type=file_type,
            mime_type=mime_type,
            file_extension=file_extension,
            size=file_size,
            dimensions=dimensions,
            duration=None,  # Let Lambda handle this
            date_created=timezone.now(),  # Simple current timestamp
            metadata={}  # Let Lambda handle detailed metadata
        )
    finally:
        if isinstance(file_or_path, str):
            file.close()

def generate_workspace_avatar(size=200):
    """
    Generate a colorful geometric avatar using DiceBear.
    This provides consistent, high-quality avatars with good color variety.
    """
    # Create a unique seed for the avatar
    seed = str(uuid.uuid4())
    
    # Create avatar with shapes style
    av = DAvatar(
        style=DStyle.shapes,
        seed=seed,
        options=DOptions(
            size=size,
            backgroundColor=DColor("073b4c"),
        )
    )
    
    try:
        # Editing the style specific customisations
        av.customise(
            blank_options={
                "shape1Color": "ef476f",
                "shape2Color": "06d6a0",
                "shape3Color": "ffd166"
            }
        )
        # Save directly as PNG
        av.save(
            location=None,  # Current directory
            file_name=f"{seed}",
            file_format=DFormat.png,
            overwrite=True,
            open_after_save=False
        )
        
        # Read the saved file
        with open(f"{seed}.png", 'rb') as f:
            image_data = f.read()
            
        # Clean up the temporary file
        os.remove(f"{seed}.png")
        
        # Create a ContentFile from the image data
        return ContentFile(image_data, name=f'{seed}.png')
        
    except Exception as e:
        logger.error(f"Error generating avatar: {str(e)}")
        # Fallback to a simple colored square if generation fails
        image = Image.new('RGB', (size, size), '#E0E0E0')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        return ContentFile(buffer.getvalue(), name=f'{seed}.png')
