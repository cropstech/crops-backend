import boto3
import os
import io
import zipfile
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')

def get_file_extension(key):
    """Extract file extension from S3 key or content type"""
    # First try to get extension from the key
    ext = os.path.splitext(key)[1]
    if ext:
        return ext
    
    # If no extension in key, try to determine from content type
    try:
        response = s3_client.head_object(Bucket=source_bucket, Key=key)
        content_type = response.get('ContentType', '')
        if content_type:
            # Map common content types to extensions
            content_type_map = {
                'image/jpeg': '.jpg',
                'image/png': '.png',
                'image/gif': '.gif',
                'application/pdf': '.pdf',
                'text/plain': '.txt',
                'application/msword': '.doc',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
                'application/vnd.ms-excel': '.xls',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx'
            }
            return content_type_map.get(content_type, '')
    except Exception as e:
        logger.warning(f"Could not determine content type for {key}: {str(e)}")
    
    return ''

def lambda_handler(event, context):
    """
    AWS Lambda function to create a ZIP archive from S3 objects
    
    Expected event structure:
    {
        "source_bucket": "your-bucket-name",
        "output_bucket": "your-bucket-name", 
        "output_key": "path/to/output.zip",
        "files": [
            {
                "key": "path/to/file1.jpg",
                "filename": "custom-filename1.jpg"  # Optional, defaults to basename of key
            },
            {
                "key": "path/to/file2.pdf"
                # No filename specified, will use basename of key
            }
        ],
        "generate_presigned_url": true,  # Optional, defaults to false
        "presigned_url_expiry": 3600  # Optional, defaults to 1 hour
    }
    
    Returns:
    {
        "status": "success",
        "output_bucket": "your-bucket-name",
        "output_key": "path/to/output.zip",
        "zip_size": 12345,  # Size in bytes
        "file_count": 10,
        "presigned_url": "https://..."  # Only if generate_presigned_url is true
    }
    """
    try:
        # Extract parameters from event
        source_bucket = event['source_bucket']
        output_bucket = event.get('output_bucket', source_bucket)
        output_key = event['output_key']
        files = event['files']
        generate_url = event.get('generate_presigned_url', False)
        url_expiry = event.get('presigned_url_expiry', 3600)  # Default 1 hour
        
        logger.info(f"Creating ZIP archive in {output_bucket}/{output_key} from {len(files)} files")
        
        # Create in-memory ZIP file
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add each file to the ZIP
            for file_info in files:
                key = file_info['key']
                # Get the file extension
                ext = get_file_extension(key)
                
                # Use provided filename or default to basename of key
                filename = file_info.get('filename', os.path.basename(key))
                
                # Ensure filename has the correct extension
                if not os.path.splitext(filename)[1] and ext:
                    filename = f"{filename}{ext}"
                
                try:
                    # Download file from S3
                    logger.info(f"Adding {key} to ZIP as {filename}")
                    s3_obj = s3_client.get_object(Bucket=source_bucket, Key=key)
                    file_content = s3_obj['Body'].read()
                    
                    # Add to ZIP
                    zip_file.writestr(filename, file_content)
                except Exception as e:
                    logger.error(f"Error adding {key} to ZIP: {str(e)}")
                    # Continue with other files instead of failing completely
                    continue
        
        # Get the ZIP data and size
        zip_data = zip_buffer.getvalue()
        zip_size = len(zip_data)
        
        # Upload ZIP to S3
        logger.info(f"Uploading ZIP ({zip_size} bytes) to {output_bucket}/{output_key}")
        s3_client.put_object(
            Bucket=output_bucket,
            Key=output_key,
            Body=zip_data,
            ContentType='application/zip'
        )
        
        result = {
            "status": "success",
            "output_bucket": output_bucket,
            "output_key": output_key,
            "zip_size": zip_size,
            "file_count": len(files)
        }
        
        # Generate presigned URL if requested
        if generate_url:
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': output_bucket,
                    'Key': output_key,
                    'ResponseContentDisposition': f'attachment; filename="{os.path.basename(output_key)}"',
                    'ResponseContentType': 'application/zip'
                },
                ExpiresIn=url_expiry
            )
            result['presigned_url'] = url
        
        return result
        
    except Exception as e:
        logger.error(f"Error creating ZIP: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        } 