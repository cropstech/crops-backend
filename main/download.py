import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings
from datetime import datetime, timedelta
import uuid
from typing import List, Optional, Tuple, Dict
import logging
from .models import Asset
import json
from django.utils import timezone

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

# Configure Lambda client
lambda_client = boto3.client(
    'lambda',
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_S3_REGION_NAME
)

class DownloadManager:
    DEFAULT_PART_SIZE = 5 * 1024 * 1024  # 5MB
    URL_EXPIRY = 3600  # 1 hour in seconds
    LAMBDA_FUNCTION_NAME = "s3-zip-creator"  # Name of your Lambda function

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
        expires_at = timezone.now() + timedelta(seconds=cls.URL_EXPIRY)

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

    @classmethod
    def create_zip_archive(cls, assets: List[Asset], zip_name: str = None) -> dict:
        """
        Create a ZIP archive of multiple assets using AWS Lambda
        
        This method invokes a Lambda function that:
        1. Reads the files directly from S3
        2. Creates a ZIP archive
        3. Uploads the ZIP back to S3
        4. Returns a presigned URL to download the ZIP
        
        The Lambda function handles everything server-side, with no local downloads.
        """
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        
        # Generate a unique key for the output ZIP file
        timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        zip_name = zip_name or f"archive-{timestamp}"
        output_key = f"temp/zips/{zip_name}-{uuid.uuid4()}.zip"
        
        # Prepare file list for Lambda
        file_list = []
        for asset in assets:
            key = asset.file.name
            if not key.startswith('media/'):
                key = f'media/{key}'
                
            file_list.append({
                "key": key,
                "filename": asset.name or key.split('/')[-1]  # Use asset name or extract from key
            })
        
        try:
            # Prepare payload for Lambda
            payload = {
                "source_bucket": bucket,
                "output_bucket": bucket,
                "output_key": output_key,
                "files": file_list,
                "generate_presigned_url": True,
                "presigned_url_expiry": cls.URL_EXPIRY
            }
            
            # Invoke Lambda function to create ZIP
            logger.info(f"Invoking Lambda to create ZIP archive of {len(file_list)} files")
            response = lambda_client.invoke(
                FunctionName=cls.LAMBDA_FUNCTION_NAME,
                InvocationType='RequestResponse',  # Synchronous execution
                Payload=json.dumps(payload)
            )
            
            # Parse response
            response_payload = json.loads(response['Payload'].read().decode('utf-8'))
            
            if response['StatusCode'] != 200 or 'error' in response_payload:
                logger.error(f"Lambda ZIP creation failed: {response_payload.get('error', 'Unknown error')}")
                raise Exception(f"Failed to create ZIP: {response_payload.get('error', 'Unknown error')}")
            
            download_url = response_payload.get('presigned_url')
            if not download_url:
                # If Lambda didn't return a presigned URL, generate one
                download_url = cls.get_presigned_url(bucket, output_key)
            
            expires_at = timezone.now() + timedelta(seconds=cls.URL_EXPIRY)
            
            return {
                "download_url": download_url,
                "zip_size": response_payload.get('zip_size', 0),
                "file_count": len(file_list),
                "expires_at": expires_at
            }
            
        except Exception as e:
            logger.error(f"Error creating ZIP archive: {str(e)}")
            raise 