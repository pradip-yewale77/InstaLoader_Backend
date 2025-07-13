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
from urllib.parse import urlparse, parse_qs
import signal
import sys
from functools import wraps
import random
import re
import threading
from collections import defaultdict
import hashlib

app = Flask(__name__)
CORS(app)

# Global cache for thumbnails and metadata (in-memory for serverless)
THUMBNAIL_CACHE = {}
METADATA_CACHE = {}
SESSION_CACHE = {}
CACHE_DURATION = 1800  # 30 minutes for faster refresh

# Rate limiting
REQUEST_TRACKER = defaultdict(list)
RATE_LIMIT_WINDOW = 120  # 2 minutes
MAX_REQUESTS_PER_WINDOW = 3  # Reduced for deployed environments
REQUEST_DELAY = 8  # Increased delay

# Session management
SESSIONS = {}
SESSION_ROTATION_TIME = 300  # 5 minutes

# Proxy configuration
PROXY_CONFIG = {
    'enabled': os.getenv('PROXY_ENABLED', 'false').lower() == 'true',
    'primary_proxy': os.getenv('PRIMARY_PROXY', ''),
    'fallback_proxies': []
}

# Enhanced User agents with more variety
USER_AGENTS = [
    # Mobile Instagram app user agents
    'Instagram 276.0.0.16.119 Android (33/13; 420dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100; en_US; 458229237)',
    'Instagram 276.0.0.16.119 Android (32/12; 450dpi; 1080x2340; OnePlus; CPH2399; OP515FL1; qcom; en_US; 458229237)',
    'Instagram 276.0.0.16.119 Android (31/12; 440dpi; 1080x2400; Xiaomi; M2102J20SG; alioth; qcom; en_US; 458229237)',
    
    # iOS Instagram app user agents
    'Instagram 295.0.0.18.111 (iPhone14,5; iOS 16_6; en_US; en-US; scale=3.00; 1170x2532; 458229237) AppleWebKit/420+',
    'Instagram 295.0.0.18.111 (iPhone13,2; iOS 15_7_1; en_US; en-US; scale=3.00; 1170x2532; 458229237) AppleWebKit/420+',
    
    # Web browsers
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Android 13; Mobile; rv:109.0) Gecko/111.0 Firefox/111.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
]

# Cookie configuration
COOKIE_CONFIG = {
    'cookies_file': os.getenv('COOKIES_FILE', ''),
    'browser_cookies': os.getenv('BROWSER_COOKIES', 'chrome'),
    'use_cookies': os.getenv('USE_COOKIES', 'true').lower() == 'true',
    'fallback_mode': True  # Enable fallback when cookies fail
}

def get_random_user_agent():
    """Get a random user agent"""
    return random.choice(USER_AGENTS)

def get_session_id():
    """Get or create a session ID"""
    current_time = time.time()
    
    # Clean old sessions
    expired_sessions = [sid for sid, data in SESSIONS.items() 
                       if current_time - data['created'] > SESSION_ROTATION_TIME]
    for sid in expired_sessions:
        del SESSIONS[sid]
    
    # Create new session if none exist or all expired
    if not SESSIONS:
        session_id = str(uuid.uuid4())
        SESSIONS[session_id] = {
            'created': current_time,
            'requests': 0,
            'user_agent': get_random_user_agent()
        }
        return session_id
    
    # Use existing session with least requests
    return min(SESSIONS.keys(), key=lambda x: SESSIONS[x]['requests'])

def get_instagram_headers(session_id=None):
    """Get headers optimized for Instagram with session management"""
    if session_id and session_id in SESSIONS:
        user_agent = SESSIONS[session_id]['user_agent']
        SESSIONS[session_id]['requests'] += 1
    else:
        user_agent = get_random_user_agent()
    
    # Simulate mobile app headers for better success rate
    if 'Instagram' in user_agent:
        return {
            'User-Agent': user_agent,
            'Accept': '*/*',
            'Accept-Language': 'en-US',
            'Accept-Encoding': 'gzip, deflate',
            'X-IG-App-ID': '936619743392459',
            'X-IG-WWW-Claim': '0',
            'X-Requested-With': 'XMLHttpRequest',
            'Connection': 'keep-alive'
        }
    else:
        return {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }

