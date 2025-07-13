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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import ssl
import urllib3

app = Flask(__name__)
CORS(app)

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DOWNLOAD_DIR = "temp_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Global variables for proxy management
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
    except Exception as e:
        print(f"[ERROR] proxy-list.download failed: {e}")
    
    # Fallback hardcoded proxies
    fallback_proxies = [
        "http://47.74.152.29:8888",
        "http://103.149.162.194:80",
        "http://185.15.172.212:3128",
        "http://103.145.185.123:8080",
        "socks5://184.178.172.3:4145",
        "socks5://72.210.221.197:4145",
        "socks5://98.162.25.4:31653",
        "socks5://184.178.172.25:15291",
        "socks5://72.195.34.35:27360",
    ]
    
    all_proxies.extend(fallback_proxies)
    
    # Remove duplicates and shuffle
    unique_proxies = list(set(all_proxies))
    random.shuffle(unique_proxies)
    
    return unique_proxies

def test_proxy_fast(proxy, timeout=2):
    """Fast proxy test with short timeout"""
    try:
        test_url = "http://httpbin.org/ip"
        proxies = {"http": proxy, "https": proxy}
        
        response = requests.get(test_url, proxies=proxies, timeout=timeout, verify=False)
        if response.status_code == 200:
            return proxy
        return None
    except:
        return None

def update_working_proxies():
    """Update working proxies list"""
    global working_proxies, last_proxy_update
    
    with proxy_lock:
        current_time = time.time()
        if current_time - last_proxy_update < PROXY_UPDATE_INTERVAL and working_proxies:
            return working_proxies
        
        print("[INFO] Fetching fresh proxies...")
        all_proxies = fetch_proxies_from_api()
        
        # Test proxies concurrently
        new_working_proxies = []
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
        
        print(f"[INFO] Found {len(working_proxies)} working proxies")
        return working_proxies

def get_fast_proxy():
    """Get a working proxy"""
    if not working_proxies:
        update_working_proxies()
    
    if working_proxies:
        return random.choice(working_proxies)
    return None

def get_ydl_opts_with_proxy_ssl(output_path=None):
    """Get yt-dlp options with proxy and SSL fixes"""
    opts = {
        'quiet': True,
        'skip_download': True if output_path is None else False,
        'force_generic_extractor': False,
        'socket_timeout': 10,
        'retries': 2,
        'fragment_retries': 2,
        'format': 'mp4/best',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'referer': 'https://www.instagram.com/',
        
        # SSL Certificate fixes
        'nocheckcertificate': True,
        'no_check_certificate': True,
        'insecure': True,
        
        # HTTP headers
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        },
    }
    
    if output_path:
        opts['outtmpl'] = output_path
    
    return opts

def download_with_proxy_fallback(url, ydl_opts, max_attempts=3):
    """Download with proxy fallback"""
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
            else:  # Last attempt - direct connection
                print(f"[INFO] Attempt {attempt + 1} using direct connection (final attempt)")
                current_opts.pop('proxy', None)
            
            with yt_dlp.YoutubeDL(current_opts) as ydl:
                info = ydl.extract_info(url, download=current_opts.get('skip_download', False) == False)
                return info
                
        except Exception as e:
            last_error = e
            print(f"[ERROR] Attempt {attempt + 1} failed: {str(e)}")
            
            if attempt < max_attempts - 1:
                sleep(1)
    
    raise last_error

@app.route('/get-reel-thumbnail', methods=['POST'])
def get_thumbnail():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        print(f"[INFO] Getting thumbnail for: {url}")
        
        # Get JSON metadata using yt-dlp with proxy and SSL fixes
        ydl_opts = get_ydl_opts_with_proxy_ssl()
        info = download_with_proxy_fallback(url, ydl_opts)
        
        thumbnail_url = info.get("thumbnail", "")
        video_id = info.get("id", "unknown")

        if not thumbnail_url:
            raise Exception("No thumbnail found")

        # Fetch thumbnail image with proxy and SSL fixes
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

        return jsonify({
            "shortcode": video_id,
            "thumbnail_url": thumbnail_url,
            "thumbnail_base64": f"data:{mime};base64,{image_data}"
        })

    except Exception as e:
        print(f"[ERROR] Thumbnail failed: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/download-reel', methods=['POST'])
def download_reel():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        print(f"[INFO] Downloading reel: {url}")
        
        uid = str(uuid.uuid4())
        filename_template = os.path.join(DOWNLOAD_DIR, f"{uid}.%(ext)s")

        # Download with proxy and SSL fixes
        ydl_opts = get_ydl_opts_with_proxy_ssl(output_path=filename_template)
        info = download_with_proxy_fallback(url, ydl_opts)
        
        # Find the downloaded file
        downloaded_file = None
        for ext in ['mp4', 'mov', 'avi', 'mkv', 'webm']:
            potential_file = os.path.join(DOWNLOAD_DIR, f"{uid}.{ext}")
            if os.path.exists(potential_file):
                downloaded_file = potential_file
                break
        
        if not downloaded_file or not os.path.exists(downloaded_file):
            raise Exception("Download failed - file not found")

        # Schedule cleanup
        def delete_later(path):
            sleep(30)
            try:
                os.remove(path)
                print(f"[INFO] Deleted {path}")
            except Exception as e:
                print(f"[Cleanup error] {e}")

        Thread(target=delete_later, args=(downloaded_file,)).start()

        return send_file(
            downloaded_file,
            as_attachment=True,
            download_name=os.path.basename(downloaded_file),
            mimetype="video/mp4"
        )

    except Exception as e:
        print(f"[ERROR] Download failed: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/")
def home():
    return jsonify({"message": "Instagram Reel Downloader is running with proxy and SSL support"})

# Initialize proxies on startup
def initialize_proxies():
    """Initialize working proxies on startup"""
    print("[INFO] Initializing proxy system...")
    update_working_proxies()
    print(f"[INFO] Ready with {len(working_proxies)} working proxies")

if __name__ == "__main__":
    # Initialize proxies
    initialize_proxies()
    
    print("[INFO] Starting Instagram Reel Downloader with proxy and SSL support")
    app.run(debug=True)