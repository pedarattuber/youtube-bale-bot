import telebot
from telebot import apihelper
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import os
import time
import glob

# دریافت توکن‌ها و تنظیم API پیام‌رسان بله
TOKEN = os.getenv("BALE_BOT_TOKEN")
apihelper.API_URL = "https://tapi.bale.ai/bot{0}/{1}"
bot = telebot.TeleBot(TOKEN)

MAX_FILE_SIZE = 19 * 1024 * 1024  # 19 MB

def get_progress_hook(chat_id, message_id):
    last_edit_time = [0]
    def hook(d):
        if d['status'] == 'downloading':
            current_time = time.time()
            # آپدیت پیام هر 5 ثانیه برای جلوگیری از محدودیت‌های API
            if current_time - last_edit_time[0] > 5:
                percent = d.get('_percent_str', '0%').strip()
                speed = d.get('_speed_str', '0KiB/s').strip()
                text = f"⏳ در حال دانلود...\n📊 پیشرفت: {percent}\n🚀 سرعت: {speed}"
                try:
                    bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
                except:
                    pass
                last_edit_time[0] = current_time
    return hook

def split_file(file_path, chunk_size=MAX_FILE_SIZE):
    parts = []
    with open(file_path, 'rb') as f:
        part_num = 1
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            part_name = f"{file_path}.part{part_num:03d}"
            with open(part_name, 'wb') as p:
                p.write(chunk)
            parts.append(part_name)
            part_num += 1
    return parts

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "سلام! 🎬\nلینک ویدیوی یوتوب رو بفرست تا اطلاعاتش رو بگیرم و برای دانلود آمادش کنم.")

@bot.message_handler(func=lambda message: "youtube.com" in message.text or "youtu.be" in message.text)
def process_link(message):
    url = message.text.strip()
    msg = bot.reply_to(message, "🔎 در حال استخراج اطلاعات ویدیو... لطفا کمی صبر کنید.")
    
    ydl_opts = {
        'cookiefile': 'cookies.txt',
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'ویدیوی ناشناس')
            thumbnail = info.get('thumbnail')
            video_id = info.get('id')
            
            # ساخت دکمه‌های شیشه‌ای
            markup = InlineKeyboardMarkup()
            markup.row_width = 2
            btn_360 = InlineKeyboardButton("کیفیت 360p", callback_data=f"dl_18_{video_id}")
            btn_720 = InlineKeyboardButton("کیفیت 720p", callback_data=f"dl_22_{video_id}")
            btn_audio = InlineKeyboardButton("🎵 فقط صدا", callback_data=f"dl_140_{video_id}")
            markup.add(btn_360, btn_720, btn_audio)

            caption = f"🎥 **عنوان:** {title}\n\n👇 یکی از کیفیت‌های زیر را انتخاب کنید:"
            
            bot.delete_message(message.chat.id, msg.message_id)
            if thumbnail:
                bot.send_photo(message.chat.id, photo=thumbnail, caption=caption, reply_markup=markup, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ خطا در دریافت اطلاعات:\n`{str(e)}`", message.chat.id, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('dl_'))
def handle_download(call):
    data = call.data.split('_')
    format_id = data[1]
    video_id = data[2]
    url = f"https://youtu.be/{video_id}"
    
    msg = bot.send_message(call.message.chat.id, "🔄 در حال آماده‌سازی برای دانلود...")
    
    filename_template = f"{video_id}.%(ext)s"
    ydl_opts = {
        'format': format_id,
        'outtmpl': filename_template,
        'cookiefile': 'cookies.txt',
        'progress_hooks': [get_progress_hook(call.message.chat.id, msg.message_id)],
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = ydl.prepare_filename(info)

        bot.edit_message_text("✅ دانلود تمام شد. در حال بررسی حجم برای آپلود...", chat_id=call.message.chat.id, message_id=msg.message_id)
        
        file_size = os.path.getsize(downloaded_file)
        
        if file_size <= MAX_FILE_SIZE:
            bot.edit_message_text("📤 در حال آپلود ویدیو...", chat_id=call.message.chat.id, message_id=msg.message_id)
            with open(downloaded_file, 'rb') as f:
                bot.send_document(call.message.chat.id, f)
            bot.delete_message(call.message.chat.id, msg.message_id)
        else:
            bot.edit_message_text("✂️ حجم فایل بیشتر از ۱۹ مگابایت است. در حال تکه‌تکه کردن...", chat_id=call.message.chat.id, message_id=msg.message_id)
            parts = split_file(downloaded_file)
            total_parts = len(parts)
            
            for index, part in enumerate(parts):
                bot.edit_message_text(f"📤 در حال آپلود پارت {index + 1} از {total_parts}...", chat_id=call.message.chat.id, message_id=msg.message_id)
                with open(part, 'rb') as p:
                    bot.send_document(call.message.chat.id, p)
            
            filename_base = os.path.basename(downloaded_file)
            merge_instructions = (
                f"🎉 آپلود تمام پارت‌ها با موفقیت انجام شد.\n\n"
                f"🔧 **راهنمای ترکیب فایل‌ها:**\n"
                f"ابتدا همه فایل‌ها را در یک پوشه دانلود کنید. سپس بر اساس سیستم‌عامل خود دستورات زیر را در ترمینال یا CMD وارد کنید:\n\n"
                f"🖥 **در ویندوز:**\n"
                f"`copy /b {filename_base}.part* {filename_base}`\n\n"
                f"🐧 **در لینوکس، مک و ترموکس:**\n"
                f"`cat {filename_base}.part* > {filename_base}`"
            )
            bot.send_message(call.message.chat.id, merge_instructions, parse_mode="Markdown")
            bot.delete_message(call.message.chat.id, msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ خطا در دانلود یا آپلود:\n`{str(e)}`", call.message.chat.id, msg.message_id)
    
    finally:
        # پاکسازی فایل‌های دانلودی از روی سرور گیتهاب اکشن
        for f in glob.glob(f"{video_id}*"):
            try:
                os.remove(f)
            except:
                pass

print("Bot is running on Bale...")
bot.infinity_polling(timeout=60, long_polling_timeout=60)