def check_rate_limit(client_ip):
    """Check if client has exceeded rate limit"""
    current_time = time.time()
    
    # Clean old requests
    REQUEST_TRACKER[client_ip] = [
        req_time for req_time in REQUEST_TRACKER[client_ip]
        if current_time - req_time < RATE_LIMIT_WINDOW
    ]
    
    # Check if rate limit exceeded
    if len(REQUEST_TRACKER[client_ip]) >= MAX_REQUESTS_PER_WINDOW:
        return False
    
    # Add current request
    REQUEST_TRACKER[client_ip].append(current_time)
    return True

def apply_request_delay():
    """Apply delay between requests to avoid rate limiting"""
    delay = REQUEST_DELAY + random.uniform(2, 5)
    time.sleep(delay)

def extract_shortcode_from_url(url):
    """Extract shortcode from Instagram URL"""
    patterns = [
        r'/(?:p|reel)/([A-Za-z0-9_-]+)',
        r'/([A-Za-z0-9_-]+)/?(?:\?|$)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_fallback_thumbnail(url):
    """Fallback method to get thumbnail when yt-dlp fails"""
    try:
        shortcode = extract_shortcode_from_url(url)
        if not shortcode:
            return None
        
        # Try Instagram's embed endpoint
        embed_url = f"https://www.instagram.com/p/{shortcode}/embed/"
        session_id = get_session_id()
        headers = get_instagram_headers(session_id)
        
        response = requests.get(embed_url, headers=headers, timeout=15)
        if response.status_code == 200:
            # Extract thumbnail URL from embed page
            content = response.text
            
            # Look for thumbnail in various formats
            thumbnail_patterns = [
                r'"display_url":"([^"]+)"',
                r'"thumbnail_src":"([^"]+)"',
                r'property="og:image" content="([^"]+)"',
                r'"src":"([^"]+\.jpg[^"]*)"'
            ]
            
            for pattern in thumbnail_patterns:
                match = re.search(pattern, content)
                if match:
                    thumbnail_url = match.group(1).replace('\\u0026', '&').replace('\\/', '/')
                    return thumbnail_url
        
        return None
    except:
        return None

def get_video_info_fallback(url):
    """Fallback method when yt-dlp completely fails"""
    try:
        shortcode = extract_shortcode_from_url(url)
        if not shortcode:
            return None
        
        session_id = get_session_id()
        headers = get_instagram_headers(session_id)
        
        # Try different endpoints
        endpoints = [
            f"https://www.instagram.com/p/{shortcode}/embed/",
            f"https://www.instagram.com/reel/{shortcode}/embed/",
            f"https://www.instagram.com/p/{shortcode}/"
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, headers=headers, timeout=20)
                if response.status_code == 200:
                    content = response.text
                    
                    # Extract basic info
                    info = {
                        'id': shortcode,
                        'title': '',
                        'thumbnail': get_fallback_thumbnail(url),
                        'uploader': '',
                        'duration': 0
                    }
                    
                    # Try to extract title/caption
                    title_patterns = [
                        r'property="og:title" content="([^"]+)"',
                        r'"caption":"([^"]+)"',
                        r'<title>([^<]+)</title>'
                    ]
                    
                    for pattern in title_patterns:
                        match = re.search(pattern, content)
                        if match:
                            info['title'] = match.group(1).strip()
                            break
                    
                    return info
            except:
                continue
        
        return None
    except:
        return None

# Load proxy configuration from environment or use defaults
def load_proxy_config():
    """Load proxy configuration from environment variables"""
    global PROXY_CONFIG
    
    if PROXY_CONFIG['enabled'] and os.getenv('PROXY_LIST'):
        proxy_list = os.getenv('PROXY_LIST').split(',')
        PROXY_CONFIG['fallback_proxies'] = [proxy.strip() for proxy in proxy_list if proxy.strip()]
    
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
            'socket_timeout': 45,
            'retries': 8
        }
    return {}

