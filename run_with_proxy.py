#!/usr/bin/env python3
"""
Run Instagram Reel Downloader with Proxy Configuration
"""

import os
import sys
import subprocess
from proxy_config import get_proxy_config, test_proxy_connectivity

def setup_environment():
    """Set up environment variables for proxy configuration"""
    config = get_proxy_config()
    
    # Set environment variables
    os.environ['PROXY_ENABLED'] = str(config['enabled']).lower()
    
    if config['primary_proxy']:
        os.environ['PRIMARY_PROXY'] = config['primary_proxy']
    
    if config['fallback_proxies']:
        os.environ['PROXY_LIST'] = ','.join(config['fallback_proxies'])
    
    os.environ['PROXY_TIMEOUT'] = str(config['timeout'])
    os.environ['PROXY_RETRIES'] = str(config['retries'])
    
    print("✓ Environment variables set")

def check_requirements():
    """Check if all required packages are installed"""
    try:
        import flask
        import flask_cors
        import yt_dlp
        import requests
        print("✓ All required packages are installed")
        return True
    except ImportError as e:
        print(f"✗ Missing required package: {e}")
        print("Installing requirements...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        return True

def run_app():
    """Run the Flask application"""
    print("\n🚀 Starting Instagram Reel Downloader with Proxy Support...")
    print("=" * 60)
    
    # Set up environment
    setup_environment()
    
    # Check requirements
    check_requirements()
    
    # Test proxy connectivity (optional)
    test_choice = input("\nDo you want to test proxy connectivity first? (y/n): ").lower()
    if test_choice in ['y', 'yes']:
        print("\n🔍 Testing proxy connectivity...")
        working_proxies = test_proxy_connectivity()
        
        if not working_proxies:
            print("⚠️  No working proxies found. The app will run without proxy support.")
            os.environ['PROXY_ENABLED'] = 'false'
        else:
            print(f"✓ Found {len(working_proxies)} working proxies")
    
    # Run the app
    print("\n🌟 Starting the application...")
    print("API will be available at: http://localhost:5000")
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    
    try:
        # Import and run the app
        from Backend import app
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=True
        )
    except KeyboardInterrupt:
        print("\n👋 Shutting down the server...")
    except Exception as e:
        print(f"❌ Error running the app: {e}")

if __name__ == '__main__':
    run_app()