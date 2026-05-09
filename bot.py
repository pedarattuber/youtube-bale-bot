#!/usr/bin/env python3
"""
🎬 YouTube Downloader Bot for Bale (Fixed for Shorts & All Formats)
Based on: github.com/pedarattuber/sandbox workflow logic
"""

import os
import io
import re
import sys
import json
import time
import shutil
import tempfile
import zipfile
import traceback
import subprocess
from pathlib import Path
from datetime import datetime

import requests

# ==================== Configuration ====================
BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN", "535471620:niU3L-UZs9dFrT_vSPn_1mCPgQi1YdmtQxM").strip()
if not BOT_TOKEN:
    sys.exit("❌ BALE_BOT_TOKEN environment variable is required!")

CHUNK_SIZE = 19 * 1024 * 1024  # 19 MB
MAX_ITERATIONS = 30
BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

YOUTUBE_COOKIES = os.environ.get("YOUTUBE_COOKIES", "")
COOKIE_FILE = Path.home() / ".youtube_cookies.txt"
OFFSET_FILE = Path.home() / ".youtube_bale_bot_offset.txt"

DEFAULT_QUALITY = "480p"

# ==================== Quality Options (Fixed for Shorts compatibility) ====================
# The key fix: use "best" as fallback for each height limit
# This ensures Shorts and unusual formats are always downloadable
QUALITY_OPTIONS = {
    "2160p": "bestvideo[height<=2160]+bestaudio/best[height<=2160]/bestvideo[height<=2160]/best",
    "1440p": "bestvideo[height<=1440]+bestaudio/best[height<=1440]/bestvideo[height<=1440]/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/bestvideo[height<=1080]/best",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/bestvideo[height<=720]/best",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]/bestvideo[height<=480]/best",
    "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]/bestvideo[height<=360]/best",
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
    emoji = {"INFO": "📘", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "DEBUG": "🔍"}
    print(f"[{timestamp}] {emoji.get(level, '•')} {msg}")
    sys.stdout.flush()

# ==================== Temp Directory ====================
def get_temp_dir():
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
    return Path("yt_temp")

# ==================== Cookie Setup ====================
def setup_cookies():
    if YOUTUBE_COOKIES and YOUTUBE_COOKIES.strip():
        try:
            COOKIE_FILE.write_text(YOUTUBE_COOKIES.strip())
            log(f"Cookies saved: {len(YOUTUBE_COOKIES)} chars", "SUCCESS")
            return True
        except Exception as e:
            log(f"Cookie write error: {e}", "ERROR")
    
    if COOKIE_FILE.exists():
        content = COOKIE_FILE.read_text().strip()
        lines = [l for l in content.split('\n') if not l.startswith('#') and l.strip() and '\t' in l]
        if lines:
            log(f"Cookies from file: {len(lines)} entries", "SUCCESS")
            return True
    
    log("No cookies", "WARN")
    return False

# ==================== Bale API ====================
def test_bot_token():
    url = f"https://tapi.bale.ai/bot{BOT_TOKEN}/getMe"
    log(f"Testing token...", "DEBUG")
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                bot = data["result"]
                log(f"✅ Bot: @{bot.get('username')} - {bot.get('first_name')}", "SUCCESS")
                return True
        log(f"❌ Token invalid (HTTP {resp.status_code})", "ERROR")
    except Exception as e:
        log(f"Connection error: {e}", "ERROR")
    return False

def call_bale_api(method, data=None, files=None, retries=3):
    url = f"{BASE_URL}/{method}"
    for attempt in range(retries):
        try:
            if files:
                resp = requests.post(url, data=data, files=files, timeout=180)
            else:
                resp = requests.post(url, json=data, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if attempt < retries - 1:
                time.sleep(2)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
    return {"ok": False, "description": "Max retries"}

def send_message(chat_id, text, reply_to=None):
    if len(text) <= 4000:
        payload = {"chat_id": str(chat_id), "text": text}
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        return call_bale_api("sendMessage", data=payload)
    parts = [text[i:i+3900] for i in range(0, len(text), 3900)]
    for part in parts:
        call_bale_api("sendMessage", data={"chat_id": str(chat_id), "text": part})
        time.sleep(0.3)

def edit_message(chat_id, message_id, text):
    return call_bale_api("editMessageText", data={
        "chat_id": str(chat_id), "message_id": message_id, "text": text
    })

def send_document(chat_id, file_data, file_name, caption="", reply_to=None):
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
    try:
        if isinstance(file_data, (str, Path)):
            with open(str(file_data), "rb") as f:
                data = f.read()
        else:
            data = file_data
        files = {"video": (file_name, data, "video/mp4")}
        payload = {"chat_id": str(chat_id), "supports_streaming": "true"}
        if caption:
            payload["caption"] = caption[:1024]
        result = call_bale_api("sendVideo", data=payload, files=files)
        if result.get("ok"):
            return result
        return send_document(chat_id, file_data, file_name, caption, reply_to)
    except:
        return send_document(chat_id, file_data, file_name, caption, reply_to)

def send_audio_track(chat_id, file_data, file_name, caption="", reply_to=None):
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
        result = call_bale_api("sendAudio", data=payload, files=files)
        if result.get("ok"):
            return result
        return send_document(chat_id, file_data, file_name, caption, reply_to)
    except:
        return {"ok": False}

# ==================== Offset ====================
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

# ==================== yt-dlp & FFmpeg ====================
def ensure_ytdlp():
    try:
        result = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"],
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            log(f"yt-dlp v{result.stdout.strip()}", "SUCCESS")
            return True
    except:
        pass
    log("Installing yt-dlp...", "INFO")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp", "--quiet"],
                      check=True, timeout=120)
        return True
    except:
        return False

def check_ffmpeg():
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            log(f"FFmpeg: {result.stdout.split(chr(10))[0][:60]}...", "SUCCESS")
            return True
    except:
        pass
    log("No FFmpeg", "WARN")
    return False

# ==================== YouTube Downloader (Fixed) ====================
class YouTubeDownloader:
    def __init__(self):
        self.temp_dir = get_temp_dir()
    
    def _cleanup(self):
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
        match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})', url)
        return match.group(1) if match else None
    
    def get_video_info(self, url):
        """Get video info with flexible format detection"""
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
            log(f"Info error: {e}", "ERROR")
            return None
    
    def download_video(self, url, quality=DEFAULT_QUALITY, progress_callback=None):
        """
        Download YouTube video with auto-fallback for Shorts
        The key fix: if format fails, automatically try best-available format
        """
        self._cleanup()
        
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError
            
            video_id = self.extract_video_id(url)
            if not video_id:
                return None, "Invalid YouTube URL"
            
            if progress_callback:
                progress_callback(5, "دریافت اطلاعات...")
            
            # Try to get info
            info = self.get_video_info(url)
            if not info:
                return None, "ویدیو در دسترس نیست (ممکنه خصوصی یا حذف شده باشه)"
            
            title = info.get("title", "Unknown")
            duration = info.get("duration", 0) or 0
            uploader = info.get("uploader", "Unknown")
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:120]
            
            # Check if it's a Short
            is_short = "/shorts/" in url.lower()
            
            # Format selection
            is_audio = (quality == "audio")
            if is_audio:
                format_str = QUALITY_OPTIONS["audio"]
            else:
                format_str = QUALITY_OPTIONS.get(quality, QUALITY_OPTIONS[DEFAULT_QUALITY])
                
                # For Shorts, use a more flexible format selection
                if is_short:
                    log(f"Detected Shorts video, using flexible format", "DEBUG")
                    # For Shorts: prefer vertical video, fall back to best
                    format_str = f"best[height<={get_quality_height(quality)}]/best"
            
            ext = "m4a" if is_audio else "mp4"
            output_template = str(self.temp_dir / f"{safe_title}.%(ext)s")
            
            # Build options
            opts = {
                "outtmpl": output_template,
                "format": format_str,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "ignoreerrors": False,
                "retries": 10,
                "fragment_retries": 10,
                "extractor_retries": 5,
                "socket_timeout": 60,
                "merge_output_format": ext if not is_audio else None,
                "allow_unplayable_formats": True,  # Allow any format
                "format_sort": ["res", "codec:h264"],  # Prefer H.264 for compatibility
            }
            
            if is_audio:
                opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
            
            if COOKIE_FILE.exists():
                opts["cookiefile"] = str(COOKIE_FILE)
            
            # Progress hook
            if progress_callback:
                last_percent = [0]
                def hook(d):
                    if d.get("status") == "downloading":
                        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                        if total > 0:
                            pct = min(int((d.get("downloaded_bytes", 0) / total) * 90) + 5, 95)
                            if pct > last_percent[0] + 4:
                                last_percent[0] = pct
                                speed = d.get("speed") or 0
                                if speed > 1024*1024:
                                    speed_str = f"{speed/1024/1024:.1f} MB/s"
                                elif speed > 1024:
                                    speed_str = f"{speed/1024:.0f} KB/s"
                                else:
                                    speed_str = ""
                                progress_callback(pct, f"دانلود... {speed_str}")
                    elif d.get("status") == "finished":
                        progress_callback(95, "پردازش نهایی...")
                opts["progress_hooks"] = [hook]
            
            # Download with auto-fallback logic
            if progress_callback:
                progress_callback(10, "شروع دانلود...")
            
            download_success = False
            last_error = None
            
            # Try 1: User's preferred format
            try:
                with YoutubeDL(opts) as ydl:
                    ydl.download([url])
                download_success = True
            except DownloadError as e:
                last_error = str(e)
                log(f"First attempt failed: {last_error[:200]}", "WARN")
                
                # Try 2: Fallback to best available format
                if "Requested format is not available" in last_error or "format" in last_error.lower():
                    log("Trying fallback: best format...", "WARN")
                    if progress_callback:
                        progress_callback(15, "تلاش مجدد با فرمت جایگزین...")
                    
                    opts["format"] = "best[ext=mp4]/best"
                    if is_audio:
                        opts["format"] = "bestaudio/best"
                    
                    try:
                        with YoutubeDL(opts) as ydl:
                            ydl.download([url])
                        download_success = True
                        log("Fallback format succeeded!", "SUCCESS")
                    except DownloadError as e2:
                        last_error = str(e2)
                        log(f"Fallback also failed: {last_error[:200]}", "ERROR")
            
            if not download_success:
                return None, f"فرمت درخواستی موجود نیست: {last_error[:150]}"
            
            # Find downloaded file
            downloaded = list(self.temp_dir.glob(f"{safe_title}*.{ext}"))
            if not downloaded:
                downloaded = list(self.temp_dir.glob(f"{safe_title}*.*"))
            if not downloaded:
                downloaded = [f for f in self.temp_dir.glob("*") if f.is_file() and not f.name.startswith('.')]
            
            if not downloaded:
                return None, "فایل دانلود شده یافت نشد"
            
            file_path = downloaded[0]
            file_size = file_path.stat().st_size
            
            if progress_callback:
                progress_callback(100, "✅ کامل شد")
            
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

