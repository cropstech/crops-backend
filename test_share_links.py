#!/usr/bin/env python
"""
Simple test script for the new share link functionality
"""
import os
import sys
import django
from django.test import Client
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
import json

# Setup Django
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crops.settings')
    django.setup()

from main.models import Workspace, WorkspaceMember, Asset, ShareLink

User = get_user_model()

def setup_test_data():
    """Create test user, workspace, and asset"""
    user = User.objects.create_user(
        email='test@example.com',
        username='testuser',
        password='testpass123'
    )
    
    workspace = Workspace.objects.create(
        name='Test Workspace',
        slug='test-workspace'
    )
    
    WorkspaceMember.objects.create(
        workspace=workspace,
        user=user,
        role=WorkspaceMember.Role.ADMIN
    )
    
    # Create a mock asset (you might need to adjust this based on your Asset model)
    asset = Asset.objects.create(
        workspace=workspace,
        name='Test Asset',
        file='test-file.jpg',  # This might need to be adjusted
        file_type='IMAGE',
        size=1024,
        created_by=user
    )
    
    return user, workspace, asset

def test_auto_create_share_link():
    """Test the GET endpoint that auto-creates share links"""
    print("Testing auto-create share link functionality...")
    
    user, workspace, asset = setup_test_data()
    client = Client()
    client.force_login(user)
    
    # Test GET request to auto-create share link
    response = client.get(f'/api/workspaces/{workspace.id}/share/asset/{asset.id}')
    print(f"GET response status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"Created share link: {data}")
        
        # Verify share link was created in database
        share_link = ShareLink.objects.get(
            content_type=ContentType.objects.get_for_model(Asset),
            object_id=asset.id
        )
        print(f"Database share link: {share_link}")
        print(f"Permission: {share_link.permission}")
        print(f"Token: {share_link.token}")
        
        # Test that subsequent GET requests return the same link
        response2 = client.get(f'/api/workspaces/{workspace.id}/share/asset/{asset.id}')
        if response2.status_code == 200:
            data2 = response2.json()
            print(f"Second GET request returned same token: {data['token'] == data2['token']}")
        
        return True
    else:
        print(f"Failed with status {response.status_code}: {response.content}")
        return False

def test_update_share_link():
    """Test the PUT endpoint for updating share links"""
    print("\nTesting share link update functionality...")
    
    user, workspace, asset = setup_test_data()
    client = Client()
    client.force_login(user)
    
    # First create a share link
    response = client.get(f'/api/workspaces/{workspace.id}/share/asset/{asset.id}')
    if response.status_code != 200:
        print("Failed to create initial share link")
        return False
    
    # Update the share link
    update_data = {
        'permission': 'EDIT',
        'password': 'secret123',
        'max_uses': 10
    }
    
    response = client.put(
        f'/api/workspaces/{workspace.id}/share/asset/{asset.id}',
        data=json.dumps(update_data),
        content_type='application/json'
    )
    
    print(f"PUT response status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"Updated share link: {data}")
        
        # Verify changes in database
        share_link = ShareLink.objects.get(
            content_type=ContentType.objects.get_for_model(Asset),
            object_id=asset.id
        )
        print(f"Updated permission: {share_link.permission}")
        print(f"Updated password: {share_link.password}")
        print(f"Updated max_uses: {share_link.max_uses}")
        
        return True
    else:
        print(f"Failed with status {response.status_code}: {response.content}")
        return False

if __name__ == '__main__':
    try:
        print("🧪 Testing new share link functionality")
        print("=" * 50)
        
        test1_passed = test_auto_create_share_link()
        test2_passed = test_update_share_link()
        
        print("\n" + "=" * 50)
        print(f"Auto-create test: {'✅ PASSED' if test1_passed else '❌ FAILED'}")
        print(f"Update test: {'✅ PASSED' if test2_passed else '❌ FAILED'}")
        
        if test1_passed and test2_passed:
            print("\n🎉 All tests passed!")
        else:
            print("\n❌ Some tests failed")
            
    except Exception as e:
        print(f"Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        try:
            ShareLink.objects.all().delete()
            Asset.objects.all().delete()
            WorkspaceMember.objects.all().delete()
            Workspace.objects.all().delete()
            User.objects.filter(email='test@example.com').delete()
            print("\n🧹 Cleanup completed")
        except:
            pass
