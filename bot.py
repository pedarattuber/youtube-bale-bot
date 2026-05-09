#!/usr/bin/env python3
"""
YouTube Downloader Bot for Bale
Uses yt-dlp with cookie support
Runs on Android / Windows / Linux / GitHub Actions
"""

import os
import io
import re
import sys
import json
import time
import glob
import tempfile
import zipfile
import traceback
import subprocess
from pathlib import Path
from datetime import datetime

import requests

# ==================== Configuration ====================
BOT_TOKEN = "535471620:niU3L-UZs9dFrT_vSPn_1mCPgQi1YdmtQxM"
CHUNK_SIZE = 19 * 1024 * 1024  # 19 MB
MAX_ITERATIONS = 30
BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# Cookie file path (put your YouTube cookies here)
COOKIE_FILE = Path.home() / ".youtube_cookies.txt"

# Offset file
OFFSET_FILE = Path.home() / ".youtube_bale_bot_offset.txt"

# Quality settings
VIDEO_QUALITY = "best[height<=1080]"  # Max 1080p
AUDIO_QUALITY = "bestaudio[ext=m4a]/bestaudio"  # Best audio

# ==================== YouTube URL Pattern ====================
YT_PATTERN = re.compile(
    r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)'
    r'[a-zA-Z0-9_-]{11}',
    re.I
)

# ==================== Logging ====================
def log(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}")
    sys.stdout.flush()

# ==================== Bale API ====================
def bale_api(method, payload=None, files=None):
    url = f"{BASE_URL}/{method}"
    try:
        if files:
            resp = requests.post(url, data=payload, files=files, timeout=180)
        else:
            resp = requests.post(url, json=payload, timeout=30)
        return resp.json()
    except Exception as e:
        log(f"Bale API Error [{method}]: {e}")
        return {"ok": False}

def send_message(chat_id, text):
    return bale_api("sendMessage", {"chat_id": str(chat_id), "text": text})

def send_document(chat_id, file_data, file_name, caption=""):
    try:
        if isinstance(file_data, (str, Path)):
            with open(str(file_data), "rb") as f:
                data = f.read()
        else:
            data = file_data
        
        files = {"document": (file_name, data, "application/octet-stream")}
        payload = {"chat_id": str(chat_id)}
        if caption:
            payload["caption"] = caption
        
        result = bale_api("sendDocument", payload=payload, files=files)
        return result.get("ok", False)
    except Exception as e:
        log(f"Send document error: {e}")
        return False

def send_video(chat_id, file_data, file_name, caption=""):
    """Send as video (not document) for better UX"""
    try:
        if isinstance(file_data, (str, Path)):
            with open(str(file_data), "rb") as f:
                data = f.read()
        else:
            data = file_data
        
        files = {"video": (file_name, data, "video/mp4")}
        payload = {
            "chat_id": str(chat_id),
            "supports_streaming": "true"
        }
        if caption:
            payload["caption"] = caption
        
        result = bale_api("sendVideo", payload=payload, files=files)
        if result.get("ok"):
            return True
        
        # Fallback to document if video fails
        log("sendVideo failed, trying sendDocument...")
        return send_document(chat_id, file_data, file_name, caption)
    except Exception as e:
        log(f"Send video error: {e}")
        return send_document(chat_id, file_data, file_name, caption)

def send_audio(chat_id, file_data, file_name, caption=""):
    """Send audio file"""
    try:
        if isinstance(file_data, (str, Path)):
            with open(str(file_data), "rb") as f:
                data = f.read()
        else:
            data = file_data
        
        files = {"audio": (file_name, data, "audio/mpeg")}
        payload = {"chat_id": str(chat_id)}
        if caption:
            payload["caption"] = caption
        
        result = bale_api("sendAudio", payload=payload, files=files)
        if result.get("ok"):
            return True
        
        return send_document(chat_id, file_data, file_name, caption)
    except Exception as e:
        log(f"Send audio error: {e}")
        return False

