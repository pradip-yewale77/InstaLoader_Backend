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
import re

app = Flask(__name__)
CORS(app)

# Global cache for thumbnails and metadata (in-memory for serverless)
THUMBNAIL_CACHE = {}
METADATA_CACHE = {}
CACHE_DURATION = 3600  # 1 hour

# Proxy configuration - DISABLED BY DEFAULT
PROXY_CONFIG = {
    'enabled': os.getenv('PROXY_ENABLED', 'false').lower() == 'true',
    'primary_proxy': os.getenv('PRIMARY_PROXY', ''),
    'fallback_proxies': []
}

# User agents for Instagram
USER_AGENTS = [
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Android 11; Mobile; rv:68.0) Gecko/68.0 Firefox/88.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
]

def get_random_user_agent():
    """Get a random user agent"""
    return random.choice(USER_AGENTS)

def get_instagram_headers():
    """Get headers optimized for Instagram"""
    return {
        'User-Agent': get_random_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0'
    }

# Load proxy configuration from environment or use defaults
def load_proxy_config():
    """Load proxy configuration from environment variables"""
    global PROXY_CONFIG
    
    # Only load proxies if explicitly enabled and provided
    if PROXY_CONFIG['enabled'] and os.getenv('PROXY_LIST'):
        proxy_list = os.getenv('PROXY_LIST').split(',')
        PROXY_CONFIG['fallback_proxies'] = [proxy.strip() for proxy in proxy_list if proxy.strip()]
    
    # Set primary proxy if provided
    if PROXY_CONFIG['enabled'] and os.getenv('PRIMARY_PROXY'):
        PROXY_CONFIG['primary_proxy'] = os.getenv('PRIMARY_PROXY')

def get_random_proxy():
    """Get a random proxy from the configured list"""
    if not PROXY_CONFIG['enabled'] or not PROXY_CONFIG['fallback_proxies']:
        return None
    
    return random.choice(PROXY_CONFIG['fallback_proxies'])

def get_proxy_dict(proxy_url=None):
    """Get proxy dictionary for requests"""
    if not PROXY_CONFIG['enabled']:
        return None
    
    if proxy_url is None:
        proxy_url = PROXY_CONFIG['primary_proxy'] or get_random_proxy()
    
    if proxy_url:
        return {
            'http': proxy_url,
            'https': proxy_url
        }
    return None

def get_ydl_proxy_opts(proxy_url=None):
    """Get yt-dlp proxy options"""
    if not PROXY_CONFIG['enabled']:
        return {}
    
    if proxy_url is None:
        proxy_url = PROXY_CONFIG['primary_proxy'] or get_random_proxy()
    
    if proxy_url:
        return {
            'proxy': proxy_url,
            'socket_timeout': 20,
            'retries': 3
        }
    return {}

# Initialize proxy configuration
load_proxy_config()

# Timeout handler for long-running operations
class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

def with_timeout(seconds):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Set timeout signal
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)
            
            try:
                result = func(*args, **kwargs)
                signal.alarm(0)  # Cancel timeout
                return result
            except TimeoutError:
                signal.alarm(0)  # Cancel timeout
                raise
            except Exception as e:
                signal.alarm(0)  # Cancel timeout
                raise e
        return wrapper
    return decorator

def get_cache_key(url):
    """Generate cache key from URL"""
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}".replace('/', '')

def is_cache_valid(timestamp):
    """Check if cache entry is still valid"""
    return time.time() - timestamp < CACHE_DURATION

def validate_instagram_url(url):
    """Validate Instagram URL"""
    instagram_patterns = [
        r'https?://(www\.)?instagram\.com/(p|reel)/[A-Za-z0-9_-]+/?',
        r'https?://(www\.)?instagram\.com/stories/[A-Za-z0-9_.-]+/[0-9]+/?'
    ]
    
    for pattern in instagram_patterns:
        if re.match(pattern, url):
            return True
    return False

