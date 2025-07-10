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

app = Flask(__name__)
CORS(app)

# Global cache for thumbnails and metadata (in-memory for serverless)
THUMBNAIL_CACHE = {}
METADATA_CACHE = {}
CACHE_DURATION = 3600  # 1 hour

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

def get_video_info_with_cache(url):
    """Get video info with caching to avoid repeated yt-dlp calls"""
    cache_key = get_cache_key(url)
    
    # Check cache first
    if cache_key in METADATA_CACHE:
        cached_data, timestamp = METADATA_CACHE[cache_key]
        if is_cache_valid(timestamp):
            return cached_data
    
    # If not in cache or expired, fetch new data
    try:
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'force_generic_extractor': False,
            'socket_timeout': 10,
            'retries': 2
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        # Cache the result
        METADATA_CACHE[cache_key] = (info, time.time())
        return info
        
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

        # Fetch thumbnail with timeout and retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    thumbnail_url, 
                    timeout=10,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                )
                response.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    return jsonify({"error": f"Failed to fetch thumbnail after {max_retries} attempts"}), 500
                time.sleep(1)  # Brief delay before retry
        
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
        return jsonify({"error": f"Failed to get thumbnail: {error_msg}"}), 500

@app.route('/download-reel', methods=['POST'])
def download_reel():
    data = request.get_json()
    url = data.get("url")
    quality = data.get("quality", "best")  # Allow quality selection
    
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
        return jsonify({"error": f"Download failed: {error_msg}"}), 500

def download_video_stream(url, format_selector):
    """Stream video download to avoid memory issues"""
    with tempfile.TemporaryDirectory() as temp_dir:
        uid = str(uuid.uuid4())
        filename_template = os.path.join(temp_dir, f"{uid}.%(ext)s")
        
        ydl_opts = {
            'outtmpl': filename_template,
            'format': format_selector,
            'quiet': True,
            'socket_timeout': 15,
            'retries': 2,
            'fragment_retries': 3
        }
        
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

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "cache_stats": {
            "thumbnails_cached": len(THUMBNAIL_CACHE),
            "metadata_cached": len(METADATA_CACHE)
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
        "message": "Instagram Reel Downloader API",
        "endpoints": {
            "GET /health": "Health check",
            "POST /get-reel-thumbnail": "Get reel thumbnail",
            "POST /get-reel-info": "Get reel information",
            "POST /download-reel": "Download reel (supports quality parameter)",
            "POST /clear-cache": "Clear cache"
        },
        "version": "2.0",
        "features": ["streaming", "caching", "timeout_handling", "rate_limit_handling"]
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
    app.run(debug=True)