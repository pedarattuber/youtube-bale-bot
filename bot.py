#!/usr/bin/env python3
"""
🎬 YouTube Downloader Bot for Bale
Based on: github.com/pedarattuber/sandbox workflow
Downloads YouTube videos using yt-dlp with quality selection
"""

import os
import io
import re
import sys
import json
import time
import base64
import shutil
import tempfile
import zipfile
import traceback
import subprocess
from pathlib import Path
from datetime import datetime

import requests

# ==================== Configuration ====================
BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN", "535471620:niU3L-UZs9dFrT_vSPn_1mCPgQi1YdmtQxM")
CHUNK_SIZE = 19 * 1024 * 1024  # 19 MB per chunk
MAX_ITERATIONS = 30
BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# Get YouTube cookies from environment variable (same as sandbox)
YOUTUBE_COOKIES = os.environ.get("YOUTUBE_COOKIES", "")

# Cookie file path
COOKIE_FILE = Path.home() / ".youtube_cookies.txt"
OFFSET_FILE = Path.home() / ".youtube_bale_bot_offset.txt"

# Default quality (like sandbox)
DEFAULT_QUALITY = "480p"

QUALITY_OPTIONS = {
    "2160p": "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best",
    "1440p": "bestvideo[height<=1440]+bestaudio/best[height<=1440]/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
    "audio": "bestaudio/best",
}

# ==================== URL Patterns ====================
YT_PATTERN = re.compile(
    r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)'
    r'[a-zA-Z0-9_-]{11}',
    re.I
)

# ==================== Logging ====================
def log(msg, level="INFO"):
    timestamp = datetime.now().strftime('%H:%M:%S')
    emoji = {"INFO": "📘", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "PROGRESS": "📊"}
    print(f"[{timestamp}] {emoji.get(level, '•')} {msg}")
    sys.stdout.flush()

# ==================== Temp Directory ====================
def get_temp_dir():
    """Get or create temp directory for downloads"""
    for path in [
        Path(tempfile.gettempdir()) / "yt_bale_bot",
        Path.home() / ".yt_bale_bot_temp",
        Path("yt_temp")
    ]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            (path / ".write_test").write_text("ok")
            return path
        except:
            continue
    # Last resort
    fallback = Path("yt_temp")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

# ==================== Cookie Setup ====================
def setup_cookies():
    """Setup cookie file from environment variable (like sandbox)"""
    if YOUTUBE_COOKIES and YOUTUBE_COOKIES.strip():
        try:
            COOKIE_FILE.write_text(YOUTUBE_COOKIES.strip())
            log(f"Cookies saved: {len(YOUTUBE_COOKIES)} chars", "SUCCESS")
            return True
        except Exception as e:
            log(f"Could not write cookies: {e}", "ERROR")
    
    if COOKIE_FILE.exists():
        content = COOKIE_FILE.read_text().strip()
        lines = [l for l in content.split('\n') if not l.startswith('#') and l.strip() and '\t' in l]
        if len(lines) >= 3:
            log(f"Cookies loaded: {len(lines)} entries", "SUCCESS")
            return True
    
    log("No cookies found - some videos may not download", "WARN")
    return False

# ==================== Bale API ====================
def call_bale_api(method, data=None, files=None, retries=3):
    """Call Bale Bot API with retry logic"""
    url = f"{BASE_URL}/{method}"
    
    for attempt in range(retries):
        try:
            if files:
                resp = requests.post(url, data=data, files=files, timeout=180)
            else:
                resp = requests.post(url, json=data, timeout=30)
            
            result = resp.json()
            
            if result.get("ok"):
                return result
            else:
                error_desc = result.get("description", "Unknown")
                if "too many" in str(error_desc).lower() or "retry" in str(error_desc).lower():
                    wait = (attempt + 1) * 3
                    log(f"Rate limited. Waiting {wait}s...", "WARN")
                    time.sleep(wait)
                    continue
                return result
                
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                log(f"API Error [{method}]: {e}", "ERROR")
                return {"ok": False}
    
    return {"ok": False}

