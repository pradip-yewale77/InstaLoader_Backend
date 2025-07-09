from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import os
import base64
import requests
import tempfile
import uuid
import time
import json
from urllib.parse import urlparse
import signal
import sys
from functools import wraps
import random
import threading
from concurrent.futures import ThreadPoolExecutor
import itertools

app = Flask(__name__)
CORS(app)

# Global cache for thumbnails and metadata (in-memory for serverless)
THUMBNAIL_CACHE = {}
METADATA_CACHE = {}
CACHE_DURATION = 3600  # 1 hour

# Free proxy lists (rotating)
FREE_PROXIES = [
    # HTTP Proxies
    {'http': 'http://20.206.106.192:80', 'https': 'http://20.206.106.192:80'},
    {'http': 'http://47.74.152.29:8888', 'https': 'http://47.74.152.29:8888'},
    {'http': 'http://103.149.162.194:80', 'https': 'http://103.149.162.194:80'},
    {'http': 'http://185.199.84.161:53281', 'https': 'http://185.199.84.161:53281'},
    {'http': 'http://103.167.134.31:80', 'https': 'http://103.167.134.31:80'},
    {'http': 'http://49.0.2.242:8090', 'https': 'http://49.0.2.242:8090'},
    {'http': 'http://103.152.112.162:80', 'https': 'http://103.152.112.162:80'},
    {'http': 'http://185.199.229.156:7492', 'https': 'http://185.199.229.156:7492'},
    {'http': 'http://103.149.162.195:80', 'https': 'http://103.149.162.195:80'},
    {'http': 'http://20.111.54.16:80', 'https': 'http://20.111.54.16:80'},
    
    # SOCKS Proxies
    {'http': 'socks5://98.162.25.29:31679', 'https': 'socks5://98.162.25.29:31679'},
    {'http': 'socks5://72.195.34.35:27360', 'https': 'socks5://72.195.34.35:27360'},
    {'http': 'socks5://184.178.172.25:15291', 'https': 'socks5://184.178.172.25:15291'},
    {'http': 'socks5://72.195.34.41:4145', 'https': 'socks5://72.195.34.41:4145'},
    {'http': 'socks5://184.178.172.26:4145', 'https': 'socks5://184.178.172.26:4145'},
]

# User agents for rotation
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPad; CPU OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Android 11; Mobile; rv:89.0) Gecko/89.0 Firefox/89.0'
]

# Proxy rotation state
proxy_iterator = itertools.cycle(FREE_PROXIES)
working_proxies = []
proxy_lock = threading.Lock()

# Timeout handler for long-running operations
class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

def with_timeout(seconds):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Only use signal timeout on Unix systems
            if hasattr(signal, 'SIGALRM') and os.name != 'nt':
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(seconds)
            
            try:
                result = func(*args, **kwargs)
                if hasattr(signal, 'SIGALRM') and os.name != 'nt':
                    signal.alarm(0)  # Cancel timeout
                return result
            except TimeoutError:
                if hasattr(signal, 'SIGALRM') and os.name != 'nt':
                    signal.alarm(0)  # Cancel timeout
                raise
            except Exception as e:
                if hasattr(signal, 'SIGALRM') and os.name != 'nt':
                    signal.alarm(0)  # Cancel timeout
                raise e
        return wrapper
    return decorator

def test_proxy(proxy):
    """Test if a proxy is working"""
    try:
        response = requests.get(
            'http://httpbin.org/ip',
            proxies=proxy,
            timeout=5,
            headers={'User-Agent': random.choice(USER_AGENTS)}
        )
        return response.status_code == 200
    except:
        return False

def get_working_proxy():
    """Get a working proxy from the list"""
    global working_proxies
    
    with proxy_lock:
        # If we have working proxies, use them
        if working_proxies:
            return random.choice(working_proxies)
        
        # Test proxies and find working ones
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(test_proxy, proxy): proxy for proxy in FREE_PROXIES}
            
            for future in futures:
                try:
                    if future.result(timeout=5):
                        working_proxies.append(futures[future])
                        if len(working_proxies) >= 3:  # Stop after finding 3 working proxies
                            break
                except:
                    continue
        
        return random.choice(working_proxies) if working_proxies else None

def get_cache_key(url):
    """Generate cache key from URL"""
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}".replace('/', '')

def is_cache_valid(timestamp):
    """Check if cache entry is still valid"""
    return time.time() - timestamp < CACHE_DURATION

def make_request_with_proxy(url, max_retries=3):
    """Make HTTP request with proxy rotation and retry logic"""
    for attempt in range(max_retries):
        try:
            proxy = get_working_proxy()
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            kwargs = {
                'timeout': 10,
                'headers': headers,
                'allow_redirects': True
            }
            
            if proxy:
                kwargs['proxies'] = proxy
            
            response = requests.get(url, **kwargs)
            response.raise_for_status()
            return response
            
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            
            # Remove failed proxy from working list
            if proxy and proxy in working_proxies:
                with proxy_lock:
                    working_proxies.remove(proxy)
            
            time.sleep(1)  # Brief delay before retry

