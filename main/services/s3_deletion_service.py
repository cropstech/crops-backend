"""
S3 Asset Deletion Service using Chancy for background processing
"""
import boto3
import logging
from typing import List, Tuple, Dict, Any
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from main.models import Asset

logger = logging.getLogger(__name__)

class S3AssetDeletionService:
    """Service for managing S3 file deletion for assets"""
    
    @staticmethod
    def get_asset_s3_files(asset: Asset) -> Dict[str, List[str]]:
        """
        Get all S3 files associated with an asset.
        Returns a dict with bucket names as keys and lists of S3 keys as values.
        """
        files_by_bucket = {}
        
        # Asset folder path
        base_path = f"media/workspaces/{asset.workspace.id}/assets/{asset.id}/"
        
        # Analysis metadata path
        analysis_path = f"metadata/{asset.id}/"
        
        # S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )
        
        # Check main storage bucket (original files)
        storage_bucket = settings.AWS_STORAGE_BUCKET_NAME
        try:
            response = s3_client.list_objects_v2(
                Bucket=storage_bucket,
                Prefix=base_path
            )
            
            if 'Contents' in response:
                storage_files = [obj['Key'] for obj in response['Contents']]
                if storage_files:
                    files_by_bucket[storage_bucket] = storage_files
                    
        except Exception as e:
            logger.error(f"Error listing files in storage bucket {storage_bucket}: {e}")
        
        # Check CDN bucket (processed files)
        cdn_bucket = settings.AWS_STORAGE_CDN_BUCKET_NAME
        try:
            # Check asset files
            response = s3_client.list_objects_v2(
                Bucket=cdn_bucket,
                Prefix=base_path
            )
            
            cdn_files = []
            if 'Contents' in response:
                cdn_files.extend([obj['Key'] for obj in response['Contents']])
            
            # Check analysis files
            response = s3_client.list_objects_v2(
                Bucket=cdn_bucket,
                Prefix=analysis_path
            )
            
            if 'Contents' in response:
                cdn_files.extend([obj['Key'] for obj in response['Contents']])
                
            if cdn_files:
                files_by_bucket[cdn_bucket] = cdn_files
                
        except Exception as e:
            logger.error(f"Error listing files in CDN bucket {cdn_bucket}: {e}")
        
        return files_by_bucket
    
    @staticmethod
    def delete_s3_files(files_by_bucket: Dict[str, List[str]]) -> Tuple[int, List[str]]:
        """
        Delete S3 files from multiple buckets.
        Returns (deleted_count, failed_files)
        """
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )
        
        deleted_count = 0
        failed_files = []
        
        for bucket, file_keys in files_by_bucket.items():
            for file_key in file_keys:
                try:
                    s3_client.delete_object(Bucket=bucket, Key=file_key)
                    deleted_count += 1
                    logger.info(f"Deleted S3 file: s3://{bucket}/{file_key}")
                    
                except Exception as e:
                    error_msg = f"s3://{bucket}/{file_key}: {str(e)}"
                    failed_files.append(error_msg)
                    logger.error(f"Failed to delete S3 file: {error_msg}")
        
        return deleted_count, failed_files
    
    @staticmethod
    def get_recovery_period_days(workspace) -> int:
        """Get recovery period in days based on workspace plan"""
        try:
            subscription_details = workspace.subscription_details
            plan = subscription_details.get('plan', 'free').lower()
            
            # Recovery periods by plan
            recovery_periods = {
                'free': 7,      # 7 days
                'pro': 30,      # 30 days  
                'enterprise': 90 # 90 days
            }
            
            return recovery_periods.get(plan, 7)  # Default to 7 days
            
        except Exception as e:
            logger.warning(f"Could not determine recovery period for workspace {workspace.id}: {e}")
            return 7  # Default to 7 days


# Chancy job definitions
# Import chancy directly to avoid circular imports
from django.conf import settings
from chancy import Chancy, job

# Create chancy app instance directly
chancy_app = Chancy(settings.DATABASES["default"])

@job()
def delete_asset_s3_files_job(asset_id: str) -> Dict[str, Any]:
    """
    Chancy job to delete all S3 files for an asset.
    This runs in the background after the recovery period expires.
    """
    try:
        asset = Asset.objects.get(id=asset_id)
        
        # Double-check that asset is marked for deletion
        if not asset.deleted_at:
            return {
                'status': 'skipped',
                'message': f'Asset {asset_id} is not marked for deletion'
            }
        
        # Check if already deleted
        if asset.s3_files_deleted:
            return {
                'status': 'already_deleted',
                'message': f'S3 files already deleted for asset {asset_id}'
            }
        
        # Get all S3 files for this asset
        service = S3AssetDeletionService()
        files_by_bucket = service.get_asset_s3_files(asset)
        
        if not files_by_bucket:
            # No files found, mark as deleted
            asset.s3_files_deleted = True
            asset.save()
            return {
                'status': 'no_files',
                'message': f'No S3 files found for asset {asset_id}'
            }
        
        # Delete the files
        deleted_count, failed_files = service.delete_s3_files(files_by_bucket)
        
        # Update asset status
        asset.s3_files_deleted = True
        asset.save()
        
        result = {
            'status': 'completed',
            'asset_id': asset_id,
            'deleted_count': deleted_count,
            'failed_files': failed_files,
            'buckets_processed': list(files_by_bucket.keys())
        }
        
        if failed_files:
            logger.warning(f"Some files failed to delete for asset {asset_id}: {failed_files}")
        else:
            logger.info(f"Successfully deleted all S3 files for asset {asset_id}")
            
        return result
        
    except Asset.DoesNotExist:
        error_msg = f'Asset {asset_id} not found'
        logger.error(error_msg)
        return {
            'status': 'error',
            'message': error_msg
        }
        
    except Exception as e:
        error_msg = f'Failed to delete S3 files for asset {asset_id}: {str(e)}'
        logger.error(error_msg)
        return {
            'status': 'error', 
            'message': error_msg
        }


@job()
def delete_asset_s3_files_immediate(asset_id: str) -> Dict[str, Any]:
    """
    Chancy job for immediate S3 deletion (no recovery period).
    """
    return delete_asset_s3_files_job(asset_id)


def schedule_asset_s3_deletion(asset: Asset, immediate: bool = False) -> 'datetime':
    """
    Schedule S3 deletion for an asset.
    
    Args:
        asset: The asset to schedule deletion for
        immediate: If True, delete immediately. If False, respect recovery period.
        
    Returns:
        datetime: When the S3 deletion will actually execute
    """
    from datetime import datetime, timezone
    
    if immediate:
        # Delete immediately
        chancy_app.sync_push(delete_asset_s3_files_immediate.job.with_kwargs(asset_id=str(asset.id)))
        logger.info(f"Scheduled immediate S3 deletion for asset {asset.id}")
        return datetime.now(timezone.utc)
    else:
        # Schedule for after recovery period
        recovery_days = S3AssetDeletionService.get_recovery_period_days(asset.workspace)
        delay = timedelta(days=recovery_days)
        
        # Use the correct Chancy API for scheduled jobs
        scheduled_at = datetime.now(timezone.utc) + delay
        
        # Create a scheduled job using the correct Chancy API
        scheduled_job = delete_asset_s3_files_job.job.with_scheduled_at(scheduled_at).with_kwargs(asset_id=str(asset.id))
        chancy_app.sync_push(scheduled_job)
        
        logger.info(f"Scheduled S3 deletion for asset {asset.id} in {recovery_days} days")
        return scheduled_at