def send_message(chat_id, text, reply_to=None):
    """Send text message. Automatically splits if > 4000 chars"""
    if len(text) <= 4000:
        payload = {"chat_id": str(chat_id), "text": text}
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        return call_bale_api("sendMessage", data=payload)
    
    # Split long messages
    parts = [text[i:i+3900] for i in range(0, len(text), 3900)]
    for i, part in enumerate(parts):
        prefix = f"📄 بخش {i+1}/{len(parts)}\n\n" if len(parts) > 1 else ""
        call_bale_api("sendMessage", data={
            "chat_id": str(chat_id),
            "text": prefix + part
        })
        if i < len(parts) - 1:
            time.sleep(0.5)

def edit_message(chat_id, message_id, text):
    """Edit existing message"""
    return call_bale_api("editMessageText", data={
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text
    })

def send_document(chat_id, file_data, file_name, caption="", reply_to=None):
    """Send document file"""
    try:
        if isinstance(file_data, (str, Path)):
            with open(str(file_data), "rb") as f:
                data = f.read()
        else:
            data = file_data
        
        files = {"document": (file_name, data, "application/octet-stream")}
        payload = {"chat_id": str(chat_id)}
        if caption:
            payload["caption"] = caption[:1024]
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        
        return call_bale_api("sendDocument", data=payload, files=files)
    except Exception as e:
        log(f"Send doc error: {e}", "ERROR")
        return {"ok": False}

def send_video(chat_id, file_data, file_name, caption="", reply_to=None):
    """Send video (with document fallback)"""
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
            payload["caption"] = caption[:1024]
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        
        result = call_bale_api("sendVideo", data=payload, files=files)
        if result.get("ok"):
            return result
        
        # Fallback to document
        log("Video send failed, trying document...", "WARN")
        return send_document(chat_id, file_data, file_name, caption, reply_to)
    except Exception as e:
        log(f"Send video error: {e}", "ERROR")
        return send_document(chat_id, file_data, file_name, caption, reply_to)

def send_audio_track(chat_id, file_data, file_name, caption="", reply_to=None):
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
            payload["caption"] = caption[:1024]
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        
        result = call_bale_api("sendAudio", data=payload, files=files)
        if result.get("ok"):
            return result
        return send_document(chat_id, file_data, file_name, caption, reply_to)
    except Exception as e:
        log(f"Send audio error: {e}", "ERROR")
        return {"ok": False}

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
    except:
        pass

# ==================== yt-dlp Setup ====================
def ensure_ytdlp():
    """Ensure yt-dlp is installed (auto-install if needed)"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            log(f"yt-dlp v{result.stdout.strip()}", "SUCCESS")
            return True
    except:
        pass
    
    log("Installing yt-dlp...", "INFO")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp", "--quiet"],
            check=True, timeout=120
        )
        log("yt-dlp installed", "SUCCESS")
        return True
    except Exception as e:
        log(f"Failed to install yt-dlp: {e}", "ERROR")
        return False

def check_ffmpeg():
    """Check if FFmpeg is available"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            log(f"FFmpeg: {version_line[:60]}...", "SUCCESS")
            return True
    except FileNotFoundError:
        pass
    except:
        pass
    
    log("FFmpeg not found - will try without it", "WARN")
    return False

