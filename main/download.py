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
    region_name=settings.AWS_S3_REGION_NAME,
    config=Config(
        read_timeout=300,  # 5 minutes timeout for Lambda execution
        retries={'max_attempts': 2}
    )
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
    def get_presigned_url_for_zip(bucket: str, key: str, expires_in: int = URL_EXPIRY) -> str:
        """Generate a presigned URL for S3 zip file download (without /media/ prefix)"""
        try:
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': bucket,
                    'Key': key,  # Use key as-is, don't add /media/ prefix
                    'ResponseContentDisposition': f'attachment; filename="{key.split("/")[-1]}"',
                    'ResponseContentType': 'application/zip'
                },
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            logger.error(f"Error generating presigned URL for zip: {str(e)}")
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
        bucket = settings.AWS_STORAGE_CDN_BUCKET_NAME
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
        
        Performance considerations:
        - For 100+ files, consider increasing Lambda memory to 1024MB and timeout to 2-5 minutes
        - Very large requests (500+ files) may benefit from batch processing
        """
        bucket = settings.AWS_STORAGE_CDN_BUCKET_NAME
        
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
            logger.info(f"Lambda payload: {json.dumps(payload, indent=2)}")
            response = lambda_client.invoke(
                FunctionName=cls.LAMBDA_FUNCTION_NAME,
                InvocationType='RequestResponse',  # Synchronous execution
                Payload=json.dumps(payload)
            )
            logger.info(f"Lambda invocation response status: {response['StatusCode']}")
            
            # Parse response
            try:
                response_payload = json.loads(response['Payload'].read().decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.error(f"Failed to parse Lambda response: {str(e)}")
                logger.error(f"Raw response: {response.get('Payload', 'No payload')}")
                raise Exception(f"Lambda returned invalid response, possibly due to timeout or error: {str(e)}")
            
            # Check if response payload is empty (can happen with timeouts)
            if not response_payload:
                logger.error("Lambda returned empty response, likely due to timeout")
                raise Exception("Lambda function failed to return a response, likely due to timeout. Please try with fewer files or increase Lambda timeout.")
            
            # Check for various error conditions
            has_error = (
                response['StatusCode'] != 200 or 
                response_payload.get('status') == 'error' or 
                'error' in response_payload or
                'errorMessage' in response_payload or  # Lambda timeout/error format
                'errorType' in response_payload
            )
            
            if has_error:
                error_msg = response_payload.get('error') or response_payload.get('errorMessage') or f"Lambda returned status: {response['StatusCode']}"
                logger.error(f"Lambda ZIP creation failed: {error_msg}")
                logger.error(f"Full response: {response_payload}")
                
                # Check if this looks like a timeout
                if 'timeout' in error_msg.lower() or 'Task timed out' in error_msg:
                    raise Exception(f"Lambda function timed out while creating ZIP. Please increase Lambda timeout or try with fewer files. Error: {error_msg}")
                else:
                    raise Exception(f"Failed to create ZIP: {error_msg}")
            
            # Verify response contains expected fields
            if 'output_key' not in response_payload:
                logger.error("Lambda response missing output_key field, indicating incomplete execution")
                raise Exception("Lambda function did not complete successfully - missing output information. This often indicates a timeout.")
            
            download_url = response_payload.get('presigned_url')
            zip_size = response_payload.get('zip_size', 0)
            successful_files = response_payload.get('successful_files', 0)
            failed_files = response_payload.get('failed_files', [])
            
            # Verify that the Lambda actually created a zip file
            if zip_size == 0:
                logger.warning(f"Lambda returned zip_size of 0, this might indicate an issue")
                
            # Check if any files were successfully processed
            if successful_files == 0:
                logger.error(f"Lambda processed 0 files successfully. Failed files: {failed_files}")
                raise Exception(f"No files could be added to the ZIP archive. All files failed processing.")
            
            if not download_url:
                # If Lambda didn't return a presigned URL, generate one
                logger.info(f"Lambda didn't return presigned URL, generating one for key: {output_key}")
                download_url = cls.get_presigned_url_for_zip(bucket, output_key)
            else:
                logger.info(f"Lambda returned presigned URL: {download_url}")
            
            expires_at = timezone.now() + timedelta(seconds=cls.URL_EXPIRY)
            
            return {
                "download_url": download_url,
                "zip_size": zip_size,
                "file_count": len(file_list),
                "successful_files": successful_files,
                "failed_files": len(failed_files),
                "expires_at": expires_at
            }
            
        except Exception as e:
            logger.error(f"Error creating ZIP archive: {str(e)}")
            raise

    @classmethod
    def create_zip_archive_with_structure(cls, file_list: List[dict], zip_name: str = None) -> dict:
        """
        Create a ZIP archive from a pre-built file list with folder structure
        
        Args:
            file_list: List of dicts with 'key' (S3 path) and 'filename' (ZIP path)
            zip_name: Optional name for the ZIP file
            
        Returns:
            dict with download_url, expires_at, file_count, and zip_size
        """
        bucket = settings.AWS_STORAGE_CDN_BUCKET_NAME
        
        # Generate a unique key for the output ZIP file
        timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        zip_name = zip_name or f"archive-{timestamp}"
        output_key = f"temp/zips/{zip_name}-{uuid.uuid4()}.zip"
        
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
            logger.info(f"Invoking Lambda to create ZIP archive of {len(file_list)} files with folder structure")
            logger.info(f"Lambda payload: {json.dumps(payload, indent=2)}")
            response = lambda_client.invoke(
                FunctionName=cls.LAMBDA_FUNCTION_NAME,
                InvocationType='RequestResponse',  # Synchronous execution
                Payload=json.dumps(payload)
            )
            logger.info(f"Lambda invocation response status: {response['StatusCode']}")
            
            # Parse response
            try:
                response_payload = json.loads(response['Payload'].read().decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.error(f"Failed to parse Lambda response: {str(e)}")
                logger.error(f"Raw response: {response.get('Payload', 'No payload')}")
                raise Exception(f"Lambda returned invalid response, possibly due to timeout or error: {str(e)}")
            
            # Check if response payload is empty (can happen with timeouts)
            if not response_payload:
                logger.error("Lambda returned empty response, likely due to timeout")
                raise Exception("Lambda function failed to return a response, likely due to timeout. Please try with fewer files or increase Lambda timeout.")
            
            # Check for various error conditions
            if 'errorMessage' in response_payload:
                error_msg = response_payload.get('errorMessage', 'Unknown error')
                logger.error(f"Lambda function error: {error_msg}")
                raise Exception(f"Lambda function failed: {error_msg}")
            
            if response_payload.get('status') != 'success':
                error_msg = response_payload.get('error', 'Unknown error')
                logger.error(f"Lambda function returned error status: {error_msg}")
                raise Exception(f"Failed to create ZIP archive: {error_msg}")
            
            # Extract results
            presigned_url = response_payload.get('presigned_url')
            if not presigned_url:
                logger.error("Lambda response missing presigned_url")
                raise Exception("Failed to generate download URL")
            
            # Calculate expiry time
            expires_at = timezone.now() + timedelta(seconds=cls.URL_EXPIRY)
            
            logger.info(f"Successfully created ZIP archive with {response_payload.get('file_count', 0)} files, size: {response_payload.get('zip_size', 0)} bytes")
            
            return {
                'download_url': presigned_url,
                'file_count': response_payload.get('file_count', len(file_list)),
                'zip_size': response_payload.get('zip_size', 0),
                'expires_at': expires_at
            }
            
        except Exception as e:
            logger.error(f"Error in create_zip_archive_with_structure: {str(e)}")
            raise 