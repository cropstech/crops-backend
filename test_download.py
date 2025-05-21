import requests
import os
import json
import time
import concurrent.futures
from tqdm import tqdm

def bulk_download_example(workspace_id, asset_ids, token, session_id):
    """
    Example code showing how to implement bulk downloads with the new API
    """
    headers = {
        'Content-Type': 'application/json',
        'X-CSRFToken': token,
        'Cookie': f'csrftoken={token}; sessionid={session_id}'
    }
    
    # Step 1: Request presigned URLs for all assets
    print("Requesting presigned URLs for bulk download...")
    url = f"http://localhost:8000/api/workspaces/{workspace_id}/assets/bulk/download"
    response = requests.post(
        url, 
        json={'asset_ids': asset_ids},
        headers=headers
    )
    
    if response.status_code != 200:
        print(f"Error getting download URLs: {response.status_code}")
        print(response.text)
        return False
    
    data = response.json()
    print(f"Got {data['asset_count']} download URLs")
    
    # Step 2: Download all files in parallel
    os.makedirs("downloads", exist_ok=True)
    
    def download_file(download_info):
        try:
            file_name = download_info['name']
            download_url = download_info['download_url']
            file_path = os.path.join("downloads", file_name)
            
            # Download the file
            file_response = requests.get(download_url, stream=True)
            file_response.raise_for_status()
            
            total_size = int(file_response.headers.get('content-length', 0))
            block_size = 8192
            
            with open(file_path, 'wb') as f, tqdm(
                desc=file_name,
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
            ) as progress_bar:
                for chunk in file_response.iter_content(chunk_size=block_size):
                    if chunk:
                        f.write(chunk)
                        progress_bar.update(len(chunk))
                        
            return True, file_name
        except Exception as e:
            print(f"Error downloading {download_info['name']}: {str(e)}")
            return False, download_info['name']
    
    # Use ThreadPoolExecutor to download files in parallel
    print("\nStarting parallel downloads...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for download_info in data['downloads']:
            futures.append(executor.submit(download_file, download_info))
            
        # Process the results
        successful = 0
        failed = 0
        for future in concurrent.futures.as_completed(futures):
            result, file_name = future.result()
            if result:
                successful += 1
            else:
                failed += 1
    
    print(f"\nDownload complete: {successful} successful, {failed} failed")
    return True

# To use this code:
# bulk_download_example(
#    "your-workspace-id", 
#    ["asset-id-1", "asset-id-2"], 
#    "your-csrf-token", 
#    "your-session-id"
# ) 