def get_cookie_opts():
    """Get cookie options for yt-dlp with fallback handling"""
    cookie_opts = {}
    
    if not COOKIE_CONFIG['use_cookies']:
        return cookie_opts
    
    # In deployment environments, cookies might not be available
    try:
        # Use cookies from file if provided and exists
        if COOKIE_CONFIG['cookies_file'] and os.path.exists(COOKIE_CONFIG['cookies_file']):
            cookie_opts['cookiefile'] = COOKIE_CONFIG['cookies_file']
        elif not os.getenv('RENDER') and not os.getenv('NETLIFY'):  # Only try browser cookies locally
            # Try to extract cookies from browser (only works locally)
            cookie_opts['cookiesfrombrowser'] = (COOKIE_CONFIG['browser_cookies'], None, None, None)
    except Exception as e:
        # Cookies failed, continue without them in deployment
        pass
    
    return cookie_opts

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

def get_video_info_with_cache(url, use_cache=True):
    """Get video info with caching and multiple fallback methods"""
    cache_key = get_cache_key(url)
    
    # Validate URL first
    if not validate_instagram_url(url):
        raise ValueError("Invalid Instagram URL format")
    
    # Check cache first if enabled
    if use_cache and cache_key in METADATA_CACHE:
        cached_data, timestamp = METADATA_CACHE[cache_key]
        if is_cache_valid(timestamp):
            return cached_data
    
    # Apply request delay
    apply_request_delay()
    
    # Try yt-dlp first
    session_id = get_session_id()
    max_attempts = 2  # Reduced attempts for faster fallback
    last_error = None
    
    for attempt in range(max_attempts):
        try:
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'force_generic_extractor': False,
                'socket_timeout': 30,  # Reduced timeout
                'retries': 3,  # Reduced retries
                'http_headers': get_instagram_headers(session_id),
                'extractor_args': {
                    'instagram': {
                        'comment_count': 0,
                        'like_count': 0
                    }
                },
                'no_warnings': True,
                'ignoreerrors': True  # Don't fail on minor errors
            }
            
            # Add cookie configuration (might not work in deployment)
            try:
                cookie_opts = get_cookie_opts()
                ydl_opts.update(cookie_opts)
            except:
                pass
            
            # Add proxy configuration if enabled
            if PROXY_CONFIG['enabled'] and PROXY_CONFIG['fallback_proxies']:
                try:
                    proxy_opts = get_ydl_proxy_opts()
                    ydl_opts.update(proxy_opts)
                except:
                    pass
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
            # Cache the result
            if use_cache:
                METADATA_CACHE[cache_key] = (info, time.time())
            return info
            
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()
            
            # If rate limited or login required, try fallback immediately
            if any(keyword in error_msg for keyword in ["rate", "limit", "login", "not available", "429"]):
                break
            
            # Short wait before retry
            time.sleep(2)
    
    # Try fallback method when yt-dlp fails
    try:
        fallback_info = get_video_info_fallback(url)
        if fallback_info:
            if use_cache:
                METADATA_CACHE[cache_key] = (fallback_info, time.time())
            return fallback_info
    except Exception as e:
        last_error = e
    
    # If we have expired cache, return it as last resort
    if use_cache and cache_key in METADATA_CACHE:
        cached_data, _ = METADATA_CACHE[cache_key]
        return cached_data
    
    # If all fails, raise the last error
    raise last_error if last_error else Exception("All extraction methods failed")

