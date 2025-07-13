#!/bin/bash

echo "🚀 Instagram Reel Downloader with Proxy Support"
echo "=============================================="

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 is not installed. Please install Python3 first."
    exit 1
fi

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 is not installed. Please install pip3 first."
    exit 1
fi

# Install requirements if not already installed
echo "📦 Installing requirements..."
pip3 install -r requirements.txt

# Set default proxy configuration
export PROXY_ENABLED=true
export PROXY_TIMEOUT=20
export PROXY_RETRIES=3

# Check if proxy configuration is provided via command line
if [ "$1" = "--proxy" ] && [ ! -z "$2" ]; then
    echo "🔧 Using proxy: $2"
    export PRIMARY_PROXY="$2"
fi

# Check if proxy list is provided
if [ "$1" = "--proxy-list" ] && [ ! -z "$2" ]; then
    echo "🔧 Using proxy list: $2"
    export PROXY_LIST="$2"
fi

# Check if proxy should be disabled
if [ "$1" = "--no-proxy" ]; then
    echo "🚫 Proxy disabled"
    export PROXY_ENABLED=false
fi

# Test proxy connectivity if enabled
if [ "$PROXY_ENABLED" = "true" ]; then
    echo "🔍 Testing proxy connectivity..."
    python3 proxy_config.py
fi

# Start the application
echo "🌟 Starting Instagram Reel Downloader..."
echo "📡 Server will be available at: http://localhost:5000"
echo "🛑 Press Ctrl+C to stop the server"
echo "=============================================="

# Run the application
python3 run_with_proxy.py