# ==================== YouTube Downloader ====================
class YouTubeDownloader:
    """Download YouTube videos using yt-dlp (same logic as sandbox workflow)"""
    
    def __init__(self):
        self.temp_dir = get_temp_dir()
    
    def _cleanup(self):
        """Clean temp directory"""
        try:
            for item in self.temp_dir.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(str(item), ignore_errors=True)
                except:
                    pass
        except:
            pass
    
    def extract_video_id(self, url):
        """Extract YouTube video ID from URL"""
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
            r'^([a-zA-Z0-9_-]{11})$'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def get_video_info(self, url):
        """Get video info without downloading"""
        try:
            from yt_dlp import YoutubeDL
            
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "ignoreerrors": False,
            }
            
            if COOKIE_FILE.exists():
                opts["cookiefile"] = str(COOKIE_FILE)
            
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except Exception as e:
            log(f"Info extraction error: {e}", "ERROR")
            return None
    
    def download_video(self, url, quality=DEFAULT_QUALITY, progress_callback=None):
        """
        Download YouTube video
        quality: "480p", "720p", "1080p", "audio", etc.
        progress_callback: function(percent, status_text)
        """
        self._cleanup()
        
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError
            
            video_id = self.extract_video_id(url)
            if not video_id:
                return None, "Invalid YouTube URL"
            
            # Get video info first
            if progress_callback:
                progress_callback(5, "دریافت اطلاعات ویدیو...")
            
            info = self.get_video_info(url)
            if not info:
                return None, "Cannot access video (private/removed/geo-blocked)"
            
            title = info.get("title", "Unknown")
            duration = info.get("duration", 0) or 0
            uploader = info.get("uploader", "Unknown")
            
            # Sanitize filename
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:120]
            
            # Format selection (same logic as sandbox)
            is_audio = (quality == "audio")
            if is_audio:
                format_str = QUALITY_OPTIONS["audio"]
                ext = "m4a"
            else:
                format_str = QUALITY_OPTIONS.get(quality, QUALITY_OPTIONS[DEFAULT_QUALITY])
                ext = "mp4"
            
            output_template = str(self.temp_dir / f"{safe_title}.%(ext)s")
            
            # Build yt-dlp options (matching sandbox workflow)
            opts = {
                "outtmpl": output_template,
                "format": format_str,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "ignoreerrors": False,
                "retries": 5,
                "fragment_retries": 5,
                "extractor_retries": 3,
                "socket_timeout": 60,
                "merge_output_format": ext if not is_audio else None,
                "no_color": True,
            }
            
            # Post-processing for audio
            if is_audio:
                opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                }]
            
            # Cookies
            if COOKIE_FILE.exists():
                opts["cookiefile"] = str(COOKIE_FILE)
            
            # Progress hook
            class ProgressHook:
                def __init__(self, callback):
                    self.callback = callback
                    self.last_percent = 0
                
                def __call__(self, d):
                    if d.get("status") == "downloading":
                        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                        downloaded = d.get("downloaded_bytes", 0)
                        if total > 0:
                            percent = int((downloaded / total) * 90) + 5
                            percent = min(percent, 95)
                            if percent > self.last_percent + 4:
                                self.last_percent = percent
                                speed = d.get("speed") or 0
                                if speed:
                                    speed_str = self._format_speed(speed)
                                    status = f"دانلود... {percent}% | {speed_str}"
                                else:
                                    status = f"دانلود... {percent}%"
                                self.callback(percent, status)
                    elif d.get("status") == "finished":
                        self.callback(95, "پردازش نهایی...")
                
                def _format_speed(self, speed):
                    if speed > 1024 * 1024:
                        return f"{speed/(1024*1024):.1f} MB/s"
                    elif speed > 1024:
                        return f"{speed/1024:.0f} KB/s"
                    return f"{speed:.0f} B/s"
            
            opts["progress_hooks"] = [ProgressHook(progress_callback or (lambda p, s: None))]
            
            # Download
            if progress_callback:
                progress_callback(10, "شروع دانلود...")
            
            with YoutubeDL(opts) as ydl:
                try:
                    ydl.download([url])
                except DownloadError as e:
                    error_msg = str(e)
                    if "Video unavailable" in error_msg:
                        return None, "ویدیو در دسترس نیست (محدودیت سنی/جغرافیایی یا حذف شده)"
                    elif "Private video" in error_msg:
                        return None, "ویدیو خصوصی است"
                    elif "This video is not available" in error_msg:
                        return None, "ویدیو در کشور شما قابل دسترس نیست"
                    else:
                        return None, f"خطای دانلود: {error_msg[:200]}"
            
            # Find downloaded file
            if progress_callback:
                progress_callback(96, "یافتن فایل دانلود شده...")
            
            downloaded_files = []
            for pattern in [f"{safe_title}*.{ext}", f"{safe_title}*.*"]:
                downloaded_files = list(self.temp_dir.glob(pattern))
                if downloaded_files:
                    break
            
            if not downloaded_files:
                # Try broader search
                all_files = list(self.temp_dir.glob("*"))
                downloaded_files = [f for f in all_files if f.is_file() and not f.name.startswith('.')]
            
            if not downloaded_files:
                return None, "فایل دانلود شده یافت نشد"
            
            file_path = downloaded_files[0]
            file_size = file_path.stat().st_size
            
            if progress_callback:
                progress_callback(100, "✅ دانلود کامل شد")
            
            return {
                "path": str(file_path),
                "name": file_path.name,
                "size": file_size,
                "title": title,
                "duration": duration,
                "uploader": uploader,
                "is_audio": is_audio,
                "video_id": video_id,
                "quality": quality,
            }, None
            
        except Exception as e:
            log(f"Download exception: {traceback.format_exc()}", "ERROR")
            return None, f"خطای غیرمنتظره: {str(e)[:200]}"