@app.route('/get-reel-thumbnail', methods=['POST'])
def get_thumbnail():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    # Get client IP for rate limiting
    client_ip = request.remote_addr or request.headers.get('X-Forwarded-For', 'unknown').split(',')[0]
    
    # Check rate limit
    if not check_rate_limit(client_ip):
        return jsonify({
            "error": f"Rate limit exceeded. Maximum {MAX_REQUESTS_PER_WINDOW} requests per {RATE_LIMIT_WINDOW} seconds."
        }), 429

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
        
        # Get video info with multiple fallback methods
        info = get_video_info_with_cache(url)
        thumbnail_url = info.get("thumbnail", "")
        video_id = info.get("id", "unknown")
        
        # If no thumbnail from main method, try fallback
        if not thumbnail_url:
            thumbnail_url = get_fallback_thumbnail(url)
        
        if not thumbnail_url:
            return jsonify({"error": "No thumbnail found for this Instagram post"}), 404

        # Fetch thumbnail with enhanced retry logic
        max_retries = 3  # Reduced for faster response
        session_id = get_session_id()
        proxies = get_proxy_dict() if PROXY_CONFIG['enabled'] else None
        
        for attempt in range(max_retries):
            try:
                # Use different proxy for each retry if available
                if PROXY_CONFIG['enabled'] and attempt > 0 and len(PROXY_CONFIG['fallback_proxies']) > 1:
                    proxies = get_proxy_dict(get_random_proxy())
                
                headers = get_instagram_headers(session_id)
                
                response = requests.get(
                    thumbnail_url, 
                    timeout=(10, 30),
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
                    # Final fallback attempt
                    try:
                        response = requests.get(
                            thumbnail_url, 
                            timeout=(5, 15),
                            headers={'User-Agent': get_random_user_agent()},
                            verify=False  # Less strict for fallback
                        )
                        response.raise_for_status()
                        break
                    except Exception as final_e:
                        return jsonify({
                            "error": f"Failed to fetch thumbnail. Service may be temporarily unavailable."
                        }), 500
                
                time.sleep(2)
        
        # Process thumbnail
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
                "timestamp": int(time.time()),
                "method": "yt-dlp" if "formats" in info else "fallback"
            }
            
            # Cache the result
            THUMBNAIL_CACHE[cache_key] = (result, time.time())
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({"error": f"Failed to process thumbnail: {str(e)}"}), 500

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["rate limit", "too many requests", "429"]):
            return jsonify({"error": "Instagram is rate limiting requests. Please wait a few minutes and try again."}), 429
        elif any(keyword in error_msg for keyword in ["blocked", "forbidden", "403"]):
            return jsonify({"error": "Access blocked by Instagram. This is common in deployed environments."}), 403
        elif any(keyword in error_msg for keyword in ["unavailable", "private", "not found", "login required"]):
            return jsonify({"error": "Content not available. May be private or require login."}), 404
        else:
            return jsonify({"error": f"Service temporarily unavailable: {str(e)}"}), 500

@app.route('/download-reel', methods=['POST'])
def download_reel():
    data = request.get_json()
    url = data.get("url")
    quality = data.get("quality", "best")
    
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    # Get client IP for rate limiting  
    client_ip = request.remote_addr or request.headers.get('X-Forwarded-For', 'unknown').split(',')[0]
    
    # Check rate limit
    if not check_rate_limit(client_ip):
        return jsonify({
            "error": f"Rate limit exceeded. Maximum {MAX_REQUESTS_PER_WINDOW} requests per {RATE_LIMIT_WINDOW} seconds."
        }), 429

    try:
        # Validate URL
        if not validate_instagram_url(url):
            return jsonify({"error": "Invalid Instagram URL format"}), 400
        
        # Get video info first (without cache for downloads)
        info = get_video_info_with_cache(url, use_cache=False)
        
        # Check video duration
        duration = info.get("duration", 0)
        if duration > 300:  # 5 minutes for deployed environments
            return jsonify({"error": "Video too long. Maximum duration is 5 minutes in deployed environment."}), 400
        
        # Select format
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
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["rate limit", "too many requests"]):
            return jsonify({"error": "Rate limited. Please wait before downloading more content."}), 429
        elif any(keyword in error_msg for keyword in ["blocked", "forbidden"]):
            return jsonify({"error": "Download blocked. Try again later or use a different method."}), 403
        elif any(keyword in error_msg for keyword in ["login required", "not available"]):
            return jsonify({"error": "Content requires authentication or is not available."}), 401
        else:
            return jsonify({"error": f"Download failed: {str(e)}"}), 500