def get_video_info_with_cache(url):
    """Get video info with caching to avoid repeated yt-dlp calls"""
    cache_key = get_cache_key(url)
    
    # Validate URL first
    if not validate_instagram_url(url):
        raise ValueError("Invalid Instagram URL format")
    
    # Check cache first
    if cache_key in METADATA_CACHE:
        cached_data, timestamp = METADATA_CACHE[cache_key]
        if is_cache_valid(timestamp):
            return cached_data
    
    # If not in cache or expired, fetch new data
    max_attempts = 3
    last_error = None
    
    for attempt in range(max_attempts):
        try:
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'force_generic_extractor': False,
                'socket_timeout': 30,
                'retries': 5,
                'http_headers': get_instagram_headers(),
                'extractor_args': {
                    'instagram': {
                        'comment_count': 0,
                        'like_count': 0
                    }
                }
            }
            
            # Add proxy configuration to yt-dlp options if enabled
            if PROXY_CONFIG['enabled'] and PROXY_CONFIG['fallback_proxies']:
                proxy_opts = get_ydl_proxy_opts()
                ydl_opts.update(proxy_opts)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
            # Cache the result
            METADATA_CACHE[cache_key] = (info, time.time())
            return info
            
        except Exception as e:
            last_error = e
            time.sleep(2 ** attempt)  # Exponential backoff
            
            # Try with different proxy if available and enabled
            if PROXY_CONFIG['enabled'] and len(PROXY_CONFIG['fallback_proxies']) > 1:
                continue
        
    # Try without proxy if proxy was causing issues
    if PROXY_CONFIG['enabled']:
        try:
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'force_generic_extractor': False,
                'socket_timeout': 30,
                'retries': 5,
                'http_headers': get_instagram_headers(),
                'extractor_args': {
                    'instagram': {
                        'comment_count': 0,
                        'like_count': 0
                    }
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
            # Cache the result
            METADATA_CACHE[cache_key] = (info, time.time())
            return info
        except Exception as e:
            last_error = e
    
    # If we have expired cache, return it as fallback
    if cache_key in METADATA_CACHE:
        cached_data, _ = METADATA_CACHE[cache_key]
        return cached_data
    
    # If all fails, raise the last error
    raise last_error if last_error else Exception("Failed to extract video info")

@app.route('/get-reel-thumbnail', methods=['POST'])
def get_thumbnail():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        # Validate URL
        if not validate_instagram_url(url):
            return jsonify({"error": "Invalid Instagram URL format"}), 400
        
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
            return jsonify({"error": "No thumbnail found for this Instagram post"}), 404

        # Fetch thumbnail with timeout and retry logic
        max_retries = 5
        proxies = get_proxy_dict() if PROXY_CONFIG['enabled'] else None
        
        for attempt in range(max_retries):
            try:
                # Use different proxy for each retry if available
                if PROXY_CONFIG['enabled'] and attempt > 0 and len(PROXY_CONFIG['fallback_proxies']) > 1:
                    proxies = get_proxy_dict(get_random_proxy())
                
                # Use Instagram-optimized headers
                headers = get_instagram_headers()
                
                response = requests.get(
                    thumbnail_url, 
                    timeout=(10, 30),  # (connect timeout, read timeout)
                    proxies=proxies,
                    headers=headers,
                    stream=True,
                    verify=True
                )
                response.raise_for_status()
                
                # Check if response is actually an image
                content_type = response.headers.get('content-type', '').lower()
                if not content_type.startswith('image/'):
                    raise requests.RequestException(f"Invalid content type: {content_type}")
                
                break
                
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    # Try once more without proxy and with minimal headers
                    try:
                        response = requests.get(
                            thumbnail_url, 
                            timeout=(10, 30),
                            headers={'User-Agent': get_random_user_agent()},
                            stream=True,
                            verify=True
                        )
                        response.raise_for_status()
                        break
                    except Exception as final_e:
                        return jsonify({
                            "error": f"Failed to fetch thumbnail after {max_retries} attempts. Last error: {str(final_e)}"
                        }), 500
                
                # Exponential backoff
                time.sleep(min(2 ** attempt, 10))
        
        # Read and encode thumbnail
        try:
            image_content = response.content
            if len(image_content) == 0:
                raise ValueError("Empty image content")
            
            image_data = base64.b64encode(image_content).decode('utf-8')
            mime = response.headers.get("Content-Type", "image/jpeg")
            
            result = {
                "shortcode": video_id,
                "thumbnail_url": thumbnail_url,
                "thumbnail_base64": f"data:{mime};base64,{image_data}",
                "duration": info.get("duration", 0),
                "title": info.get("title", ""),
                "uploader": info.get("uploader", ""),
                "proxy_used": bool(proxies),
                "timestamp": int(time.time())
            }
            
            # Cache the result
            THUMBNAIL_CACHE[cache_key] = (result, time.time())
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({"error": f"Failed to process thumbnail image: {str(e)}"}), 500

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except TimeoutError:
        return jsonify({"error": "Request timed out. Instagram may be blocking requests. Please try again later."}), 408
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["rate limit", "too many requests", "429"]):
            return jsonify({"error": "Rate limited by Instagram. Please try again later."}), 429
        elif any(keyword in error_msg for keyword in ["blocked", "forbidden", "403"]):
            return jsonify({"error": "Access blocked by Instagram. Try using a proxy or VPN."}), 403
        elif any(keyword in error_msg for keyword in ["unavailable", "private", "not found"]):
            return jsonify({"error": "Instagram post not found or is private."}), 404
        else:
            return jsonify({"error": f"Failed to get thumbnail: {str(e)}"}), 500

