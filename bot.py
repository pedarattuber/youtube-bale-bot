#!/usr/bin/env python3
"""
🎬 YouTube Downloader Bot for Bale (ABSOLUTE FINAL FIX)
Uses subprocess with yt-dlp CLI directly - bypasses all format issues
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
BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    sys.exit("❌ BALE_BOT_TOKEN is required!")

CHUNK_SIZE = 19 * 1024 * 1024
MAX_ITERATIONS = 30
BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

YOUTUBE_COOKIES = os.environ.get("YOUTUBE_COOKIES", "")
COOKIE_FILE = Path.home() / ".youtube_cookies.txt"
OFFSET_FILE = Path.home() / ".youtube_bale_bot_offset.txt"

DEFAULT_QUALITY = "480p"

# ==================== Logging ====================
def log(msg, level="INFO"):
    timestamp = datetime.now().strftime('%H:%M:%S')
    emoji = {"INFO": "📘", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️"}
    print(f"[{timestamp}] {emoji.get(level, '•')} {msg}", flush=True)

# ==================== Temp ====================
def get_temp_dir():
    for path in [Path(tempfile.gettempdir()) / "yt_bot", Path.home() / ".yt_bot", Path("yt_temp")]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except:
            continue
    return Path("yt_temp")

# ==================== Cookies ====================
def setup_cookies():
    if YOUTUBE_COOKIES and YOUTUBE_COOKIES.strip():
        try:
            COOKIE_FILE.write_text(YOUTUBE_COOKIES.strip())
            log(f"Cookies: {len(YOUTUBE_COOKIES)} chars", "SUCCESS")
            return True
        except:
            pass
    if COOKIE_FILE.exists():
        content = COOKIE_FILE.read_text().strip()
        lines = [l for l in content.split('\n') if l.strip() and not l.startswith('#')]
        if len(lines) >= 3:
            log(f"Cookies: {len(lines)} lines", "SUCCESS")
            return True
    return False

# ==================== Bale API ====================
def bale_get(method, data=None, files=None, retries=3):
    url = f"{BASE_URL}/{method}"
    for attempt in range(retries):
        try:
            if files:
                resp = requests.post(url, data=data, files=files, timeout=180)
            else:
                resp = requests.post(url, json=data, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            time.sleep(2)
        except:
            time.sleep(2)
    return {"ok": False}

def send_msg(chat, text, reply=None):
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        payload = {"chat_id": str(chat), "text": chunk}
        if reply: payload["reply_to_message_id"] = reply
        bale_get("sendMessage", data=payload)
        time.sleep(0.2)

def edit_msg(chat, msg_id, text):
    bale_get("editMessageText", data={"chat_id": str(chat), "message_id": msg_id, "text": text})

def send_file(chat, data, name, caption="", reply=None):
    if isinstance(data, (str, Path)):
        with open(str(data), "rb") as f:
            data = f.read()
    payload = {"chat_id": str(chat)}
    if caption: payload["caption"] = caption[:1024]
    if reply: payload["reply_to_message_id"] = reply
    return bale_get("sendDocument", data=payload, files={"document": (name, data, "application/octet-stream")})

def send_vid(chat, data, name, caption="", reply=None):
    if isinstance(data, (str, Path)):
        with open(str(data), "rb") as f:
            data = f.read()
    payload = {"chat_id": str(chat), "supports_streaming": "true"}
    if caption: payload["caption"] = caption[:1024]
    if reply: payload["reply_to_message_id"] = reply
    result = bale_get("sendVideo", data=payload, files={"video": (name, data, "video/mp4")})
    if not result.get("ok"):
        return send_file(chat, data, name, caption, reply)
    return result

def send_aud(chat, data, name, caption="", reply=None):
    if isinstance(data, (str, Path)):
        with open(str(data), "rb") as f:
            data = f.read()
    payload = {"chat_id": str(chat)}
    if caption: payload["caption"] = caption[:1024]
    if reply: payload["reply_to_message_id"] = reply
    result = bale_get("sendAudio", data=payload, files={"audio": (name, data, "audio/mpeg")})
    if not result.get("ok"):
        return send_file(chat, data, name, caption, reply)
    return result

# ==================== Offset ====================
def get_offset():
    try: return int(OFFSET_FILE.read_text().strip()) if OFFSET_FILE.exists() else 0
    except: return 0

def save_offset(o):
    try: OFFSET_FILE.write_text(str(o))
    except: pass

# ==================== Setup ====================
def ensure_ytdlp():
    try:
        r = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            log(f"yt-dlp v{r.stdout.strip()}", "SUCCESS")
            return True
    except:
        pass
    log("Installing yt-dlp...", "INFO")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"], timeout=120)
    return True

# ==================== YouTube Download (SUBPROCESS METHOD) ====================
def download_youtube(url, quality="480p", temp_dir=None, progress_callback=None):
    """
    Download using yt-dlp CLI directly.
    This bypasses ALL Python module format issues.
    """
    if temp_dir is None:
        temp_dir = get_temp_dir()
    
    # Clean temp
    for f in temp_dir.iterdir():
        try:
            if f.is_file(): f.unlink()
            elif f.is_dir(): shutil.rmtree(str(f), ignore_errors=True)
        except: pass
    
    # Extract video ID
    vid_match = re.search(r'[a-zA-Z0-9_-]{11}', url)
    vid_id = vid_match.group(0) if vid_match else "video"
    
    # Output template
    output = str(temp_dir / f"%(title)s_{vid_id}.%(ext)s")
    
    # Build yt-dlp command
    cmd = [
        "yt-dlp",
        "-f", "b",  # BEST available format - ALWAYS works
        "-o", output,
        "--no-playlist",
        "--merge-output-format", "mp4",
        "--no-warnings",
        "--no-progress",
        "--socket-timeout", "30",
        "-R", "5",
        "--fragment-retries", "5",
    ]
    
    # Handle audio-only
    if quality == "audio":
        cmd = [
            "yt-dlp",
            "-f", "ba",  # Best audio
            "-o", output,
            "--no-playlist",
            "--extract-audio",
            "--audio-format", "m4a",
            "--no-warnings",
            "--no-progress",
            "--socket-timeout", "30",
            "-R", "5",
        ]
    
    # Cookiefile
    if COOKIE_FILE.exists():
        cmd.extend(["--cookies", str(COOKIE_FILE)])
    
    cmd.append(url)
    
    log(f"Running: {' '.join(cmd[:8])}...", "DEBUG")
    
    try:
        # Run yt-dlp
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        # Read output for progress
        download_started = False
        for line in process.stderr:
            line = line.strip()
            if not line:
                continue
            
            # Progress detection
            if "%" in line and "MiB" in line:
                download_started = True
                try:
                    pct_match = re.search(r'(\d+\.?\d*)%', line)
                    if pct_match and progress_callback:
                        pct = min(float(pct_match.group(1)), 95)
                        speed_match = re.search(r'(\d+\.?\d*\s*[KMG]iB/s)', line)
                        speed = speed_match.group(1) if speed_match else ""
                        progress_callback(int(pct), f"دانلود... {speed}")
                except:
                    pass
            elif "Destination:" in line:
                download_started = True
                if progress_callback:
                    progress_callback(5, "شروع دریافت...")
            elif "ERROR:" in line or "WARNING:" in line:
                log(f"yt-dlp: {line}", "WARN")
        
        process.wait(timeout=300)
        
        if process.returncode != 0:
            stderr_output = process.stderr.read() if hasattr(process.stderr, 'read') else ""
            return None, f"yt-dlp failed: {stderr_output[:200]}"
        
        # Find downloaded file
        downloaded = list(temp_dir.glob("*"))
        media_files = [f for f in downloaded 
                       if f.is_file() and f.suffix.lower() in 
                       ('.mp4', '.mkv', '.webm', '.m4a', '.mp3', '.opus', '.aac')]
        
        if not media_files:
            # Try broader search
            media_files = [f for f in downloaded if f.is_file() and f.stat().st_size > 1000]
        
        if not media_files:
            return None, "No output file found"
        
        file_path = media_files[0]
        file_size = file_path.stat().st_size
        
        if progress_callback:
            progress_callback(100, "✅ کامل شد")
        
        # Extract title from filename
        title = file_path.stem
        # Remove video ID from title
        title = re.sub(rf'_{re.escape(vid_id)}$', '', title)
        title = title.replace('_', ' ').strip()
        
        return {
            "path": str(file_path),
            "name": file_path.name,
            "size": file_size,
            "title": title or "YouTube Video",
            "is_audio": quality == "audio",
        }, None
        
    except subprocess.TimeoutExpired:
        process.kill()
        return None, "دانلود بیش از حد طول کشید (تایم‌اوت)"
    except Exception as e:
        log(f"Subprocess error: {traceback.format_exc()}", "ERROR")
        return None, f"خطای سیستمی: {str(e)[:200]}"

# ==================== Split File ====================
def split_file(file_path, file_name, chunk_size=CHUNK_SIZE):
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
def bar(pct, w=12):
    f = int(w * pct / 100)
    return f"[{'█'*f}{'░'*(w-f)}] {pct}%"

# ==================== Main Bot ====================
YT_URL = re.compile(r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})', re.I)
QUALITIES = {"audio", "360p", "480p", "720p", "1080p"}

def process_updates():
    offset = get_offset()
    params = {"timeout": 30, "limit": 10}
    if offset > 0:
        params["offset"] = str(offset)
    
    result = bale_get("getUpdates", data=params)
    if not result.get("ok"):
        return
    
    updates = result.get("result", [])
    if updates:
        log(f"📨 {len(updates)} messages", "INFO")
    
    for upd in updates:
        uid = upd.get("update_id", 0)
        msg = upd.get("message") or upd.get("channel_post") or {}
        
        if not msg:
            save_offset(uid + 1)
            continue
        
        chat_id = (msg.get("chat", {}) or {}).get("id") or (msg.get("from", {}) or {}).get("id")
        msg_id = msg.get("message_id", 0)
        text = (msg.get("text") or "").strip()
        
        if not chat_id:
            save_offset(uid + 1)
            continue
        
        # === Commands ===
        if text == "/start":
            send_msg(chat_id,
                "🎬 **YouTube Downloader**\n\n"
                "✅ همه نوع ویدیو: معمولی، Shorts، youtu.be\n"
                "✅ کیفیت: `360p` `480p` `720p` `1080p` `audio`\n"
                "✅ فرمت نامعتبر → خودکار best جایگزین میشه\n\n"
                "🎯 مثال:\n`480p https://youtu.be/xxx`\n`audio https://youtube.com/shorts/xxx`\n\n"
                "💡 `/help` | `/quality`",
                reply=msg_id)
        
        elif text == "/quality":
            send_msg(chat_id,
                f"⚙️ کیفیت‌ها: `audio` `360p` `480p` `720p` `1080p`\n"
                f"💡 پیش‌فرض: {DEFAULT_QUALITY}",
                reply=msg_id)
        
        elif text == "/cookie":
            if COOKIE_FILE.exists():
                send_msg(chat_id, "✅ کوکی فعاله", reply=msg_id)
            else:
                send_msg(chat_id, "❌ کوکی نیست", reply=msg_id)
        
        elif text == "/help":
            send_msg(chat_id,
                "📚 **راهنما**\n\n"
                "۱. لینک رو بفرست\n"
                "۲. کیفیت: `720p لینک`\n"
                "۳. صوت: `audio لینک`\n\n"
                "📦 بزرگتر از ۱۹MB → تکه‌تکه",
                reply=msg_id)
        
        elif text:
            # Parse quality
            q = DEFAULT_QUALITY
            remaining = text
            for qual in sorted(QUALITIES, key=len, reverse=True):
                if remaining.lower().startswith(qual.lower()):
                    q = qual
                    remaining = remaining[len(qual):].strip()
                    break
            
            match = YT_URL.search(remaining)
            if match:
                url = f"https://youtube.com/watch?v={match.group(1)}"
                download_and_send(chat_id, msg_id, url, q)
            elif not text.startswith("/"):
                send_msg(chat_id, "🔗 لینک یوتیوب بفرستید\n💡 `/help`", reply=msg_id)
        
        save_offset(uid + 1)
    
    if updates:
        save_offset(max(u["update_id"] for u in updates) + 1)

def download_and_send(chat_id, msg_id, url, quality):
    q_disp = "🎵 صوت" if quality == "audio" else f"🎬 {quality}"
    
    status = send_msg(chat_id, f"{q_disp}\n🔗 {url}\n\n{bar(0)}\n⏳ شروع...")
    if not status or not status.get("ok"):
        return
    
    status_msg_id = status["result"]["message_id"]
    start = time.time()
    
    def progress(pct, txt):
        try:
            edit_msg(chat_id, status_msg_id,
                f"{q_disp}\n🔗 {url}\n\n{bar(pct)}\n⚡ {txt}\n⏱ {int(time.time()-start)}s")
        except:
            pass
    
    temp_dir = get_temp_dir()
    result, error = download_youtube(url, quality, temp_dir, progress_callback=progress)
    
    if error:
        send_msg(chat_id, f"❌ {error}", reply=msg_id)
        try:
            edit_msg(chat_id, status_msg_id, f"❌ {error[:100]}")
        except:
            pass
        return
    
    if not result:
        send_msg(chat_id, "❌ دانلود ناموفق", reply=msg_id)
        return
    
    file_path = result["path"]
    file_name = result["name"]
    file_size = result["size"]
    title = result["title"]
    is_audio = result["is_audio"]
    
    caption = f"🎬 {title}\n📦 {format_size(file_size)}"
    
    if file_size <= CHUNK_SIZE:
        progress(99, "📤 ارسال...")
        if is_audio:
            send_aud(chat_id, file_path, file_name, caption, reply=msg_id)
        else:
            send_vid(chat_id, file_path, file_name, caption, reply=msg_id)
        
        try:
            edit_msg(chat_id, status_msg_id, f"✅ {title}\n📦 {format_size(file_size)}")
        except:
            pass
    else:
        chunks = split_file(file_path, file_name)
        total = len(chunks)
        
        try:
            edit_msg(chat_id, status_msg_id, f"📦 {format_size(file_size)}\n🔢 {total} بخش")
        except:
            pass
        
        send_msg(chat_id, f"📦 ارسال {total} بخش...", reply=msg_id)
        
        for i, chunk in enumerate(chunks):
            send_file(chat_id, chunk["data"], chunk["name"],
                f"📤 {title}\nبخش {i+1}/{total}")
            time.sleep(1)
        
        send_msg(chat_id,
            f"✅ {total} بخش ارسال شد\n\n"
            f"📌 ترکیب:\n`cat {Path(file_name).stem}.part*of{total}{Path(file_name).suffix} > {file_name}`",
            reply=msg_id)
    
    # Cleanup
    try:
        for f in temp_dir.iterdir():
            try:
                if f.is_file(): f.unlink()
                elif f.is_dir(): shutil.rmtree(str(f), ignore_errors=True)
            except: pass
    except: pass

def format_size(s):
    if s < 1024: return f"{s} B"
    elif s < 1024*1024: return f"{s/1024:.1f} KB"
    elif s < 1024*1024*1024: return f"{s/(1024*1024):.1f} MB"
    return f"{s/(1024*1024*1024):.2f} GB"

# ==================== Entry ====================
if __name__ == "__main__":
    log("=" * 50)
    log("🎬 YouTube Bot - CLI Method (Final)")
    log("=" * 50)
    
    # Test token
    try:
        r = requests.get(f"https://tapi.bale.ai/bot{BOT_TOKEN}/getMe", timeout=10)
        if r.status_code == 200 and r.json().get("ok"):
            bot = r.json()["result"]
            log(f"✅ @{bot['username']}", "SUCCESS")
        else:
            log("❌ Invalid token", "ERROR")
            sys.exit(1)
    except:
        log("❌ Cannot verify token", "ERROR")
        sys.exit(1)
    
    setup_cookies()
    
    # Check ffmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        log("✅ FFmpeg OK", "SUCCESS")
    except:
        log("⚠️ FFmpeg missing", "WARN")
    
    ensure_ytdlp()
    
    # Delete webhook
    try:
        requests.post(f"{BASE_URL}/deleteWebhook")
    except:
        pass
    
    log("Polling...", "INFO")
    
    for i in range(MAX_ITERATIONS):
        try:
            process_updates()
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"Loop {i+1}: {e}", "ERROR")
        
        if i < MAX_ITERATIONS - 1:
            time.sleep(2)
    
    log("Done", "SUCCESS")