def download_video_stream(url, format_selector):
    """Enhanced video download with better error handling for deployed environments"""
    # Apply request delay
    apply_request_delay()
    
    session_id = get_session_id()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        uid = str(uuid.uuid4())
        filename_template = os.path.join(temp_dir, f"{uid}.%(ext)s")
        
        # Enhanced yt-dlp options for deployment
        ydl_opts = {
            'outtmpl': filename_template,
            'format': format_selector,
            'quiet': True,
            'socket_timeout': 45,
            'retries': 5,
            'fragment_retries': 5,
            'http_headers': get_instagram_headers(session_id),
            'extractor_args': {
                'instagram': {
                    'comment_count': 0,
                    'like_count': 0
                }
            },
            'no_warnings': True,
            'ignoreerrors': True,
            'prefer_insecure': False  # Ensure HTTPS
        }
        
        # Add cookie configuration (deployment safe)
        try:
            cookie_opts = get_cookie_opts()
            ydl_opts.update(cookie_opts)
        except:
            pass
        
        # Add proxy configuration if enabled
        if PROXY_CONFIG['enabled'] and PROXY_CONFIG['fallback_proxies']:
            try:
                proxy_opts = get_ydl_proxy_opts()
                ydl_opts.update(proxy_opts)
            except:
                pass
        
        # Try download with multiple attempts
        attempts = 2 if PROXY_CONFIG['enabled'] else 1
        
        for attempt in range(attempts):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    downloaded_file = ydl.prepare_filename(info)
                
                # Verify file exists and has content
                if not os.path.exists(downloaded_file) or os.path.getsize(downloaded_file) == 0:
                    raise Exception("Download failed or file is empty")
                
                # Stream the file
                chunk_size = 8192
                with open(downloaded_file, 'rb') as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
                return
                
            except Exception as e:
                if attempt == attempts - 1:
                    # Final attempt without proxy
                    try:
                        ydl_opts_clean = {
                            'outtmpl': filename_template,
                            'format': format_selector,
                            'quiet': True,
                            'socket_timeout': 30,
                            'retries': 3,
                            'http_headers': get_instagram_headers(),
                            'no_warnings': True,
                            'ignoreerrors': True
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts_clean) as ydl:
                            info = ydl.extract_info(url, download=True)
                            downloaded_file = ydl.prepare_filename(info)
                        
                        if os.path.exists(downloaded_file) and os.path.getsize(downloaded_file) > 0:
                            chunk_size = 8192
                            with open(downloaded_file, 'rb') as f:
                                while True:
                                    chunk = f.read(chunk_size)
                                    if not chunk:
                                        break
                                    yield chunk
                            return
                    except:
                        pass
                
                # Wait before retry
                time.sleep(5)
        
        # If all attempts fail, return empty
        yield b''

@app.route('/get-reel-info', methods=['POST'])
def get_reel_info():
    """Get detailed reel information"""
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    # Rate limiting
    client_ip = request.remote_addr or request.headers.get('X-Forwarded-For', 'unknown').split(',')[0]
    
    if not check_rate_limit(client_ip):
        return jsonify({
            "error": f"Rate limit exceeded. Maximum {MAX_REQUESTS_PER_WINDOW} requests per {RATE_LIMIT_WINDOW} seconds."
        }), 429

    try:
        # Validate URL
        if not validate_instagram_url(url):
            return jsonify({"error": "Invalid Instagram URL format"}), 400
        
        info = get_video_info_with_cache(url)
        
        # Extract information with fallback values
        result = {
            "id": info.get("id", extract_shortcode_from_url(url) or "unknown"),
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
            ][:3],  # Limit to top 3 formats
            "timestamp": int(time.time()),
            "method": "yt-dlp" if "formats" in info else "fallback"
        }
        
        return jsonify(result)
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["rate limit", "too many requests"]):
            return jsonify({"error": "Rate limited. Please wait before making more requests."}), 429
        elif any(keyword in error_msg for keyword in ["blocked", "forbidden"]):
            return jsonify({"error": "Access blocked. This is common in deployed environments."}), 403
        else:
            return jsonify({"error": f"Failed to get info: {str(e)}"}), 500