# ==================== Offset Management ====================
def get_offset():
    try:
        if OFFSET_FILE.exists():
            return int(OFFSET_FILE.read_text().strip())
    except:
        pass
    return 0

def save_offset(offset):
    try:
        OFFSET_FILE.write_text(str(offset))
    except Exception as e:
        log(f"Could not save offset: {e}")

# ==================== Temp Directory ====================
def get_temp_dir():
    try:
        temp_path = Path(tempfile.gettempdir()) / "yt_bale_bot"
        temp_path.mkdir(parents=True, exist_ok=True)
        test_file = temp_path / ".test"
        test_file.write_text("ok")
        test_file.unlink()
        return temp_path
    except:
        pass
    
    home_temp = Path.home() / ".yt_bale_bot_temp"
    home_temp.mkdir(parents=True, exist_ok=True)
    return home_temp

# ==================== yt-dlp Checker & Installer ====================
def ensure_ytdlp():
    """Check if yt-dlp is installed, install if not"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            log(f"yt-dlp version: {version}")
            return True
    except:
        pass
    
    log("yt-dlp not found. Installing...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "yt-dlp", "--quiet"],
            check=True, timeout=60
        )
        log("yt-dlp installed successfully")
        return True
    except Exception as e:
        log(f"Failed to install yt-dlp: {e}")
        return False

# ==================== YouTube Downloader ====================
class YouTubeDL:
    """YouTube downloader using yt-dlp with cookie support"""
    
    def __init__(self):
        self.temp_dir = get_temp_dir()
        log(f"Temp dir: {self.temp_dir}")
    
    def _cleanup(self):
        """Clean temp directory"""
        try:
            for f in self.temp_dir.iterdir():
                try:
                    if f.is_file():
                        f.unlink()
                    elif f.is_dir():
                        import shutil
                        shutil.rmtree(str(f), ignore_errors=True)
                except:
                    pass
        except Exception as e:
            log(f"Cleanup error: {e}")
    
    def _get_ydl_opts(self, output_template, audio_only=False):
        """Build yt-dlp options"""
        opts = {
            "outtmpl": str(output_template),
            "quiet": True,
            "no_warnings": True,
            "progress": False,
            "noplaylist": True,
            "extract_flat": False,
            "format_sort": ["res:1080", "codec:h264"],
        }
        
        # Cookie file
        if COOKIE_FILE.exists():
            opts["cookiefile"] = str(COOKIE_FILE)
            log(f"Using cookies from: {COOKIE_FILE}")
        else:
            log("No cookie file found, downloading without cookies")
        
        # Audio only
        if audio_only:
            opts["format"] = AUDIO_QUALITY
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
            }]
        else:
            opts["format"] = VIDEO_QUALITY
            opts["merge_output_format"] = "mp4"
        
        return opts
    
    def get_info(self, url):
        """Get video info without downloading"""
        try:
            from yt_dlp import YoutubeDL as YTDL
            
            opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
            }
            
            if COOKIE_FILE.exists():
                opts["cookiefile"] = str(COOKIE_FILE)
            
            with YTDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except Exception as e:
            log(f"Get info error: {e}")
            return None
    
    def download_video(self, url, audio_only=False):
        """Download video/audio from YouTube URL"""
        self._cleanup()
        
        try:
            from yt_dlp import YoutubeDL as YTDL
            
            # First get info
            info = self.get_info(url)
            if not info:
                return None, None
            
            title = info.get("title", "video")
            duration = info.get("duration", 0)
            uploader = info.get("uploader", "Unknown")
            
            # Sanitize filename
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:100]
            
            # Download
            output_template = self.temp_dir / f"{safe_title}.%(ext)s"
            opts = self._get_ydl_opts(str(output_template), audio_only)
            
            log(f"Downloading: {title} ({duration}s) by {uploader}")
            
            with YTDL(opts) as ydl:
                ydl.download([url])
            
            # Find downloaded files
            downloaded = list(self.temp_dir.glob(f"{safe_title}*"))
            downloaded = [f for f in downloaded if not f.name.endswith(('.part', '.ytdl', '.temp'))]
            
            if not downloaded:
                # Try wildcard search
                downloaded = list(self.temp_dir.glob("*"))
                downloaded = [f for f in downloaded if f.is_file() and f.suffix in ('.mp4', '.mkv', '.webm', '.m4a', '.mp3', '.opus')]
            
            if downloaded:
                file_path = downloaded[0]
                file_size = file_path.stat().st_size
                file_name = file_path.name
                
                log(f"Downloaded: {file_name} ({format_size(file_size)})")
                
                return {
                    "path": str(file_path),
                    "name": file_name,
                    "size": file_size,
                    "title": title,
                    "duration": duration,
                    "uploader": uploader,
                    "is_audio": audio_only
                }, info
            
            log("No files found after download")
            return None, info
            
        except Exception as e:
            log(f"Download error: {e}")
            traceback.print_exc()
            return None, None

# ==================== ZIP Chunking ====================
def split_into_chunks(file_path, file_name, chunk_size=CHUNK_SIZE):
    """Split file into ZIP chunks"""
    chunks = []
    
    with open(str(file_path), "rb") as f:
        data = f.read()
    
    total_size = len(data)
    total_chunks = max(1, (total_size + chunk_size - 1) // chunk_size)
    
    base_name = Path(file_name).stem
    ext = Path(file_name).suffix
    
    log(f"Splitting {format_size(total_size)} into {total_chunks} chunks")
    
    for i in range(total_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, total_size)
        chunk_data = data[start:end]
        
        chunk_zip_name = f"{base_name}.part{i+1}of{total_chunks}{ext}.zip"
        inner_name = f"{base_name}.part{i+1}of{total_chunks}{ext}"
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr(inner_name, chunk_data)
        
        chunks.append({
            "name": chunk_zip_name,
            "data": zip_buffer.getvalue(),
            "size": len(zip_buffer.getvalue())
        })
    
    return chunks

# ==================== Main Bot Logic ====================
def process_updates():
    offset = get_offset()
    
    params = {"offset": offset if offset > 0 else None, "timeout": 30, "limit": 10}
    params = {k: v for k, v in params.items() if v is not None}
    
    resp = bale_api("getUpdates", payload=params)
    
    if not resp.get("ok"):
        log(f"getUpdates failed: {resp}")
        return
    
    updates = resp.get("result", [])
    log(f"Processing {len(updates)} updates")
    
    ytdl = YouTubeDL()
    
    for upd in updates:
        update_id = upd.get("update_id", 0)
        message = upd.get("message") or upd.get("channel_post") or {}
        
        if not message:
            save_offset(update_id + 1)
            continue
        
        chat = message.get("chat", {})
        from_user = message.get("from", {})
        chat_id = chat.get("id") or from_user.get("id")
        
        if not chat_id:
            save_offset(update_id + 1)
            continue
        
        text = (message.get("text") or message.get("caption") or "").strip().lower()
        original_text = text  # Keep original for URL extraction
        
        log(f"From {chat_id}: {text[:100]}")
        
        # ==================== /start ====================
        if text == "/start":
            send_message(chat_id,
                "🎬 **YouTube Downloader Bot**\n\n"
                "🏷️ @PedaretUploader\n\n"
                "📌 **قابلیت‌ها:**\n"
                "• دانلود ویدیو (تا 1080p)\n"
                "• دانلود صوت (M4A)\n"
                "• پشتیبانی از Shorts\n"
                "• ویدیوهای بزرگ تکه‌تکه میشن\n\n"
                "🔗 **لینک قابل قبول:**\n"
                "• `youtube.com/watch?v=...`\n"
                "• `youtu.be/...`\n"
                "• `youtube.com/shorts/...`\n\n"
                "💡 **دستورات:**\n"
                f"• `/audio` + لینک = فقط صوت\n"
                f"• `/video` + لینک = فقط ویدیو\n"
                f"• لینک تنها = ویدیو + صوت"
            )
        
        # ==================== YouTube URL ====================
        elif text:
            url_match = YT_PATTERN.search(original_text)
            
            if url_match:
                url = url_match.group(0)
                
                # Detect audio command
                if text.startswith("/audio") or "صدا" in text or "audio" in text.lower():
                    audio_only = True
                    mode_text = "🎵 دانلود صوت"
                elif text.startswith("/video") or "ویدیو" in text or "video" in text.lower():
                    audio_only = False
                    mode_text = "🎬 دانلود ویدیو"
                else:
                    # Default: both video and audio
                    audio_only = False
                    mode_text = "🎬 دانلود"
                
                log(f"YouTube URL: {url} | Audio: {audio_only}")
                
                # Get info first
                info = ytdl.get_info(url)
                if info:
                    title = info.get("title", "Unknown")
                    duration = info.get("duration", 0)
                    duration_str = f"{duration//60}:{duration%60:02d}" if duration else "?"
                    uploader = info.get("uploader", "Unknown")
                    
                    send_message(chat_id,
                        f"{mode_text}\n\n"
                        f"📹 **{title}**\n"
                        f"👤 {uploader}\n"
                        f"⏱ {duration_str}\n\n"
                        f"⏳ در حال دانلود...")
                else:
                    send_message(chat_id, f"⏳ {mode_text}...")
                
                try:
                    # Download video
                    result, _ = ytdl.download_video(url, audio_only=audio_only)
                    
                    if not result:
                        # Try audio as fallback
                        if not audio_only:
                            send_message(chat_id, "⚠️ ویدیو دانلود نشد. دانلود صوت...")
                            result, _ = ytdl.download_video(url, audio_only=True)
                            if result:
                                result["is_audio"] = True
                    
                    if result:
                        file_path = result["path"]
                        file_name = result["name"]
                        file_size = result["size"]
                        is_audio = result["is_audio"]
                        title = result["title"]
                        
                        if file_size <= CHUNK_SIZE:
                            # Send directly
                            if is_audio:
                                send_message(chat_id, f"📤 ارسال صوت ({format_size(file_size)})...")
                                send_audio(chat_id, file_path, file_name,
                                    f"🎵 {title}\n👤 {result['uploader']}")
                            else:
                                send_message(chat_id, f"📤 ارسال ویدیو ({format_size(file_size)})...")
                                send_video(chat_id, file_path, file_name,
                                    f"🎬 {title}\n👤 {result['uploader']}")
                        else:
                            # Chunk it
                            send_message(chat_id,
                                f"📦 حجم: {format_size(file_size)}\n"
                                f"⏳ تکه‌تکه کردن...")
                            
                            chunks = split_into_chunks(file_path, file_name)
                            total_chunks = len(chunks)
                            
                            send_message(chat_id,
                                f"🔢 {total_chunks} بخش. ارسال شروع میشه...\n"
                                f"(ممکنه چند دقیقه طول بکشه)")
                            
                            all_sent = True
                            for ci, chunk in enumerate(chunks):
                                ok = send_document(chat_id,
                                    chunk["data"],
                                    chunk["name"],
                                    f"📤 {title}\nبخش {ci+1}/{total_chunks}")
                                if not ok:
                                    send_message(chat_id, f"❌ بخش {ci+1} ارسال نشد!")
                                    all_sent = False
                                    break
                                time.sleep(1.5)  # Rate limit
                            
                            if all_sent:
                                send_message(chat_id,
                                    f"✅ {title}\n"
                                    f"همه {total_chunks} بخش ارسال شد.\n\n"
                                    f"📌 **ترکیب:**\n"
                                    f"۱. همه ZIPها رو Extract کنین\n"
                                    f"۲. دستور:\n"
                                    f"`cat {Path(file_name).stem}.part*of{total_chunks}{Path(file_name).suffix} > {file_name}`")
                    else:
                        send_message(chat_id,
                            "❌ نتونستم دانلود کنم.\n\n"
                            "علت‌های احتمالی:\n"
                            "• ویدیو محدودیت سنی یا جغرافیایی داره\n"
                            "• ویدیو خصوصی یا حذف شده\n"
                            "• نیاز به کوکی (فایل cookie.txt رو اضافه کنین)\n\n"
                            "💡 برای ویدیوهای محدودشده، فایل کوکی یوتیوب رو کنار بات بذارین.")
                
                except Exception as e:
                    log(f"Download error: {traceback.format_exc()}")
                    send_message(chat_id, f"❌ خطا:\n{str(e)[:200]}")
            
            else:
                # Not a YouTube URL
                if text not in ("/start", "/audio", "/video"):
                    send_message(chat_id,
                        "🔗 لطفاً لینک یوتیوب بفرستید.\n\n"
                        "مثال:\n"
                        "• `https://youtube.com/watch?v=xxxxx`\n"
                        "• `https://youtu.be/xxxxx`\n\n"
                        "💡 `/start` برای راهنما")
        
        save_offset(update_id + 1)
    
    if updates:
        last_id = max(u.get("update_id", 0) for u in updates)
        save_offset(last_id + 1)
        log(f"Offset: {last_id + 1}")
    
    ytdl._cleanup()

# ==================== Utils ====================
def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes/(1024*1024):.1f} MB"
    else:
        return f"{size_bytes/(1024*1024*1024):.2f} GB"

def create_sample_cookie():
    """Create a sample cookie file if none exists"""
    if not COOKIE_FILE.exists():
        sample = (
            "# Netscape HTTP Cookie File\n"
            "# Put your YouTube cookies here\n"
            "# Export from browser using 'Get cookies.txt LOCALLY' extension\n"
            "# Or use: yt-dlp --cookies-from-browser BROWSER\n"
            "#\n"
            "# Format: domain\tflag\tpath\tsecure\texpiration\tname\tvalue\n"
        )
        try:
            COOKIE_FILE.write_text(sample)
            log(f"Sample cookie file created: {COOKIE_FILE}")
        except:
            pass

# ==================== Entry Point ====================
if __name__ == "__main__":
    log("=" * 60)
    log("🎬 YouTube Downloader Bot for Bale")
    log("=" * 60)
    log(f"Platform: {sys.platform}")
    log(f"Python: {sys.version}")
    log(f"Bot Token: {BOT_TOKEN[:10]}...{BOT_TOKEN[-5:]}")
    log(f"Cookie File: {COOKIE_FILE} {'✅' if COOKIE_FILE.exists() else '❌'}")
    log(f"Temp Dir: {get_temp_dir()}")
    log("=" * 60)
    
    # Ensure yt-dlp is installed
    if not ensure_ytdlp():
        log("❌ Cannot install yt-dlp. Exiting.")
        sys.exit(1)
    
    # Create sample cookie file
    create_sample_cookie()
    
    # Delete webhook (use long polling)
    bale_api("deleteWebhook")
    
    # Get bot info
    me = bale_api("getMe")
    if me.get("ok"):
        bot = me["result"]
        log(f"Bot: @{bot.get('username')} - {bot.get('first_name')}")
    
    # Main loop
    log(f"Starting polling ({MAX_ITERATIONS} iterations)...")
    
    for i in range(MAX_ITERATIONS):
        try:
            process_updates()
        except KeyboardInterrupt:
            log("Interrupted")
            break
        except Exception as e:
            log(f"Iteration {i+1} error: {e}")
            traceback.print_exc()
        
        if i < MAX_ITERATIONS - 1:
            time.sleep(3)
    
    log("Done!")
