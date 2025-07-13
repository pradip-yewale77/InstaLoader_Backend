#!/usr/bin/env python3
"""
Test script for Instagram Reel Downloader with Proxy Support
"""

import requests
import json
import time
import sys

BASE_URL = "http://localhost:5000"

def test_health():
    """Test health endpoint"""
    print("🏥 Testing health endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Health check passed")
            print(f"  - Status: {data['status']}")
            print(f"  - Proxy enabled: {data['proxy_config']['enabled']}")
            print(f"  - Proxies available: {data['proxy_config']['proxies_available']}")
            return True
        else:
            print(f"✗ Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        return False

def test_proxy_config():
    """Test proxy configuration endpoint"""
    print("\n⚙️  Testing proxy configuration...")
    try:
        response = requests.get(f"{BASE_URL}/proxy-config")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Proxy config retrieved")
            print(f"  - Proxy enabled: {data['proxy_enabled']}")
            print(f"  - Primary proxy: {data['primary_proxy']}")
            print(f"  - Fallback proxies: {data['fallback_proxies_count']}")
            return True
        else:
            print(f"✗ Proxy config failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Proxy config failed: {e}")
        return False

def test_proxy_connectivity():
    """Test proxy connectivity"""
    print("\n🔍 Testing proxy connectivity...")
    try:
        response = requests.post(f"{BASE_URL}/test-proxy", json={})
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Proxy test passed")
            print(f"  - Status: {data['status']}")
            print(f"  - Proxy URL: {data['proxy_url']}")
            print(f"  - Response time: {data['response_time']:.2f}s")
            if 'response' in data and 'origin' in data['response']:
                print(f"  - IP: {data['response']['origin']}")
            return True
        else:
            data = response.json()
            print(f"✗ Proxy test failed: {data.get('error', 'Unknown error')}")
            return False
    except Exception as e:
        print(f"✗ Proxy test failed: {e}")
        return False

def test_instagram_reel(url):
    """Test Instagram reel download with proxy"""
    print(f"\n📸 Testing Instagram reel: {url}")
    
    # Test thumbnail fetch
    print("  Getting thumbnail...")
    try:
        response = requests.post(f"{BASE_URL}/get-reel-thumbnail", json={
            "url": url
        })
        if response.status_code == 200:
            data = response.json()
            print(f"  ✓ Thumbnail fetched")
            print(f"    - Title: {data.get('title', 'N/A')}")
            print(f"    - Uploader: {data.get('uploader', 'N/A')}")
            print(f"    - Duration: {data.get('duration', 0)}s")
            print(f"    - Proxy used: {data.get('proxy_used', False)}")
            return True
        else:
            print(f"  ✗ Thumbnail failed: {response.status_code}")
            if response.headers.get('content-type') == 'application/json':
                error = response.json().get('error', 'Unknown error')
                print(f"    Error: {error}")
            return False
    except Exception as e:
        print(f"  ✗ Thumbnail failed: {e}")
        return False

def test_reel_info(url):
    """Test reel info endpoint"""
    print(f"\n📝 Testing reel info: {url}")
    try:
        response = requests.post(f"{BASE_URL}/get-reel-info", json={
            "url": url
        })
        if response.status_code == 200:
            data = response.json()
            print(f"  ✓ Reel info retrieved")
            print(f"    - ID: {data.get('id', 'N/A')}")
            print(f"    - Title: {data.get('title', 'N/A')}")
            print(f"    - Duration: {data.get('duration', 0)}s")
            print(f"    - Formats available: {len(data.get('formats', []))}")
            return True
        else:
            print(f"  ✗ Reel info failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"  ✗ Reel info failed: {e}")
        return False

def update_proxy_config():
    """Test updating proxy configuration"""
    print("\n🔧 Testing proxy configuration update...")
    try:
        # Update proxy config
        response = requests.post(f"{BASE_URL}/proxy-config", json={
            "enabled": True,
            "primary_proxy": "http://test-proxy:8080"
        })
        if response.status_code == 200:
            print("  ✓ Proxy configuration updated")
            return True
        else:
            print(f"  ✗ Proxy config update failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"  ✗ Proxy config update failed: {e}")
        return False

def main():
    """Main test function"""
    print("🧪 Instagram Reel Downloader Proxy Test Suite")
    print("=" * 50)
    
    # Check if server is running
    print("📡 Checking if server is running...")
    try:
        response = requests.get(BASE_URL, timeout=5)
        if response.status_code == 200:
            print("✓ Server is running")
        else:
            print("✗ Server is not responding properly")
            sys.exit(1)
    except requests.ConnectionError:
        print("✗ Server is not running. Please start the server first:")
        print("   python run_with_proxy.py")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Server check failed: {e}")
        sys.exit(1)
    
    # Run tests
    tests = [
        test_health,
        test_proxy_config,
        test_proxy_connectivity,
        update_proxy_config
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        time.sleep(1)  # Brief delay between tests
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    # Test with sample Instagram reel (if provided)
    if len(sys.argv) > 1:
        instagram_url = sys.argv[1]
        print(f"\n🎯 Testing with Instagram URL: {instagram_url}")
        
        instagram_tests = [
            lambda: test_instagram_reel(instagram_url),
            lambda: test_reel_info(instagram_url)
        ]
        
        instagram_passed = 0
        for test in instagram_tests:
            if test():
                instagram_passed += 1
            time.sleep(2)  # Delay between Instagram requests
        
        print(f"Instagram Tests: {instagram_passed}/{len(instagram_tests)} passed")
    else:
        print("\n💡 Tip: Run with Instagram URL to test downloading:")
        print("   python test_proxy.py https://www.instagram.com/reel/ABC123/")
    
    print("\n🎉 Testing complete!")

if __name__ == '__main__':
    main()