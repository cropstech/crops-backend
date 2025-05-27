import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings
from datetime import datetime, timedelta
import uuid
from typing import List, Optional, Dict
import logging
from .models import Asset
import json

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

class UploadManager:
    DEFAULT_PART_SIZE = 5 * 1024 * 1024  # 5MB
    URL_EXPIRY = 3600  # 1 hour in seconds

    @classmethod
    def check_transfer_acceleration(cls) -> bool:
        """Check if Transfer Acceleration is enabled for the bucket"""
        try:
            response = s3_client.get_bucket_accelerate_configuration(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME
            )
            return response.get('Status') == 'Enabled'
        except ClientError as e:
            logger.error(f"Error checking Transfer Acceleration status: {str(e)}")
            return False

    @staticmethod
    def get_presigned_url(bucket: str, key: str, content_type: str = 'application/octet-stream', expires_in: int = URL_EXPIRY) -> str:
        """Generate a presigned URL for S3 object upload"""
        try:
            # Add /media/ prefix to the key if it's not already there
            if not key.startswith('media/'):
                key = f'media/{key}'
                
            url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': bucket,
                    'Key': key,
                    'ContentType': content_type
                },
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            logger.error(f"Error generating presigned URL: {str(e)}")
            raise

    @classmethod
    def initiate_upload(
        cls,
        filename: str,
        content_type: str,
        size: int,
        use_multipart: bool = False,
        part_size: Optional[int] = None,
        s3_key: Optional[str] = None
    ) -> dict:
        """Initiate a file upload, either single or multipart"""
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        
        # Use provided s3_key or generate a default one
        if s3_key:
            key = s3_key
        else:
            key = f"uploads/{uuid.uuid4()}/{filename}"
            
        upload_id = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(seconds=cls.URL_EXPIRY)

        if not use_multipart or size <= cls.DEFAULT_PART_SIZE:
            # Single file upload
            url = cls.get_presigned_url(bucket, key, content_type)
            return {
                'upload_id': upload_id,
                'key': key,
                'direct_url': url,
                'expires_at': expires_at
            }
        else:
            # Multipart upload
            try:
                # Add media/ prefix to key if not present
                if not key.startswith('media/'):
                    key = f'media/{key}'
                
                # Initiate multipart upload
                response = s3_client.create_multipart_upload(
                    Bucket=bucket,
                    Key=key,
                    ContentType=content_type
                )
                upload_id = response['UploadId']

                # Calculate parts
                part_size = part_size or cls.DEFAULT_PART_SIZE
                parts = []
                for i in range(0, size, part_size):
                    end = min(i + part_size - 1, size - 1)
                    part_number = len(parts) + 1
                    
                    # Get presigned URL for this part
                    url = s3_client.generate_presigned_url(
                        'upload_part',
                        Params={
                            'Bucket': bucket,
                            'Key': key,
                            'UploadId': upload_id,
                            'PartNumber': part_number
                        },
                        ExpiresIn=cls.URL_EXPIRY
                    )
                    
                    parts.append({
                        'part_number': part_number,
                        'start_byte': i,
                        'end_byte': end,
                        'url': url,
                        'expires_at': expires_at
                    })

                return {
                    'upload_id': upload_id,
                    'key': key,  # Return the key with media/ prefix
                    'total_parts': len(parts),
                    'parts': parts,
                    'expires_at': expires_at
                }
            except ClientError as e:
                logger.error(f"Error initiating multipart upload: {str(e)}")
                raise

    @classmethod
    def complete_multipart_upload(cls, upload_id: str, key: str, parts: List[Dict]) -> bool:
        """Complete a multipart upload"""
        try:
            # Format parts for AWS S3 API - ensure correct field names
            formatted_parts = []
            for part in parts:
                # Handle different possible field name formats
                part_number = part.get('PartNumber') or part.get('part_number') or part.get('partNumber')
                etag = part.get('ETag') or part.get('etag') or part.get('eTag')
                
                if part_number is None or etag is None:
                    logger.error(f"Invalid part format: {part}")
                    raise ValueError(f"Part missing required fields: {part}")
                
                formatted_parts.append({
                    'PartNumber': int(part_number),
                    'ETag': etag
                })
            
            logger.info(f"Completing multipart upload for key: {key} with {len(formatted_parts)} parts")
            
            s3_client.complete_multipart_upload(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={'Parts': formatted_parts}
            )
            return True
        except ClientError as e:
            logger.error(f"Error completing multipart upload: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error formatting parts for multipart upload: {str(e)}")
            raise

    @classmethod
    def abort_multipart_upload(cls, upload_id: str, key: str) -> bool:
        """Abort a multipart upload"""
        try:
            s3_client.abort_multipart_upload(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=key,
                UploadId=upload_id
            )
            return True
        except ClientError as e:
            logger.error(f"Error aborting multipart upload: {str(e)}")
            raise 