@app.route('/download-reel', methods=['POST'])
def download_reel():
    data = request.get_json()
    url = data.get("url")
    quality = data.get("quality", "best")  # Allow quality selection
    
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        # Validate URL
        if not validate_instagram_url(url):
            return jsonify({"error": "Invalid Instagram URL format"}), 400
        
        # Get video info first
        info = get_video_info_with_cache(url)
        
        # Check video size and duration to prevent timeouts
        duration = info.get("duration", 0)
        if duration > 600:  # 10 minutes
            return jsonify({"error": "Video too long. Maximum duration is 10 minutes."}), 400
        
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
                'Content-Type': 'video/mp4',
                'Cache-Control': 'no-cache'
            }
        )
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except TimeoutError:
        return jsonify({"error": "Download timed out. Try selecting a lower quality."}), 408
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["rate limit", "too many requests"]):
            return jsonify({"error": "Rate limited by Instagram. Please try again later."}), 429
        elif any(keyword in error_msg for keyword in ["blocked", "forbidden"]):
            return jsonify({"error": "Access blocked by Instagram. Try using a proxy or VPN."}), 403
        else:
            return jsonify({"error": f"Download failed: {str(e)}"}), 500

def download_video_stream(url, format_selector):
    """Stream video download to avoid memory issues"""
    with tempfile.TemporaryDirectory() as temp_dir:
        uid = str(uuid.uuid4())
        filename_template = os.path.join(temp_dir, f"{uid}.%(ext)s")
        
        ydl_opts = {
            'outtmpl': filename_template,
            'format': format_selector,
            'quiet': True,
            'socket_timeout': 30,
            'retries': 5,
            'fragment_retries': 5,
            'http_headers': get_instagram_headers(),
            'extractor_args': {
                'instagram': {
                    'comment_count': 0,
                    'like_count': 0
                }
            }
        }
        
        # Add proxy configuration to yt-dlp options if enabled
        if PROXY_CONFIG['enabled'] and PROXY_CONFIG['fallback_proxies']:
            proxy_opts = get_ydl_proxy_opts()
            ydl_opts.update(proxy_opts)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
            
            # Check if file exists and has content
            if not os.path.exists(downloaded_file) or os.path.getsize(downloaded_file) == 0:
                raise Exception("Downloaded file is empty or missing")
            
            # Stream the file in chunks
            chunk_size = 8192
            with open(downloaded_file, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
                    
        except Exception as e:
            # Try with different proxy if available
            if PROXY_CONFIG['enabled'] and len(PROXY_CONFIG['fallback_proxies']) > 1:
                for proxy in PROXY_CONFIG['fallback_proxies'][1:]:
                    try:
                        ydl_opts = {
                            'outtmpl': filename_template,
                            'format': format_selector,
                            'quiet': True,
                            'socket_timeout': 30,
                            'retries': 3,
                            'fragment_retries': 3,
                            'http_headers': get_instagram_headers()
                        }
                        proxy_opts = get_ydl_proxy_opts(proxy)
                        ydl_opts.update(proxy_opts)
                        
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
                        return
                    except:
                        continue
            
            # Try without proxy as last resort
            try:
                ydl_opts = {
                    'outtmpl': filename_template,
                    'format': format_selector,
                    'quiet': True,
                    'socket_timeout': 30,
                    'retries': 3,
                    'fragment_retries': 3,
                    'http_headers': get_instagram_headers()
                }
                
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
            except:
                yield b''  # Empty response on error

@app.route('/get-reel-info', methods=['POST'])
def get_reel_info():
    """Get detailed reel information without downloading"""
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        # Validate URL
        if not validate_instagram_url(url):
            return jsonify({"error": "Invalid Instagram URL format"}), 400
        
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
            ][:5],  # Limit to top 5 formats
            "timestamp": int(time.time())
        }
        
        return jsonify(result)
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["rate limit", "too many requests"]):
            return jsonify({"error": "Rate limited by Instagram. Please try again later."}), 429
        elif any(keyword in error_msg for keyword in ["blocked", "forbidden"]):
            return jsonify({"error": "Access blocked by Instagram. Try using a proxy or VPN."}), 403
        else:
            return jsonify({"error": str(e)}), 500

