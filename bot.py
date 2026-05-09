import telebot
from telebot import apihelper, types
import yt_dlp
import os
import time
import glob
import subprocess

# پیکربندی بات بله
TOKEN = os.getenv("BALE_BOT_TOKEN")
apihelper.API_URL = "https://tapi.bale.ai/bot{0}/{1}"
bot = telebot.TeleBot(TOKEN)

# محدودیت آپلود بله (۱۹ مگابایت)
MAX_FILE_SIZE = 19 * 1024 * 1024 

def get_bun_path():
    """یافتن مسیر اجرایی Bun در محیط گیت‌هاب اکشنز"""
    try:
        return subprocess.check_output(['which', 'bun']).decode().strip()
    except:
        return "/home/runner/.bun/bin/bun"

def get_progress_hook(chat_id, message_id):
    last_update = [0]
    def hook(d):
        if d['status'] == 'downloading':
            now = time.time()
            if now - last_update[0] > 5:
                p = d.get('_percent_str', '0%')
                s = d.get('_speed_str', '0KB/s')
                try:
                    bot.edit_message_text(f"🚀 **سرعت بالا (Aria2)**\n📊 پیشرفت: {p}\n⚡ سرعت: {s}", chat_id, message_id)
                except: pass
                last_update[0] = now
    return hook

def split_file(file_path):
    parts = []
    with open(file_path, 'rb') as f:
        i = 1
        while True:
            chunk = f.read(MAX_FILE_SIZE)
            if not chunk: break
            name = f"{file_path}.part{i:03d}"
            with open(name, 'wb') as p: p.write(chunk)
            parts.append(name)
            i += 1
    return parts

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🔥 **بات دانلودر فوق پیشرفته**\nآماده برای دانلود با متد Bun + Aria2. لینک را بفرست:")

@bot.message_handler(func=lambda m: "youtube.com" in m.text or "youtu.be" in m.text)
def handle_link(message):
    url = message.text.strip()
    msg = bot.reply_to(message, "🔍 در حال استخراج لینک‌های مستقیم (بای‌پس تحریم)...")
    
    # تنظیمات استخراج (دقیقاً مشابه متد yml شما)
    ydl_info_opts = {
        'cookiefile': 'youtube_cookies.txt',
        'javascript_runtimes': [f'bun:{get_bun_path()}'],
        'extractor_args': {'youtube': {'player_client': ['web', 'tv'], 'skip': ['authcheck']}},
        'quiet': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            v_id = info['id']
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🎬 720p", callback_data=f"dl_720_{v_id}"),
                       types.InlineKeyboardButton("🎬 360p", callback_data=f"dl_360_{v_id}"))
            markup.add(types.InlineKeyboardButton("🎵 MP3 Audio", callback_data=f"dl_audio_{v_id}"))
            
            bot.delete_message(message.chat.id, msg.message_id)
            bot.send_photo(message.chat.id, info.get('thumbnail'), caption=f"🎥 **{info['title']}**\nکیفیت را انتخاب کنید:", reply_markup=markup)
    except Exception as e:
        bot.edit_message_text(f"❌ خطا در حل چالش امنیتی:\n`{str(e)}`", message.chat.id, msg.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('dl_'))
def download(call):
    q, v_id = call.data.split('_')[1], call.data.split('_')[2]
    url = f"https://youtu.be/{v_id}"
    msg = bot.send_message(call.message.chat.id, "🛠 در حال آماده‌سازی محیط Bun...")

    # فرمت‌بندی بر اساس یمل انتخابی شما
    f_str = 'bestvideo[height<=720]+bestaudio/best[height<=720]' if q=='720' else 'bestvideo[height<=360]+bestaudio/best[height<=360]'
    if q == 'audio': f_str = 'bestaudio/best'

    ydl_opts = {
        'format': f_str,
        'outtmpl': f'{v_id}.%(ext)s',
        'cookiefile': 'youtube_cookies.txt',
        'javascript_runtimes': [f'bun:{get_bun_path()}'],
        'external_downloader': 'aria2c', # استفاده از Aria2 مشابه پروژه 0x00
        'external_downloader_args': ['--min-split-size=1M', '--max-connection-per-server=16', '-x16'],
        'progress_hooks': [get_progress_hook(call.message.chat.id, msg.message_id)],
        'merge_output_format': 'mp4',
        'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}] if q=='audio' else []
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(url, download=True)
            fname = ydl.prepare_filename(res)
            if q == 'audio': fname = fname.rsplit('.', 1)[0] + '.mp3'

        size = os.path.getsize(fname)
        if size <= MAX_FILE_SIZE:
            bot.edit_message_text("📤 آپلود مستقیم...", call.message.chat.id, msg.message_id)
            with open(fname, 'rb') as doc: bot.send_document(call.message.chat.id, doc)
        else:
            bot.edit_message_text("✂️ فایل حجیم است، در حال پارت‌بندی...", call.message.chat.id, msg.message_id)
            parts = split_file(fname)
            for idx, p in enumerate(parts):
                bot.edit_message_text(f"📤 آپلود پارت {idx+1}...", call.message.chat.id, msg.message_id)
                with open(p, 'rb') as f_part: bot.send_document(call.message.chat.id, f_part)
            
            b_name = os.path.basename(fname)
            bot.send_message(call.message.chat.id, f"✅ اتمام آپلود پارت‌ها.\nدستور ترکیب:\n`cat {b_name}.part* > {b_name}`")
        
        bot.delete_message(call.message.chat.id, msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ خطای نهایی:\n`{str(e)}`", call.message.chat.id, msg.message_id)
    finally:
        for f in glob.glob(f"{v_id}*"): os.remove(f)

bot.infinity_polling()