# ==================== File Splitting ====================
def split_file_into_chunks(file_path, file_name, chunk_size=CHUNK_SIZE):
    """Split large file into ZIP chunks (store method)"""
    chunks = []
    
    with open(str(file_path), "rb") as f:
        data = f.read()
    
    total_size = len(data)
    total_chunks = max(1, (total_size + chunk_size - 1) // chunk_size)
    
    base_name = Path(file_name).stem
    ext = Path(file_name).suffix
    
    log(f"Splitting {format_size(total_size)} → {total_chunks} chunks", "INFO")
    
    for i in range(total_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, total_size)
        chunk_data = data[start:end]
        
        chunk_zip_name = f"{base_name}.part{i+1}of{total_chunks}{ext}.zip"
        inner_name = f"{base_name}.part{i+1}of{total_chunks}{ext}"
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr(inner_name, chunk_data)
        
        zip_data = zip_buffer.getvalue()
        
        chunks.append({
            "name": chunk_zip_name,
            "data": zip_data,
            "size": len(zip_data)
        })
    
    return chunks

# ==================== Progress Display ====================
def create_progress_bar(percent, width=16):
    """Create text progress bar"""
    filled = int(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {percent}%"

# ==================== Main Bot Logic ====================
class BaleYouTubeBot:
    """Main bot class"""
    
    def __init__(self):
        self.downloader = YouTubeDownloader()
        self.active_downloads = {}  # Track active downloads
    
    def process_updates(self):
        """Process new messages"""
        offset = get_offset()
        
        params = {
            "offset": offset if offset > 0 else None,
            "timeout": 30,
            "limit": 10
        }
        params = {k: v for k, v in params.items() if v is not None}
        
        result = call_bale_api("getUpdates", data=params)
        
        if not result.get("ok"):
            log(f"getUpdates failed: {result.get('description')}", "ERROR")
            return
        
        updates = result.get("result", [])
        if updates:
            log(f"📨 {len(updates)} new message(s)", "INFO")
        
        for upd in updates:
            update_id = upd.get("update_id", 0)
            message = upd.get("message") or upd.get("channel_post") or {}
            
            if not message:
                save_offset(update_id + 1)
                continue
            
            chat = message.get("chat", {})
            from_user = message.get("from", {})
            chat_id = chat.get("id") or from_user.get("id")
            message_id = message.get("message_id", 0)
            
            if not chat_id:
                save_offset(update_id + 1)
                continue
            
            text = (message.get("text") or message.get("caption") or "").strip()
            
            # ==================== Handle Commands ====================
            
            # /start
            if text == "/start":
                self._handle_start(chat_id, message_id)
            
            # /quality
            elif text.startswith("/quality") or text.startswith("/کیفیت"):
                self._handle_quality(chat_id, message_id)
            
            # /help
            elif text in ("/help", "/راهنما", "راهنما"):
                self._handle_help(chat_id, message_id)
            
            # /cookie
            elif text == "/cookie":
                self._handle_cookie_status(chat_id, message_id)
            
            # Text with YouTube URL
            elif text:
                self._handle_text(chat_id, message_id, text)
            
            save_offset(update_id + 1)
        
        if updates:
            last_id = max(u.get("update_id", 0) for u in updates)
            save_offset(last_id + 1)
    
    def _handle_start(self, chat_id, message_id):
        """Handle /start command"""
        welcome = (
            "🎬 **YouTube Downloader Bot**\n\n"
            "به ربات دانلودر یوتیوب خوش آمدید!\n\n"
            "📌 **قابلیت‌ها:**\n"
            "• دانلود ویدیو با کیفیت‌های مختلف\n"
            "• دانلود فقط صوت (M4A)\n"
            "• پشتیبانی از Shorts\n"
            "• نوار پیشرفت زنده\n"
            "• تکه‌تکه کردن خودکار فایل‌های بزرگ\n\n"
            "🔗 **لینک‌های قابل قبول:**\n"
            "• `youtube.com/watch?v=...`\n"
            "• `youtu.be/...`\n"
            "• `youtube.com/shorts/...`\n\n"
            "⚙️ **دستورات:**\n"
            "• `/quality` - تنظیم کیفیت پیش‌فرض\n"
            "• `/cookie` - وضعیت کوکی\n"
            "• `/help` - راهنما\n\n"
            "💬 **کافیه لینک رو بفرستی!**"
        )
        send_message(chat_id, welcome, reply_to=message_id)
    
    def _handle_help(self, chat_id, message_id):
        """Handle /help command"""
        help_text = (
            "📚 **راهنمای استفاده**\n\n"
            "۱. لینک یوتیوب رو مستقیم بفرست\n"
            "۲. یا با دستور کیفیت:\n"
            "   `1080p https://youtu.be/xxx`\n"
            "   `audio https://youtu.be/xxx`\n\n"
            "🎯 **کیفیت‌های موجود:**\n"
            "`audio` `360p` `480p` `720p` `1080p` `1440p` `2160p`\n\n"
            "⚙️ تنظیم کیفیت پیش‌فرض: `/quality`\n"
            "🍪 وضعیت کوکی: `/cookie`\n\n"
            "📦 فایل‌های > 19MB تکه‌تکه میشن"
        )
        send_message(chat_id, help_text, reply_to=message_id)
    
    def _handle_quality(self, chat_id, message_id):
        """Handle /quality command"""
        quality_text = (
            "⚙️ **تنظیم کیفیت دانلود**\n\n"
            "برای تنظیم کیفیت، یکی از گزینه‌های زیر رو انتخاب کن:\n\n"
            "🎵 `/set audio` - فقط صوت\n"
            "📱 `/set 360p` - کیفیت پایین\n"
            "📺 `/set 480p` - کیفیت متوسط\n"
            "🖥️ `/set 720p` - کیفیت خوب\n"
            "🎬 `/set 1080p` - کیفیت عالی\n\n"
            f"💡 کیفیت فعلی: **{DEFAULT_QUALITY}**"
        )
        send_message(chat_id, quality_text, reply_to=message_id)
    
    def _handle_cookie_status(self, chat_id, message_id):
        """Show cookie status"""
        if COOKIE_FILE.exists():
            content = COOKIE_FILE.read_text().strip()
            lines = [l for l in content.split('\n') if not l.startswith('#') and l.strip() and '\t' in l]
            status = f"✅ **کوکی فعال است**\n📊 {len(lines)} کوکی معتبر"
        else:
            status = "❌ **کوکی یافت نشد**\n⚠️ ویدیوهای محدودشده دانلود نمی‌شوند"
        send_message(chat_id, status, reply_to=message_id)
    
    def _handle_text(self, chat_id, message_id, text):
        """Handle text messages that may contain YouTube URLs"""
        
        # Check for quality prefix
        quality = DEFAULT_QUALITY
        for q in list(QUALITY_OPTIONS.keys()):
            if text.lower().startswith(q.lower()):
                quality = q
                text = text[len(q):].strip()
                break
        
        # Also check /set commands
        if text.startswith("/set"):
            parts = text.split()
            if len(parts) >= 2:
                q = parts[1].lower()
                if q in QUALITY_OPTIONS:
                    quality = q
                    send_message(chat_id, 
                        f"✅ کیفیت پیش‌فرض روی **{q}** تنظیم شد.\n"
                        f"حالا لینک رو بفرست.",
                        reply_to=message_id)
                    return
                else:
                    send_message(chat_id,
                        f"❌ کیفیت نامعتبر.\n"
                        f"گزینه‌ها: {', '.join(QUALITY_OPTIONS.keys())}",
                        reply_to=message_id)
                    return
        
        # Find YouTube URL
        url_match = YT_PATTERN.search(text)
        
        if url_match:
            url = url_match.group(0).rstrip(".,;:!?\"'")
            self._download_and_send(chat_id, message_id, url, quality)
        elif not text.startswith("/"):
            # Not a URL and not a command
            send_message(chat_id,
                "🔗 لطفاً لینک یوتیوب بفرستید.\n\n"
                "مثال:\n"
                "• `https://youtube.com/watch?v=xxxxx`\n"
                "• `https://youtu.be/xxxxx`\n\n"
                "💡 `/help` برای راهنما",
                reply_to=message_id)
    
    def _download_and_send(self, chat_id, message_id, url, quality):
        """Download video and send to user"""
        
        # Send initial status message
        quality_display = "🎵 صوت" if quality == "audio" else f"🎬 {quality}"
        status_msg = send_message(chat_id,
            f"{quality_display}\n"
            f"🔗 `{url}`\n\n"
            f"{create_progress_bar(0)}\n"
            f"⏳ دریافت اطلاعات...")
        
        if not status_msg.get("ok"):
            return
        
        status_message_id = status_msg["result"]["message_id"]
        
        # Progress callback
        start_time = time.time()
        def update_progress(percent, status_text):
            elapsed = int(time.time() - start_time)
            elapsed_str = f"{elapsed//60}:{elapsed%60:02d}"
            
            bar = create_progress_bar(percent)
            try:
                edit_message(chat_id, status_message_id,
                    f"{quality_display}\n"
                    f"🔗 `{url}`\n\n"
                    f"{bar}\n"
                    f"⚡ {status_text}\n"
                    f"⏱ {elapsed_str}")
            except:
                pass
        
        # Download
        result, error = self.downloader.download_video(url, quality, progress_callback=update_progress)
        
        if error:
            send_message(chat_id,
                f"❌ **خطا در دانلود**\n\n"
                f"🔗 `{url}`\n"
                f"📝 {error}\n\n"
                f"💡 نکات:\n"
                f"• ویدیوهای خصوصی/محدودشده نیاز به کوکی دارن\n"
                f"• با `/cookie` وضعیت کوکی رو ببین\n"
                f"• کیفیت‌های دیگه رو امتحان کن",
                reply_to=message_id)
            
            try:
                edit_message(chat_id, status_message_id, "❌ دانلود ناموفق بود")
            except:
                pass
            return
        
        if not result:
            send_message(chat_id,
                "❌ نتونستم فایل رو دانلود کنم.",
                reply_to=message_id)
            return
        
        # Update status
        update_progress(98, "📤 در حال ارسال...")
        
        file_path = result["path"]
        file_name = result["name"]
        file_size = result["size"]
        title = result["title"]
        is_audio = result["is_audio"]
        uploader = result["uploader"]
        duration = result["duration"]
        
        duration_str = f"{duration//60}:{duration%60:02d}" if duration else "?"
        
        # Caption for the file
        caption = (
            f"🎬 **{title}**\n"
            f"👤 {uploader}\n"
            f"⏱ {duration_str}\n"
            f"📦 {format_size(file_size)}"
        )
        
        if file_size <= CHUNK_SIZE:
            # Send directly
            update_progress(99, "📤 ارسال فایل...")
            
            if is_audio:
                send_audio_track(chat_id, file_path, file_name, caption=caption, reply_to=message_id)
            else:
                send_video(chat_id, file_path, file_name, caption=caption, reply_to=message_id)
            
            update_progress(100, "✅ ارسال شد!")
            
            try:
                edit_message(chat_id, status_message_id,
                    f"✅ **دانلود و ارسال موفق**\n\n"
                    f"🎬 {title}\n"
                    f"👤 {uploader}\n"
                    f"⏱ {duration_str}\n"
                    f"📦 {format_size(file_size)}\n"
                    f"🎯 {quality}")
            except:
                pass
        
        else:
            # Split into chunks
            update_progress(96, f"📦 تکه‌تکه کردن ({format_size(file_size)})...")
            
            chunks = split_file_into_chunks(file_path, file_name)
            total_chunks = len(chunks)
            
            try:
                edit_message(chat_id, status_message_id,
                    f"📦 حجم: {format_size(file_size)}\n"
                    f"🔢 {total_chunks} بخش\n"
                    f"📤 در حال ارسال...")
            except:
                pass
            
            send_message(chat_id,
                f"📦 **فایل بزرگ است** ({format_size(file_size)})\n"
                f"🔢 ارسال در {total_chunks} بخش شروع می‌شود...\n"
                f"⏳ لطفاً صبر کنید...",
                reply_to=message_id)
            
            all_sent = True
            for idx, chunk in enumerate(chunks):
                chunk_caption = (
                    f"📤 **{title}**\n"
                    f"📦 بخش {idx+1}/{total_chunks}\n"
                    f"💾 {format_size(chunk['size'])}"
                )
                result = send_document(chat_id, chunk["data"], chunk["name"], caption=chunk_caption)
                
                if not result.get("ok"):
                    send_message(chat_id, f"❌ ارسال بخش {idx+1} ناموفق بود!")
                    all_sent = False
                    break
                
                time.sleep(1)  # Rate limit
            
            if all_sent:
                send_message(chat_id,
                    f"✅ **همه {total_chunks} بخش ارسال شد**\n\n"
                    f"📌 **راهنمای ترکیب:**\n"
                    f"۱. همه فایل‌های `.zip` را دانلود کنید\n"
                    f"۲. همه را با هم Extract کنید\n"
                    f"۳. فایل‌های استخراج شده را با دستور زیر ترکیب کنید:\n\n"
                    f"`cat {Path(file_name).stem}.part*of{total_chunks}{Path(file_name).suffix} > {file_name}`\n\n"
                    f"🌐 یا از سایت:\n"
                    f"https://pedaret-uploader.pages.dev",
                    reply_to=message_id)
        
        # Cleanup
        self.downloader._cleanup()

# ==================== Utility Functions ====================
def format_size(size_bytes):
    """Format file size to human-readable format"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes/(1024*1024):.1f} MB"
    else:
        return f"{size_bytes/(1024*1024*1024):.2f} GB"

# ==================== Entry Point ====================
if __name__ == "__main__":
    log("=" * 60, "INFO")
    log("🎬 YouTube Downloader Bot for Bale", "INFO")
    log("=" * 60, "INFO")
    log(f"Platform: {sys.platform}", "INFO")
    log(f"Python: {sys.version.split()[0]}", "INFO")
    log(f"Bot Token: {BOT_TOKEN[:10]}...{BOT_TOKEN[-5:]}", "INFO")
    log(f"Default Quality: {DEFAULT_QUALITY}", "INFO")
    
    # Setup
    setup_cookies()
    check_ffmpeg()
    
    if not ensure_ytdlp():
        log("Cannot continue without yt-dlp", "ERROR")
        sys.exit(1)
    
    # Delete webhook (use long polling)
    call_bale_api("deleteWebhook")
    log("Using long polling mode", "INFO")
    
    # Get bot info
    me = call_bale_api("getMe")
    if me.get("ok"):
        bot_info = me["result"]
        log(f"Bot: @{bot_info.get('username')} - {bot_info.get('first_name')}", "SUCCESS")
    
    # Create bot instance
    bot = BaleYouTubeBot()
    
    # Main loop
    log(f"Starting polling loop ({MAX_ITERATIONS} iterations)...", "INFO")
    
    for i in range(MAX_ITERATIONS):
        try:
            bot.process_updates()
        except KeyboardInterrupt:
            log("Interrupted by user", "WARN")
            break
        except Exception as e:
            log(f"Iteration {i+1} error: {e}", "ERROR")
            traceback.print_exc()
        
        if i < MAX_ITERATIONS - 1:
            time.sleep(2)
    
    log("Bot stopped", "INFO")