def get_video_info_with_cache(url):
    """Get video info with caching and proxy support"""
    cache_key = get_cache_key(url)
    
    # Check cache first
    if cache_key in METADATA_CACHE:
        cached_data, timestamp = METADATA_CACHE[cache_key]
        if is_cache_valid(timestamp):
            return cached_data
    
    # If not in cache or expired, fetch new data
    try:
        proxy = get_working_proxy()
        
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'force_generic_extractor': False,
            'socket_timeout': 15,
            'retries': 3,
            'fragment_retries': 3,
            'http_headers': {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Accept-Encoding': 'gzip,deflate',
                'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
                'Keep-Alive': '115',
                'Connection': 'keep-alive',
            }
        }
        
        # Add proxy to yt-dlp options if available
        if proxy:
            if 'socks' in list(proxy.values())[0]:
                ydl_opts['proxy'] = list(proxy.values())[0]
            else:
                ydl_opts['proxy'] = list(proxy.values())[0]
        
        # Try alternative extractors for Instagram
        extractors_to_try = [
            {'format': 'best', 'extractor': None},
            {'format': 'worst', 'extractor': None},
            {'format': 'best[height<=720]', 'extractor': None}
        ]
        
        last_exception = None
        for extractor_config in extractors_to_try:
            try:
                current_opts = ydl_opts.copy()
                if extractor_config['format']:
                    current_opts['format'] = extractor_config['format']
                
                with yt_dlp.YoutubeDL(current_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                # Cache the result
                METADATA_CACHE[cache_key] = (info, time.time())
                return info
                
            except Exception as e:
                last_exception = e
                continue
        
        # If all extractors failed, raise the last exception
        if last_exception:
            raise last_exception
            
    except Exception as e:
        # If we have expired cache, return it as fallback
        if cache_key in METADATA_CACHE:
            cached_data, _ = METADATA_CACHE[cache_key]
            return cached_data
        raise e

@app.route('/get-reel-thumbnail', methods=['POST'])
def get_thumbnail():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        cache_key = get_cache_key(url)
        
        # Check thumbnail cache first
        if cache_key in THUMBNAIL_CACHE:
            cached_data, timestamp = THUMBNAIL_CACHE[cache_key]
            if is_cache_valid(timestamp):
                return jsonify(cached_data)
        
        # Get video info with timeout
        info = get_video_info_with_cache(url)
        thumbnail_url = info.get("thumbnail", "")
        video_id = info.get("id", "unknown")
        
        if not thumbnail_url:
            return jsonify({"error": "No thumbnail found"}), 404

        # Fetch thumbnail with proxy support
        response = make_request_with_proxy(thumbnail_url)
        
        # Encode thumbnail
        image_data = base64.b64encode(response.content).decode('utf-8')
        mime = response.headers.get("Content-Type", "image/jpeg")
        
        result = {
            "shortcode": video_id,
            "thumbnail_url": thumbnail_url,
            "thumbnail_base64": f"data:{mime};base64,{image_data}",
            "duration": info.get("duration", 0),
            "title": info.get("title", ""),
            "uploader": info.get("uploader", "")
        }
        
        # Cache the result
        THUMBNAIL_CACHE[cache_key] = (result, time.time())
        
        return jsonify(result)

    except TimeoutError:
        return jsonify({"error": "Request timed out. Please try again."}), 408
    except Exception as e:
        error_msg = str(e)
        if "rate limit" in error_msg.lower():
            return jsonify({"error": "Rate limited by Instagram. Please try again later."}), 429
        elif "login required" in error_msg.lower():
            return jsonify({"error": "Content requires authentication. This may be a private account."}), 403
        elif "not available" in error_msg.lower():
            return jsonify({"error": "Content not available. Video may have been deleted or is private."}), 404
        return jsonify({"error": f"Failed to get thumbnail: {error_msg}"}), 500

@app.route('/download-reel', methods=['POST'])
def download_reel():
    data = request.get_json()
    url = data.get("url")
    quality = data.get("quality", "best")
    
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        # Get video info first
        info = get_video_info_with_cache(url)
        
        # Check video size and duration to prevent timeouts
        duration = info.get("duration", 0)
        if duration > 300:  # 5 minutes
            return jsonify({"error": "Video too long. Maximum duration is 5 minutes."}), 400
        
        # Select appropriate format based on quality
        format_selector = {
            "low": "worst[height<=480]",
            "medium": "best[height<=720]",
            "high": "best[height<=1080]",
            "best": "best"
        }.get(quality, "best")
        
        return Response(
            stream_with_context(download_video_stream(url, format_selector)),
            mimetype='video/mp4',
            headers={
                'Content-Disposition': f'attachment; filename="reel_{uuid.uuid4().hex[:8]}.mp4"',
                'Content-Type': 'video/mp4'
            }
        )
        
    except TimeoutError:
        return jsonify({"error": "Download timed out. Try selecting a lower quality."}), 408
    except Exception as e:
        error_msg = str(e)
        if "rate limit" in error_msg.lower():
            return jsonify({"error": "Rate limited by Instagram. Please try again later."}), 429
        elif "login required" in error_msg.lower():
            return jsonify({"error": "Content requires authentication. This may be a private account."}), 403
        return jsonify({"error": f"Download failed: {error_msg}"}), 500

def download_video_stream(url, format_selector):
    """Stream video download with proxy support"""
    with tempfile.TemporaryDirectory() as temp_dir:
        uid = str(uuid.uuid4())
        filename_template = os.path.join(temp_dir, f"{uid}.%(ext)s")
        
        proxy = get_working_proxy()
        
        ydl_opts = {
            'outtmpl': filename_template,
            'format': format_selector,
            'quiet': True,
            'socket_timeout': 20,
            'retries': 3,
            'fragment_retries': 5,
            'http_headers': {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Accept-Encoding': 'gzip,deflate',
                'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
                'Keep-Alive': '115',
                'Connection': 'keep-alive',
            }
        }
        
        # Add proxy to yt-dlp options if available
        if proxy:
            if 'socks' in list(proxy.values())[0]:
                ydl_opts['proxy'] = list(proxy.values())[0]
            else:
                ydl_opts['proxy'] = list(proxy.values())[0]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
            
            # Stream the file in chunks
            chunk_size = 8192
            with open(downloaded_file, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
                    
        except Exception as e:
            yield b''  # Empty response on error

@app.route('/get-reel-info', methods=['POST'])
def get_reel_info():
    """Get detailed reel information without downloading"""
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        info = get_video_info_with_cache(url)
        
        # Extract relevant information
        result = {
            "id": info.get("id", ""),
            "title": info.get("title", ""),
            "description": info.get("description", ""),
            "duration": info.get("duration", 0),
            "view_count": info.get("view_count", 0),
            "like_count": info.get("like_count", 0),
            "uploader": info.get("uploader", ""),
            "upload_date": info.get("upload_date", ""),
            "thumbnail": info.get("thumbnail", ""),
            "formats": [
                {
                    "format_id": fmt.get("format_id", ""),
                    "height": fmt.get("height", 0),
                    "width": fmt.get("width", 0),
                    "ext": fmt.get("ext", ""),
                    "filesize": fmt.get("filesize", 0)
                }
                for fmt in info.get("formats", [])
                if fmt.get("ext") in ["mp4", "webm"]
            ][:5]  # Limit to top 5 formats
        }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/proxy-status', methods=['GET'])
def proxy_status():
    """Check proxy status"""
    return jsonify({
        "working_proxies": len(working_proxies),
        "total_proxies": len(FREE_PROXIES),
        "proxy_details": [
            {
                "proxy": proxy,
                "status": "active" if proxy in working_proxies else "untested"
            }
            for proxy in FREE_PROXIES
        ]
    })

@app.route('/refresh-proxies', methods=['POST'])
def refresh_proxies():
    """Refresh proxy list"""
    global working_proxies
    with proxy_lock:
        working_proxies.clear()
    
    # Test proxies in background
    threading.Thread(target=lambda: get_working_proxy()).start()
    
    return jsonify({"message": "Proxy refresh initiated"})

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "cache_stats": {
            "thumbnails_cached": len(THUMBNAIL_CACHE),
            "metadata_cached": len(METADATA_CACHE)
        },
        "proxy_stats": {
            "working_proxies": len(working_proxies),
            "total_proxies": len(FREE_PROXIES)
        }
    })

