
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import shutil
import uuid
import base64
import requests
from threading import Thread
from time import sleep

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = "temp_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


@app.route('/get-reel-thumbnail', methods=['POST'])
def get_thumbnail():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        # Get JSON metadata using yt-dlp
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'force_generic_extractor': False
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            thumbnail_url = info.get("thumbnail", "")
            video_id = info.get("id", "unknown")

        # Fetch thumbnail image and encode as base64
        response = requests.get(thumbnail_url)
        response.raise_for_status()
        image_data = base64.b64encode(response.content).decode('utf-8')
        mime = response.headers.get("Content-Type", "image/jpeg")

        return jsonify({
            "shortcode": video_id,
            "thumbnail_url": thumbnail_url,
            "thumbnail_base64": f"data:{mime};base64,{image_data}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/download-reel', methods=['POST'])
def download_reel():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing 'url' in request"}), 400

    try:
        uid = str(uuid.uuid4())
        filename_template = os.path.join(DOWNLOAD_DIR, f"{uid}.%(ext)s")

        ydl_opts = {
            'outtmpl': filename_template,
            'format': 'mp4/best',
            'quiet': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = ydl.prepare_filename(info)

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
        return jsonify({"error": str(e)}), 500


@app.route("/")
def home():
    return jsonify({"message": "Instagram Reel Downloader is running"})


if __name__ == "__main__":
    app.run(debug=True)
