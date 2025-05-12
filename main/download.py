import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings
from datetime import datetime, timedelta
import uuid
from typing import List, Optional, Tuple
import logging
from .models import Asset

logger = logging.getLogger(__name__)

# Configure S3 client with Transfer Acceleration
s3_client = boto3.client(
    's3',
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_S3_REGION_NAME,
    config=Config(
        s3={'use_accelerate_endpoint': True},
        retries={'max_attempts': 3}
    )
)

class DownloadManager:
    DEFAULT_PART_SIZE = 5 * 1024 * 1024  # 5MB
    URL_EXPIRY = 3600  # 1 hour in seconds

    @staticmethod
    def get_presigned_url(bucket: str, key: str, expires_in: int = URL_EXPIRY) -> str:
        """Generate a presigned URL for S3 object download"""
        try:
            # Add /media/ prefix to the key if it's not already there
            if not key.startswith('media/'):
                key = f'media/{key}'
                
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': bucket,
                    'Key': key,
                    'ResponseContentDisposition': f'attachment; filename="{key.split("/")[-1]}"',
                    'ResponseContentType': 'application/octet-stream'
                },
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            logger.error(f"Error generating presigned URL: {str(e)}")
            raise

    @staticmethod
    def get_presigned_url_for_range(
        bucket: str,
        key: str,
        start_byte: int,
        end_byte: int,
        expires_in: int = URL_EXPIRY
    ) -> str:
        """Generate a presigned URL for a specific byte range of an S3 object"""
        try:
            # Add /media/ prefix to the key if it's not already there
            if not key.startswith('media/'):
                key = f'media/{key}'
                
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': bucket,
                    'Key': key,
                    'Range': f'bytes={start_byte}-{end_byte}',
                    'ResponseContentDisposition': f'attachment; filename="{key.split("/")[-1]}"',
                    'ResponseContentType': 'application/octet-stream'
                },
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            logger.error(f"Error generating presigned URL for range: {str(e)}")
            raise

    @staticmethod
    def calculate_parts(
        total_size: int,
        part_size: Optional[int] = None
    ) -> List[Tuple[int, int]]:
        """Calculate byte ranges for multipart download"""
        if part_size is None:
            part_size = DownloadManager.DEFAULT_PART_SIZE

        parts = []
        for start in range(0, total_size, part_size):
            end = min(start + part_size - 1, total_size - 1)
            parts.append((start, end))
        return parts

    @classmethod
    def initiate_download(
        cls,
        asset: Asset,
        use_multipart: bool = False,
        part_size: Optional[int] = None
    ) -> dict:
        """Initiate a file download, either single or multipart"""
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        key = asset.file.name
        total_size = asset.size
        download_id = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(seconds=cls.URL_EXPIRY)

        if not use_multipart or total_size <= cls.DEFAULT_PART_SIZE:
            # Single file download
            url = cls.get_presigned_url(bucket, key)
            return {
                'download_id': download_id,
                'asset_id': asset.id,
                'total_size': total_size,
                'direct_url': url,
                'expires_at': expires_at
            }
        else:
            # Multipart download
            parts = cls.calculate_parts(total_size, part_size)
            download_parts = []
            
            for i, (start, end) in enumerate(parts, 1):
                url = cls.get_presigned_url_for_range(bucket, key, start, end)
                download_parts.append({
                    'part_number': i,
                    'start_byte': start,
                    'end_byte': end,
                    'url': url,
                    'expires_at': expires_at
                })

            return {
                'download_id': download_id,
                'asset_id': asset.id,
                'total_size': total_size,
                'total_parts': len(parts),
                'parts': download_parts,
                'expires_at': expires_at
            } 