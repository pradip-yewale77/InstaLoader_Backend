from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import shutil
import uuid
import base64
import requests
from threading import Thread, Lock
from time import sleep
import random
import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from functools import lru_cache
import re
import json
import ssl
import urllib3

app = Flask(__name__)
CORS(app)

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DOWNLOAD_DIR = "temp_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Global variables for performance
working_proxies = []
proxy_lock = Lock()
last_proxy_update = 0
PROXY_UPDATE_INTERVAL = 300  # 5 minutes

def fetch_proxies_from_api():
    """Fetch fresh proxies from multiple sources"""
    all_proxies = []
    
    # Source 1: ProxyScrape API
    try:
        url = "https://api.proxyscrape.com/v2/?request=get&protocol=http,socks4,socks5&timeout=3000&country=all&ssl=all&anonymity=all"
        response = requests.get(url, timeout=10, verify=False)
        if response.status_code == 200:
            proxies = response.text.strip().split('\n')
            for proxy in proxies:
                if ':' in proxy:
                    ip, port = proxy.split(':')
                    all_proxies.append(f"http://{ip}:{port}")
                    all_proxies.append(f"socks5://{ip}:{port}")
        print(f"[INFO] Fetched {len(proxies)} proxies from ProxyScrape")
    except Exception as e:
        print(f"[ERROR] ProxyScrape failed: {e}")
    
    # Source 2: Free Proxy List API
    try:
        url = "https://www.proxy-list.download/api/v1/get?type=http"
        response = requests.get(url, timeout=10, verify=False)
        if response.status_code == 200:
            proxies = response.text.strip().split('\n')
            for proxy in proxies:
                if ':' in proxy:
                    all_proxies.append(f"http://{proxy}")
        print(f"[INFO] Fetched {len(proxies)} HTTP proxies from proxy-list.download")
    except Exception as e:
        print(f"[ERROR] proxy-list.download failed: {e}")
    
    # Source 3: Hardcoded fast proxies as fallback
    fallback_proxies = [
        "http://47.74.152.29:8888",
        "http://103.149.162.194:80",
        "http://185.15.172.212:3128",
        "http://103.145.185.123:8080",
        "http://200.123.3.54:3128",
        "http://185.38.111.1:8080",
        "http://103.216.207.15:8080",
        "socks5://184.178.172.3:4145",
        "socks5://72.210.221.197:4145",
        "socks5://98.162.25.4:31653",
        "socks5://184.178.172.25:15291",
        "socks5://72.195.34.35:27360",
        "socks5://98.162.25.23:4145",
        "socks5://72.210.252.134:46164",
        "socks5://98.162.25.7:31653",
        "socks5://98.162.25.29:31679",
        "socks5://192.252.215.5:16137",
        # Additional reliable proxies
        "http://20.206.106.192:8123",
        "http://103.241.227.108:6666",
        "http://185.189.199.75:23500",
        "http://51.158.68.133:8811",
        "http://51.158.119.88:8811",
        "http://164.90.179.64:8118",
        "http://138.197.148.215:8118",
        "socks5://68.71.249.153:48606",
        "socks5://68.71.247.130:4145",
        "socks5://174.77.111.197:4145",
        "socks5://174.77.111.196:4145",
        "socks5://199.58.185.9:4145",
        "socks5://199.58.184.97:4145",
        "socks5://72.206.181.103:4145",
        "socks5://72.206.181.97:64943",
        "socks5://72.221.164.34:60671",
        "socks5://72.221.196.157:35904",
        "socks5://174.64.199.79:4145",
        "socks5://174.64.199.82:4145",
        "socks5://72.195.34.58:4145",
        "socks5://72.195.34.59:4145",
        "socks5://72.195.34.60:27391",
        "socks5://72.195.34.41:4145",
        "socks5://72.195.34.42:4145",
        "socks5://72.206.181.105:64935",
        "socks5://72.210.208.101:4145",
        "socks5://72.210.221.223:4145",
        "socks5://72.210.252.137:4145",
        "socks5://184.178.172.5:15303",
        "socks5://184.178.172.11:4145",
        "socks5://184.178.172.14:4145",
        "socks5://184.178.172.17:4145",
        "socks5://184.178.172.18:15280",
        "socks5://184.178.172.23:4145",
        "socks5://184.178.172.26:4145",
        "socks5://184.178.172.28:15294",
    ]
    
    all_proxies.extend(fallback_proxies)
    
    # Remove duplicates and shuffle
    unique_proxies = list(set(all_proxies))
    random.shuffle(unique_proxies)
    
    print(f"[INFO] Total unique proxies collected: {len(unique_proxies)}")
    return unique_proxies

def test_proxy_fast(proxy, timeout=2):
    """Fast proxy test with very short timeout"""
    try:
        # Use httpbin.org for faster testing
        test_url = "http://httpbin.org/ip"
        proxies = {"http": proxy, "https": proxy}
        
        response = requests.get(test_url, proxies=proxies, timeout=timeout, verify=False)
        if response.status_code == 200:
            return proxy
        return None
    except:
        return None