def get_quality_height(quality_str):
    """Extract height from quality string"""
    return int(quality_str.replace("p", "")) if quality_str != "audio" else 0

# ==================== File Splitting ====================
def split_file_into_chunks(file_path, file_name, chunk_size=CHUNK_SIZE):
    chunks = []
    with open(str(file_path), "rb") as f:
        data = f.read()
    
    total = len(data)
    total_chunks = max(1, (total + chunk_size - 1) // chunk_size)
    base = Path(file_name).stem
    ext = Path(file_name).suffix
    
    for i in range(total_chunks):
        chunk_data = data[i*chunk_size:(i+1)*chunk_size]
        zip_name = f"{base}.part{i+1}of{total_chunks}{ext}.zip"
        inner_name = f"{base}.part{i+1}of{total_chunks}{ext}"
        
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr(inner_name, chunk_data)
        
        chunks.append({"name": zip_name, "data": buf.getvalue(), "size": len(buf.getvalue())})
    
    return chunks

# ==================== Progress Bar ====================
def create_progress_bar(percent, width=14):
    filled = int(width * percent / 100)
    return f"[{'█'*filled}{'░'*(width-filled)}] {percent}%"

# ==================== Main Bot ====================
class BaleYouTubeBot:
    def __init__(self):
        self.downloader = YouTubeDownloader()
    
    def process_updates(self):
        offset = get_offset()
        params = {"timeout": 30, "limit": 10}
        if offset > 0:
            params["offset"] = str(offset)
        
        result = call_bale_api("getUpdates", data=params)
        
        if not result.get("ok"):
            return
        
        updates = result.get("result", [])
        if updates:
            log(f"📨 {len(updates)} message(s)", "INFO")
        
        for upd in updates:
            update_id = upd.get("update_id", 0)
            msg = upd.get("message") or upd.get("channel_post") or {}
            
            if not msg:
                save_offset(update_id + 1)
                continue
            
            chat = msg.get("chat", {}) or {}
            chat_id = chat.get("id") or (msg.get("from", {}) or {}).get("id")
            message_id = msg.get("message_id", 0)
            
            if not chat_id:
                save_offset(update_id + 1)
                continue
            
            text = (msg.get("text") or msg.get("caption") or "").strip()
            
            # Commands
            if text == "/start":
                send_message(chat_id,
                    "🎬 **YouTube Downloader Bot**\n\n"
                    "🔗 لینک یوتیوب، Shorts، یا youtu.be بفرست\n\n"
                    "🎯 **انتخاب کیفیت:**\n"
                    "• `360p لینک` - `480p لینک` - `720p لینک` - `1080p لینک`\n"
                    "• `audio لینک` - فقط صوت\n\n"
                    "⚡ Shorts خودکار تشخیص داده میشه\n"
                    "📦 >19MB تکه‌تکه ارسال میشه\n\n"
                    "💡 `/help` راهنما | `/quality` کیفیت‌ها",
                    reply_to=message_id)
            
            elif text in ("/quality", "/کیفیت"):
                send_message(chat_id,
                    "⚙️ **کیفیت‌های موجود:**\n\n"
                    "🎵 `audio` - فقط صوت (کمترین حجم)\n"
                    "📱 `360p` - حجم کم، سریع\n"
                    "📺 `480p` - متوسط (پیش‌فرض)\n"
                    "🖥️ `720p` - خوب\n"
                    "🎬 `1080p` - عالی\n"
                    "🎥 `1440p` - خیلی عالی\n"
                    "📽️ `2160p` - 4K\n\n"
                    f"💡 فعلی: **{DEFAULT_QUALITY}**",
                    reply_to=message_id)
            
            elif text == "/cookie":
                if COOKIE_FILE.exists():
                    lines = [l for l in COOKIE_FILE.read_text().split('\n') if not l.startswith('#') and l.strip()]
                    send_message(chat_id, f"✅ کوکی فعال: {len(lines)} خط", reply_to=message_id)
                else:
                    send_message(chat_id, "❌ کوکی یافت نشد", reply_to=message_id)
            
            elif text in ("/help", "/راهنما"):
                send_message(chat_id,
                    "📚 **راهنما**\n\n"
                    "۱. لینک رو بفرست (معمولی یا Shorts)\n"
                    "۲. یا با کیفیت: `720p لینک`\n"
                    "۳. یا برای صوت: `audio لینک`\n\n"
                    "✅ Shorts خودکار تشخیص داده میشه\n"
                    "✅ فرمت‌های نامعتبر خودکار جایگزین میشن\n\n"
                    "📦 فایل‌های >۱۹MB تکه‌تکه میشن\n\n"
                    "👨‍💻 @PedaretUploader",
                    reply_to=message_id)
            
            elif text:
                # Parse quality prefix and URL
                quality = DEFAULT_QUALITY
                remaining = text
                
                for q in QUALITY_OPTIONS:
                    if remaining.lower().startswith(q.lower()):
                        quality = q
                        remaining = remaining[len(q):].strip()
                        break
                
                url_match = YT_PATTERN.search(remaining)
                
                if url_match:
                    url = url_match.group(0).rstrip(".,;:!?\"'")
                    self._download_and_send(chat_id, message_id, url, quality)
                elif not text.startswith("/"):
                    send_message(chat_id,
                        "🔗 لطفاً لینک یوتیوب بفرستید.\n\n"
                        "✅ `youtube.com/watch?v=...`\n"
                        "✅ `youtu.be/...`\n"
                        "✅ `youtube.com/shorts/...`\n\n"
                        "💡 `/help`",
                        reply_to=message_id)
            
            save_offset(update_id + 1)
        
        if updates:
            save_offset(max(u["update_id"] for u in updates) + 1)
    
    def _download_and_send(self, chat_id, message_id, url, quality):
        q_display = "🎵 صوت" if quality == "audio" else f"🎬 {quality}"
        
        status = send_message(chat_id,
            f"{q_display}\n🔗 `{url}`\n\n{create_progress_bar(0)}\n⏳ دریافت اطلاعات...")
        
        if not status.get("ok"):
            return
        
        status_msg_id = status["result"]["message_id"]
        start_time = time.time()
        
        def progress(pct, txt):
            bar = create_progress_bar(pct)
            elapsed = int(time.time() - start_time)
            try:
                edit_message(chat_id, status_msg_id,
                    f"{q_display}\n🔗 `{url}`\n\n{bar}\n⚡ {txt}\n⏱ {elapsed}s")
            except:
                pass
        
        result, error = self.downloader.download_video(url, quality, progress_callback=progress)
        
        if error:
            send_message(chat_id, f"❌ {error}\n\n🔗 `{url}`", reply_to=message_id)
            try:
                edit_message(chat_id, status_msg_id, f"❌ ناموفق: {error[:100]}")
            except:
                pass
            return
        
        if not result:
            return
        
        file_path = result["path"]
        file_name = result["name"]
        file_size = result["size"]
        title = result["title"]
        is_audio = result["is_audio"]
        duration = result["duration"]
        dur_str = f"{duration//60}:{duration%60:02d}" if duration else "?"
        
        caption = f"🎬 {title}\n👤 {result['uploader']}\n⏱ {dur_str}\n📦 {format_size(file_size)}"
        
        if file_size <= CHUNK_SIZE:
            progress(99, "📤 ارسال...")
            if is_audio:
                send_audio_track(chat_id, file_path, file_name, caption, reply_to=message_id)
            else:
                send_video(chat_id, file_path, file_name, caption, reply_to=message_id)
            
            try:
                edit_message(chat_id, status_msg_id, f"✅ ارسال شد!\n🎬 {title}\n📦 {format_size(file_size)}")
            except:
                pass
        else:
            chunks = split_file_into_chunks(file_path, file_name)
            total = len(chunks)
            
            try:
                edit_message(chat_id, status_msg_id, f"📦 {format_size(file_size)}\n🔢 {total} بخش")
            except:
                pass
            
            send_message(chat_id, f"📦 حجم بالاست. ارسال {total} بخش...", reply_to=message_id)
            
            for i, chunk in enumerate(chunks):
                send_document(chat_id, chunk["data"], chunk["name"],
                    f"📤 {title}\nبخش {i+1}/{total}")
                time.sleep(1)
            
            send_message(chat_id,
                f"✅ {total} بخش ارسال شد\n\n"
                f"📌 ترکیب با دستور:\n"
                f"`cat {Path(file_name).stem}.part*of{total}{Path(file_name).suffix} > {file_name}`\n\n"
                f"🌐 یا سایت: https://pedaret-uploader.pages.dev",
                reply_to=message_id)
        
        self.downloader._cleanup()

def format_size(s):
    if s < 1024: return f"{s} B"
    elif s < 1024*1024: return f"{s/1024:.1f} KB"
    elif s < 1024*1024*1024*1: return f"{s/(1024*1024):.1f} MB"
    return f"{s/(1024*1024*1024):.2f} GB"

# ==================== Entry Point ====================
if __name__ == "__main__":
    log("=" * 60)
    log("🎬 YouTube Downloader Bot for Bale (Shorts Fixed)")
    log("=" * 60)
    log(f"Token: {BOT_TOKEN[:8]}...{BOT_TOKEN[-4:]}", "INFO")
    
    if not test_bot_token():
        sys.exit(1)
    
    setup_cookies()
    check_ffmpeg()
    
    if not ensure_ytdlp():
        sys.exit(1)
    
    call_bale_api("deleteWebhook")
    log("Long polling mode", "INFO")
    
    bot = BaleYouTubeBot()
    
    for i in range(MAX_ITERATIONS):
        try:
            bot.process_updates()
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"Iteration {i+1}: {e}", "ERROR")
        
        if i < MAX_ITERATIONS - 1:
            time.sleep(2)
    
    log("Done!", "SUCCESS")