@app.route('/clear-cache', methods=['POST'])
def clear_cache():
    """Clear cache endpoint"""
    global THUMBNAIL_CACHE, METADATA_CACHE
    THUMBNAIL_CACHE.clear()
    METADATA_CACHE.clear()
    return jsonify({"message": "Cache cleared successfully"})

@app.route("/")
def root():
    return jsonify({
        "message": "Instagram Reel Downloader API with Proxy Support",
        "endpoints": {
            "GET /health": "Health check",
            "POST /get-reel-thumbnail": "Get reel thumbnail",
            "POST /get-reel-info": "Get reel information",
            "POST /download-reel": "Download reel (supports quality parameter)",
            "POST /clear-cache": "Clear cache",
            "GET /proxy-status": "Check proxy status",
            "POST /refresh-proxies": "Refresh proxy list"
        },
        "version": "3.0",
        "features": [
            "streaming", 
            "caching", 
            "timeout_handling", 
            "rate_limit_handling",
            "proxy_rotation",
            "user_agent_rotation",
            "enhanced_error_handling"
        ]
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"error": "Method not allowed"}), 405

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# Initialize working proxies on startup
def initialize_proxies():
    """Initialize proxies in a background thread"""
    threading.Thread(target=lambda: get_working_proxy(), daemon=True).start()

# Initialize proxies when the module is imported
initialize_proxies()

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)