def update_working_proxies():
    """Update working proxies list using concurrent testing"""
    global working_proxies, last_proxy_update
    
    with proxy_lock:
        current_time = time.time()
        if current_time - last_proxy_update < PROXY_UPDATE_INTERVAL and working_proxies:
            return working_proxies
        
        print("[INFO] Fetching fresh proxies...")
        start_time = time.time()
        
        # Fetch fresh proxies
        all_proxies = fetch_proxies_from_api()
        
        # Test proxies concurrently with limited workers for better performance
        print(f"[INFO] Testing {len(all_proxies)} proxies concurrently...")
        new_working_proxies = []
        
        # Test in batches for better performance
        batch_size = 50
        for i in range(0, len(all_proxies), batch_size):
            batch = all_proxies[i:i + batch_size]
            
            with ThreadPoolExecutor(max_workers=20) as executor:
                future_to_proxy = {executor.submit(test_proxy_fast, proxy): proxy for proxy in batch}
                
                for future in as_completed(future_to_proxy, timeout=5):
                    try:
                        result = future.result()
                        if result:
                            new_working_proxies.append(result)
                    except:
                        pass
            
            # Stop if we have enough working proxies
            if len(new_working_proxies) >= 20:
                break
        
        working_proxies = new_working_proxies
        last_proxy_update = current_time
        
        elapsed_time = time.time() - start_time
        print(f"[INFO] Found {len(working_proxies)} working proxies in {elapsed_time:.2f}s")
        return working_proxies

def get_fast_proxy():
    """Get a working proxy quickly"""
    if not working_proxies:
        update_working_proxies()
    
    if working_proxies:
        return random.choice(working_proxies)
    return None

def get_optimized_ydl_opts(use_proxy=True, output_path=None):
    """Optimized yt-dlp options for better performance with SSL fix"""
    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 10,
        'retries': 2,
        'fragment_retries': 2,
        'format': 'best[height<=720]/best',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'referer': 'https://www.instagram.com/',
        
        # SSL Certificate fixes
        'nocheckcertificate': True,  # Skip SSL certificate verification
        'no_check_certificate': True,  # Alternative flag
        'insecure': True,  # Allow insecure connections
        
        # Additional SSL-related options
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        },
        
        # Extractor-specific options
        'extractor_args': {
            'instagram': {
                'api_version': 'v1',
                'include_stories': False,
            }
        }
    }
    
    if output_path:
        base_opts['outtmpl'] = output_path
    else:
        base_opts['skip_download'] = True
    
    return base_opts

def download_with_fallback(url, ydl_opts, max_attempts=5):
    """Download with fast proxy fallback and direct connection fallback"""
    last_error = None
    
    for attempt in range(max_attempts):
        try:
            current_opts = ydl_opts.copy()
            
            if attempt < max_attempts - 1:  # Try with proxy first
                proxy = get_fast_proxy()
                if proxy:
                    current_opts['proxy'] = proxy
                    print(f"[INFO] Attempt {attempt + 1} using proxy: {proxy}")
                else:
                    print(f"[INFO] Attempt {attempt + 1} using direct connection (no proxy available)")
            else:  # Last attempt - try direct connection
                print(f"[INFO] Attempt {attempt + 1} using direct connection (final attempt)")
                current_opts.pop('proxy', None)
            
            with yt_dlp.YoutubeDL(current_opts) as ydl:
                info = ydl.extract_info(url, download=current_opts.get('skip_download', False) == False)
                return info
                
        except Exception as e:
            last_error = e
            error_msg = str(e)
            print(f"[ERROR] Attempt {attempt + 1} failed: {error_msg}")
            
            # If SSL error, try without proxy on next attempt
            if "SSL" in error_msg or "certificate" in error_msg.lower():
                print(f"[INFO] SSL error detected, will try direct connection on next attempt")
            
            if attempt < max_attempts - 1:
                sleep(1)  # Slightly longer sleep between attempts
    
    raise last_error

@app.route('/get-reel-thumbnail', methods=['POST'])
def get_thumbnail():
    start_time = time.time()
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        print(f"[INFO] Getting thumbnail for: {url}")
        
        ydl_opts = get_optimized_ydl_opts(use_proxy=True)
        info = download_with_fallback(url, ydl_opts, max_attempts=5)
        
        thumbnail_url = info.get("thumbnail", "")
        video_id = info.get("id", "unknown")
        title = info.get("title", "Instagram Reel")

        if not thumbnail_url:
            raise Exception("No thumbnail found")

        # Fast thumbnail download with SSL disabled
        proxy = get_fast_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.instagram.com/'
        }
        
        # Try with proxy first, then direct
        for attempt in range(2):
            try:
                if attempt == 0 and proxies:
                    response = requests.get(thumbnail_url, headers=headers, proxies=proxies, timeout=8, verify=False)
                else:
                    response = requests.get(thumbnail_url, headers=headers, timeout=8, verify=False)
                
                if response.status_code == 200:
                    break
            except Exception as e:
                if attempt == 1:
                    raise e
                continue
        
        response.raise_for_status()
        
        image_data = base64.b64encode(response.content).decode('utf-8')
        mime = response.headers.get("Content-Type", "image/jpeg")

        elapsed_time = time.time() - start_time
        print(f"[INFO] Thumbnail retrieved in {elapsed_time:.2f}s")

        return jsonify({
            "shortcode": video_id,
            "title": title,
            "thumbnail_url": thumbnail_url,
            "thumbnail_base64": f"data:{mime};base64,{image_data}",
            "processing_time": f"{elapsed_time:.2f}s"
        })

    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"[ERROR] Thumbnail failed in {elapsed_time:.2f}s: {str(e)}")
        return jsonify({"error": str(e), "processing_time": f"{elapsed_time:.2f}s"}), 500

