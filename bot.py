import telebot
from telebot import apihelper
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import os
import time
import glob
import subprocess

# تنظیمات ربات بله
TOKEN = os.getenv("BALE_BOT_TOKEN")
apihelper.API_URL = "https://tapi.bale.ai/bot{0}/{1}"
bot = telebot.TeleBot(TOKEN)

MAX_FILE_SIZE = 19 * 1024 * 1024  # 19 MB

# پیدا کردن مسیر Bun به صورت خودکار در گیت‌هاب اکشنز
def get_bun_path():
    try:
        path = subprocess.check_output(['which', 'bun']).decode().strip()
        return path
    except:
        return "/home/runner/.bun/bin/bun"

def get_progress_hook(chat_id, message_id):
    last_edit_time = [0]
    def hook(d):
        if d['status'] == 'downloading':
            current_time = time.time()
            if current_time - last_edit_time[0] > 5:
                percent = d.get('_percent_str', '0%').strip()
                speed = d.get('_speed_str', '0KiB/s').strip()
                text = f"⏳ در حال دانلود (بای‌پس تحریم)...\n📊 پیشرفت: {percent}\n🚀 سرعت: {speed}"
                try:
                    bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
                except: pass
                last_edit_time[0] = current_time
    return hook

def split_file(file_path, chunk_size=MAX_FILE_SIZE):
    parts = []
    with open(file_path, 'rb') as f:
        part_num = 1
        while True:
            chunk = f.read(chunk_size)
            if not chunk: break
            part_name = f"{file_path}.part{part_num:03d}"
            with open(part_name, 'wb') as p:
                p.write(chunk)
            parts.append(part_name)
            part_num += 1
    return parts

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ ربات هوشمند دانلودر یوتوب فعال است.\nلینک ویدیو را بفرستید:")

@bot.message_handler(func=lambda message: "youtube.com" in message.text or "youtu.be" in message.text)
def process_link(message):
    url = message.text.strip()
    msg = bot.reply_to(message, "🔎 در حال حل چالش‌های امنیتی و دریافت اطلاعات...")
    
    ydl_opts = {
        'cookiefile': 'youtube_cookies.txt',
        'quiet': True,
        'javascript_runtimes': [f'bun:{get_bun_path()}'],
        'extractor_args': {'youtube': {'player_client': ['web', 'ios'], 'skip': ['authcheck']}}
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_id = info.get('id')
            title = info.get('title', 'Video')
            thumbnail = info.get('thumbnail')
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🎬 720p (MP4)", callback_data=f"dl_720_{video_id}"),
                       InlineKeyboardButton("🎬 360p (MP4)", callback_data=f"dl_360_{video_id}"))
            markup.add(InlineKeyboardButton("🎵 فقط صدا (MP3)", callback_data=f"dl_audio_{video_id}"))

            bot.delete_message(message.chat.id, msg.message_id)
            if thumbnail:
                bot.send_photo(message.chat.id, thumbnail, caption=f"🎥 **{title}**\n\nکیفیت را انتخاب کنید:", reply_markup=markup, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, f"🎥 **{title}**\n\nکیفیت را انتخاب کنید:", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ خطا در پردازش:\n`{str(e)}`", message.chat.id, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('dl_'))
def handle_download(call):
    quality, video_id = call.data.split('_')[1], call.data.split('_')[2]
    url = f"https://youtu.be/{video_id}"
    msg = bot.send_message(call.message.chat.id, "🔄 شروع فرایند دانلود و ترکیب فایل...")
    
    format_str = {
        '720': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]',
        '360': 'bestvideo[ext=mp4][height<=360]+bestaudio[ext=m4a]/best[ext=mp4][height<=360]',
        'audio': 'bestaudio/best'
    }.get(quality)

    ydl_opts = {
        'format': format_str,
        'outtmpl': f'{video_id}.%(ext)s',
        'cookiefile': 'youtube_cookies.txt',
        'javascript_runtimes': [f'bun:{get_bun_path()}'],
        'progress_hooks': [get_progress_hook(call.message.chat.id, msg.message_id)],
        'extractor_args': {'youtube': {'player_client': ['web', 'ios']}},
        'merge_output_format': 'mp4' if quality != 'audio' else None,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}] if quality == 'audio' else []
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if quality == 'audio': filename = filename.rsplit('.', 1)[0] + '.mp3'

        file_size = os.path.getsize(filename)
        if file_size <= MAX_FILE_SIZE:
            bot.edit_message_text("📤 در حال آپلود مستقیم...", call.message.chat.id, msg.message_id)
            with open(filename, 'rb') as f: bot.send_document(call.message.chat.id, f)
        else:
            bot.edit_message_text("✂️ فایل بزرگ است، در حال تکه‌تکه کردن...", call.message.chat.id, msg.message_id)
            parts = split_file(filename)
            for i, p in enumerate(parts):
                bot.edit_message_text(f"📤 آپلود پارت {i+1} از {len(parts)}...", call.message.chat.id, msg.message_id)
                with open(p, 'rb') as f: bot.send_document(call.message.chat.id, f)
            
            base_name = os.path.basename(filename)
            bot.send_message(call.message.chat.id, f"✅ اتمام آپلود پارت‌ها.\nدستور ترکیب:\n`cat {base_name}.part* > {base_name}`", parse_mode="Markdown")
        
        bot.delete_message(call.message.chat.id, msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ خطا:\n`{str(e)}`", call.message.chat.id, msg.message_id)
    finally:
        for f in glob.glob(f"{video_id}*"): os.remove(f)

bot.infinity_polling()
