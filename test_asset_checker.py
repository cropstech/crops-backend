"""
Asset Checker Integration Test Script

This script demonstrates how to use the Asset Checker service integration.
It includes examples for starting analysis, checking status, and retrieving results.
"""

import requests
import json
import time
from typing import Dict, Any

class AssetCheckerAPIClient:
    """Simple client for testing Asset Checker API endpoints"""
    
    def __init__(self, base_url: str, auth_token: str = None):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        if auth_token:
            self.session.headers.update({'Authorization': f'Bearer {auth_token}'})
    
    def start_analysis(self, workspace_id: str, asset_id: str, checks_config: Dict[str, Any]) -> Dict:
        """Start asset analysis"""
        url = f"{self.base_url}/api/v1/workspaces/{workspace_id}/assets/{asset_id}/analysis/start"
        payload = {
            "asset_id": asset_id,
            "checks_config": checks_config,
            "use_webhook": True,
            "timeout": 300
        }
        
        response = self.session.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    
    def check_status(self, workspace_id: str, check_id: str) -> Dict:
        """Check analysis status"""
        url = f"{self.base_url}/api/v1/workspaces/{workspace_id}/assets/analysis/{check_id}/status"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
    
    def get_results(self, workspace_id: str, check_id: str) -> Dict:
        """Get analysis results"""
        url = f"{self.base_url}/api/v1/workspaces/{workspace_id}/assets/analysis/{check_id}/results"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
    
    def analyze_sync(self, workspace_id: str, asset_id: str, checks_config: Dict[str, Any]) -> Dict:
        """Perform synchronous analysis"""
        url = f"{self.base_url}/api/v1/workspaces/{workspace_id}/assets/{asset_id}/analysis/sync"
        payload = {
            "asset_id": asset_id,
            "checks_config": checks_config,
            "timeout": 300
        }
        
        response = self.session.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    
    def list_analyses(self, workspace_id: str, asset_id: str) -> Dict:
        """List all analyses for an asset"""
        url = f"{self.base_url}/api/v1/workspaces/{workspace_id}/assets/{asset_id}/analyses"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()


def example_checks_config() -> Dict[str, Any]:
    """Example configuration for various analysis checks"""
    return {
        "spelling_grammar": {
            "language": "en",
            "check_spelling": True,
            "check_grammar": True
        },
        "color_contrast": {
            "wcag_level": "AA"
        },
        "image_quality": {
            "min_resolution": 1920,
            "check_compression": True
        },
        "image_artifacts": {
            "sensitivity": "medium"
        }
    }


def test_async_analysis():
    """Test asynchronous analysis workflow"""
    print("🔍 Testing Asynchronous Asset Analysis")
    print("=" * 50)
    
    # Initialize client
    client = AssetCheckerAPIClient("https://your-api-domain.com")
    
    # Sample IDs (replace with real ones)
    workspace_id = "your-workspace-uuid"
    asset_id = "your-asset-uuid"
    
    try:
        # 1. Start analysis
        print("1. Starting analysis...")
        checks_config = example_checks_config()
        result = client.start_analysis(workspace_id, asset_id, checks_config)
        
        check_id = result['check_id']
        print(f"   ✅ Analysis started with ID: {check_id}")
        print(f"   📊 Status: {result['status']}")
        print(f"   🔗 Webhook URL: {result.get('webhook_url', 'N/A')}")
        
        # 2. Poll for status
        print("\n2. Checking status...")
        max_attempts = 10
        for attempt in range(max_attempts):
            status_result = client.check_status(workspace_id, check_id)
            status = status_result['status']
            progress = status_result.get('progress', 0)
            
            print(f"   Attempt {attempt + 1}: {status} ({progress}%)")
            
            if status in ['completed', 'failed']:
                break
                
            time.sleep(5)  # Wait 5 seconds between checks
        
        # 3. Get results if completed
        if status == 'completed':
            print("\n3. Retrieving results...")
            results = client.get_results(workspace_id, check_id)
            print(f"   ✅ Results retrieved successfully")
            print(f"   📊 Status: {results['status']}")
            print(f"   🎯 Has Results: {bool(results.get('results'))}")
        else:
            print(f"\n❌ Analysis failed or timed out: {status}")
    
    except requests.exceptions.RequestException as e:
        print(f"❌ API Error: {e}")
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")


def test_sync_analysis():
    """Test synchronous analysis"""
    print("\n🚀 Testing Synchronous Asset Analysis")
    print("=" * 50)
    
    client = AssetCheckerAPIClient("https://your-api-domain.com")
    
    workspace_id = "your-workspace-uuid"
    asset_id = "your-asset-uuid"
    
    try:
        print("Starting synchronous analysis...")
        checks_config = {
            "spelling_grammar": {"language": "en"},
            "color_contrast": {"wcag_level": "AA"}
        }
        
        results = client.analyze_sync(workspace_id, asset_id, checks_config)
        
        print("✅ Synchronous analysis completed!")
        print(f"📊 Status: {results['status']}")
        print(f"🎯 Check ID: {results['check_id']}")
        
        # Print sample results
        if results.get('results'):
            print("\n📋 Sample Results:")
            for check_type, check_results in results['results'].items():
                print(f"   {check_type}: {len(check_results) if isinstance(check_results, list) else 'Available'}")
    
    except requests.exceptions.RequestException as e:
        print(f"❌ API Error: {e}")
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")


def test_list_analyses():
    """Test listing asset analyses"""
    print("\n📋 Testing List Asset Analyses")
    print("=" * 50)
    
    client = AssetCheckerAPIClient("https://your-api-domain.com")
    
    workspace_id = "your-workspace-uuid"
    asset_id = "your-asset-uuid"
    
    try:
        analyses = client.list_analyses(workspace_id, asset_id)
        
        print(f"✅ Found {len(analyses)} analyses for asset")
        
        for i, analysis in enumerate(analyses[:3], 1):  # Show first 3
            print(f"\n   Analysis {i}:")
            print(f"      Check ID: {analysis['check_id']}")
            print(f"      Status: {analysis['status']}")
            print(f"      Created: {analysis['created_at']}")
            print(f"      Has Results: {analysis['has_results']}")
    
    except requests.exceptions.RequestException as e:
        print(f"❌ API Error: {e}")
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")


if __name__ == "__main__":
    print("Asset Checker Integration Test")
    print("=" * 60)
    print("\n⚠️  Note: Update the workspace_id and asset_id variables")
    print("    with real values before running this test.\n")
    
    # Run tests
    test_async_analysis()
    test_sync_analysis()
    test_list_analyses()
    
    print("\n" + "=" * 60)
    print("🎉 Test script completed!")
    print("\nNext steps:")
    print("1. Update API URLs and credentials")
    print("2. Replace sample UUIDs with real workspace/asset IDs")
    print("3. Configure Asset Checker Lambda service")
    print("4. Test with real asset files") 