@app.route('/download-reel', methods=['POST'])
def download_reel():
    start_time = time.time()
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        print(f"[INFO] Downloading reel: {url}")
        
        uid = str(uuid.uuid4())
        filename_template = os.path.join(DOWNLOAD_DIR, f"{uid}.%(ext)s")
        
        ydl_opts = get_optimized_ydl_opts(use_proxy=True, output_path=filename_template)
        info = download_with_fallback(url, ydl_opts, max_attempts=5)
        
        # Find the downloaded file
        downloaded_file = None
        for ext in ['mp4', 'mov', 'avi', 'mkv', 'webm']:
            potential_file = os.path.join(DOWNLOAD_DIR, f"{uid}.{ext}")
            if os.path.exists(potential_file):
                downloaded_file = potential_file
                break
        
        if not downloaded_file or not os.path.exists(downloaded_file):
            raise Exception("Download failed - file not found")
        
        if os.path.getsize(downloaded_file) == 0:
            raise Exception("Download failed - empty file")

        # Schedule cleanup
        def delete_later(path):
            sleep(60)  # Keep file for 60 seconds
            try:
                os.remove(path)
                print(f"[INFO] Deleted {path}")
            except Exception as e:
                print(f"[Cleanup error] {e}")

        Thread(target=delete_later, args=(downloaded_file,), daemon=True).start()

        elapsed_time = time.time() - start_time
        print(f"[INFO] Download completed in {elapsed_time:.2f}s")

        return send_file(
            downloaded_file,
            as_attachment=True,
            download_name=f"instagram_reel_{uid}.mp4",
            mimetype="video/mp4"
        )

    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"[ERROR] Download failed in {elapsed_time:.2f}s: {str(e)}")
        return jsonify({"error": str(e), "processing_time": f"{elapsed_time:.2f}s"}), 500

@app.route('/refresh-proxies', methods=['POST'])
def refresh_proxies():
    """Manually refresh proxy list"""
    global last_proxy_update
    last_proxy_update = 0  # Force refresh
    working = update_working_proxies()
    return jsonify({
        "message": "Proxies refreshed",
        "working_proxies": len(working),
        "proxies": working[:5]  # Show first 5
    })

@app.route('/test-proxies', methods=['GET'])
def test_proxies():
    """Test current proxy list"""
    start_time = time.time()
    working = update_working_proxies()
    elapsed_time = time.time() - start_time
    
    return jsonify({
        "working_proxies": len(working),
        "proxies": working[:10],  # Show first 10
        "test_time": f"{elapsed_time:.2f}s"
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check with proxy status"""
    proxy = get_fast_proxy()
    return jsonify({
        "status": "healthy",
        "working_proxies": len(working_proxies),
        "current_proxy": proxy,
        "temp_files": len(os.listdir(DOWNLOAD_DIR)),
        "last_proxy_update": time.time() - last_proxy_update
    })

@app.route("/")
def home():
    return jsonify({
        "message": "Instagram Reel Downloader with SSL Certificate Fix",
        "features": [
            "Auto-fetches fresh proxies from multiple sources",
            "Concurrent proxy testing",
            "Fast failover mechanism",
            "SSL certificate verification bypass",
            "Direct connection fallback",
            "Optimized for Instagram rate limits"
        ],
        "endpoints": {
            "GET /": "This help message",
            "GET /health": "Health check with proxy status",
            "GET /test-proxies": "Test current proxy list",
            "POST /refresh-proxies": "Manually refresh proxy list",
            "POST /get-reel-thumbnail": "Get reel thumbnail",
            "POST /download-reel": "Download reel video"
        }
    })

# Initialize proxies on startup
def initialize_proxies():
    """Initialize working proxies on startup"""
    print("[INFO] Initializing dynamic proxy system...")
    update_working_proxies()
    print(f"[INFO] Ready with {len(working_proxies)} working proxies")

if __name__ == "__main__":
    # Cleanup old files
    try:
        for filename in os.listdir(DOWNLOAD_DIR):
            file_path = os.path.join(DOWNLOAD_DIR, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
        print(f"[INFO] Cleaned up {DOWNLOAD_DIR}")
    except Exception as e:
        print(f"[ERROR] Cleanup failed: {e}")
    
    # Initialize proxies
    initialize_proxies()
    
    print("[INFO] Starting Instagram Reel Downloader with SSL Certificate Fix")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)