@app.route('/cookie-config', methods=['GET'])
def get_cookie_config():
    """Get current cookie configuration"""
    return jsonify({
        "cookies_enabled": COOKIE_CONFIG['use_cookies'],
        "cookies_file": COOKIE_CONFIG['cookies_file'],
        "browser_cookies": COOKIE_CONFIG['browser_cookies'],
        "cookies_file_exists": os.path.exists(COOKIE_CONFIG['cookies_file']) if COOKIE_CONFIG['cookies_file'] else False
    })

@app.route('/cookie-config', methods=['POST'])
def update_cookie_config():
    """Update cookie configuration"""
    data = request.get_json()
    
    if 'use_cookies' in data:
        COOKIE_CONFIG['use_cookies'] = data['use_cookies']
    
    if 'cookies_file' in data:
        COOKIE_CONFIG['cookies_file'] = data['cookies_file']
    
    if 'browser_cookies' in data:
        COOKIE_CONFIG['browser_cookies'] = data['browser_cookies']
    
    return jsonify({"message": "Cookie configuration updated successfully"})

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
    """Enhanced health check with deployment environment detection"""
    is_deployed = bool(os.getenv('RENDER') or os.getenv('NETLIFY') or os.getenv('VERCEL') or os.getenv('HEROKU'))
    
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "environment": "deployed" if is_deployed else "local",
        "cache_stats": {
            "thumbnails_cached": len(THUMBNAIL_CACHE),
            "metadata_cached": len(METADATA_CACHE),
            "active_sessions": len(SESSIONS)
        },
        "proxy_config": {
            "enabled": PROXY_CONFIG['enabled'],
            "proxies_available": len(PROXY_CONFIG['fallback_proxies'])
        },
        "cookie_config": {
            "enabled": COOKIE_CONFIG['use_cookies'],
            "fallback_mode": COOKIE_CONFIG['fallback_mode']
        },
        "rate_limit_config": {
            "max_requests_per_window": MAX_REQUESTS_PER_WINDOW,
            "window_seconds": RATE_LIMIT_WINDOW,
            "request_delay": REQUEST_DELAY
        },
        "version": "2.3.0"
    })

@app.route('/clear-cache', methods=['POST'])
def clear_cache():
    """Clear all caches"""
    global THUMBNAIL_CACHE, METADATA_CACHE, REQUEST_TRACKER, SESSIONS
    THUMBNAIL_CACHE.clear()
    METADATA_CACHE.clear()
    REQUEST_TRACKER.clear()
    SESSIONS.clear()
    return jsonify({"message": "All caches cleared successfully"})

@app.route("/")
def root():
    is_deployed = bool(os.getenv('RENDER') or os.getenv('NETLIFY') or os.getenv('VERCEL'))
    
    return jsonify({
        "message": "Instagram Reel Downloader API - Deployment Optimized",
        "environment": "deployed" if is_deployed else "local",
        "endpoints": {
            "GET /health": "Health check",
            "POST /get-reel-thumbnail": "Get reel thumbnail",
            "POST /get-reel-info": "Get reel information", 
            "POST /download-reel": "Download reel",
            "POST /clear-cache": "Clear cache",
            "GET /proxy-config": "Get proxy configuration",
            "POST /proxy-config": "Update proxy configuration",
            "POST /test-proxy": "Test proxy connectivity",
            "GET /cookie-config": "Get cookie configuration",
            "POST /cookie-config": "Update cookie configuration"
        },
        "version": "2.3.0",
        "features": [
            "deployment_optimized",
            "fallback_extraction",
            "session_management", 
            "enhanced_rate_limiting",
            "multi_method_extraction",
            "deployment_environment_detection",
            "cookie_support",
            "proxy_support"
        ],
        "usage_notes": {
            "rate_limits": f"Max {MAX_REQUESTS_PER_WINDOW} requests per {RATE_LIMIT_WINDOW} seconds",
            "deployment": "Optimized for Netlify/Render deployment",
            "multiple_downloads": "Wait 8+ seconds between requests",
            "authentication": "Use cookies for private content"
        }
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