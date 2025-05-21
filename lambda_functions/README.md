# S3 ZIP Creator Lambda Function

This AWS Lambda function creates ZIP archives from multiple S3 objects without downloading them to your application server. It's used by the Vorset application for bulk asset downloads.

## Features

- Create ZIP archives from multiple S3 objects
- All processing happens within AWS infrastructure
- Support for custom filenames in the ZIP archive
- Generates presigned URLs for the resulting ZIP file
- Handles S3 Transfer Acceleration

## Setup Instructions

### 1. Create the Lambda Function

1. Go to AWS Lambda console and click "Create function"
2. Choose "Author from scratch"
3. Set the following options:
   - **Function name**: `s3-zip-creator`
   - **Runtime**: Python 3.9
   - **Architecture**: x86_64
   - **Permissions**: Create a new role with basic Lambda permissions

4. Click "Create function"

### 2. Configure the Lambda Function

1. In the "Code" tab, replace the default code with the contents of `s3_zip_creator.py`
2. Set the following configuration:
   - **Timeout**: 5 minutes (300 seconds)
   - **Memory**: 512 MB (increase if needed for larger ZIP files)

### 3. Set Up IAM Permissions

Add the following permissions to the Lambda execution role:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::your-bucket-name",
                "arn:aws:s3:::your-bucket-name/*"
            ]
        }
    ]
}
```

Replace `your-bucket-name` with your actual S3 bucket name.

### 4. Test the Lambda Function

Create a test event with the following JSON:

```json
{
  "source_bucket": "your-bucket-name",
  "output_bucket": "your-bucket-name",
  "output_key": "temp/test-zip-output.zip",
  "files": [
    {
      "key": "path/to/file1.jpg",
      "filename": "my-file1.jpg"
    },
    {
      "key": "path/to/file2.pdf"
    }
  ],
  "generate_presigned_url": true,
  "presigned_url_expiry": 3600
}
```

Click "Test" to run the function and verify it works correctly.

## Integration with Vorset

The Lambda function is called from the `DownloadManager.create_zip_archive` method in `main/download.py`. Make sure the function name in the code matches the name of your Lambda function.

## Troubleshooting

If the function fails with memory or timeout errors, increase the memory allocation and timeout duration in the Lambda configuration.

For larger ZIP files (>100MB), you may need to:

1. Increase the Lambda timeout to the maximum (15 minutes)
2. Consider using S3 multipart uploads for the output ZIP file
3. For extremely large archives, switch to a step function or specialized service 