@app.route('/proxy-config', methods=['GET'])
def get_proxy_config():
    """Get current proxy configuration"""
    return jsonify({
        "proxy_enabled": PROXY_CONFIG['enabled'],
        "primary_proxy": PROXY_CONFIG['primary_proxy'],
        "fallback_proxies_count": len(PROXY_CONFIG['fallback_proxies']),
        "total_proxies": len(PROXY_CONFIG['fallback_proxies'])
    })

@app.route('/proxy-config', methods=['POST'])
def update_proxy_config():
    """Update proxy configuration"""
    data = request.get_json()
    
    if 'enabled' in data:
        PROXY_CONFIG['enabled'] = data['enabled']
    
    if 'primary_proxy' in data:
        PROXY_CONFIG['primary_proxy'] = data['primary_proxy']
    
    if 'fallback_proxies' in data:
        PROXY_CONFIG['fallback_proxies'] = data['fallback_proxies']
    
    return jsonify({"message": "Proxy configuration updated successfully"})

@app.route('/test-proxy', methods=['POST'])
def test_proxy():
    """Test proxy connectivity"""
    data = request.get_json()
    proxy_url = data.get('proxy_url') or PROXY_CONFIG['primary_proxy']
    
    if not proxy_url:
        return jsonify({"error": "No proxy URL provided"}), 400
    
    try:
        proxies = get_proxy_dict(proxy_url)
        test_url = "https://httpbin.org/ip"
        
        response = requests.get(test_url, proxies=proxies, timeout=10)
        response.raise_for_status()
        
        return jsonify({
            "status": "success",
            "proxy_url": proxy_url,
            "response": response.json(),
            "response_time": response.elapsed.total_seconds()
        })
        
    except Exception as e:
        return jsonify({
            "status": "failed",
            "proxy_url": proxy_url,
            "error": str(e)
        }), 500

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
        "proxy_config": {
            "enabled": PROXY_CONFIG['enabled'],
            "proxies_available": len(PROXY_CONFIG['fallback_proxies'])
        },
        "version": "2.1.1"
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
        "message": "Instagram Reel Downloader API with Enhanced Error Handling",
        "endpoints": {
            "GET /health": "Health check",
            "POST /get-reel-thumbnail": "Get reel thumbnail",
            "POST /get-reel-info": "Get reel information",
            "POST /download-reel": "Download reel (supports quality parameter)",
            "POST /clear-cache": "Clear cache",
            "GET /proxy-config": "Get proxy configuration",
            "POST /proxy-config": "Update proxy configuration",
            "POST /test-proxy": "Test proxy connectivity"
        },
        "version": "2.1.1",
        "features": [
            "streaming", 
            "caching", 
            "timeout_handling", 
            "rate_limit_handling",
            "proxy_support",
            "proxy_fallback",
            "enhanced_error_handling",
            "instagram_headers",
            "url_validation"
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

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)