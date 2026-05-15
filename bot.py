import asyncio
import os
import re
import time
import zipfile
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ========== تنظیمات ==========
BOT_TOKEN = "1670424245:KeYeyPpfRUBMVdakFvShOf8g6pyei_l05DE"           # ← توکن ربات بله خود را جایگزین کنید
BASE_URL = "https://tapi.bale.ai/bot"       # API اصلی بله
BASE_FILE_URL = "https://tapi.bale.ai/file/bot"  # دانلود فایل‌های بله

CHUNK_SIZE = 19 * 1024 * 1024               # ۱۹ مگابایت
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ========== کلاس مدیریت گیت‌هاب ==========
class GitHubRepo:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.owner, self.repo = self._parse_url()
        self.api_url = f"https://api.github.com/repos/{self.owner}/{self.repo}"
        self.headers = {"Accept": "application/vnd.github.v3+json"}

    def _parse_url(self):
        path = urlparse(self.url).path.strip("/").split("/")
        if len(path) >= 2:
            return path[0], path[1]
        raise ValueError("آدرس ریپازیتوری نامعتبر است")

    def _request(self, endpoint: str, params: dict = None) -> dict | list:
        url = f"{self.api_url}{endpoint}"
        resp = requests.get(url, headers=self.headers, params=params)
        resp.raise_for_status()
        return resp.json()

    def get_info(self) -> dict:
        return self._request("")

    def get_releases(self) -> list:
        return self._request("/releases?per_page=20")

    def get_contributors(self) -> list:
        return self._request("/contributors?per_page=10")

    def get_languages(self) -> dict:
        return self._request("/languages")

    def get_branches(self) -> list:
        return self._request("/branches?per_page=20")

    def get_readme(self) -> Optional[str]:
        try:
            data = self._request("/readme")
            import base64
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except:
            return None

    def get_tree(self) -> list:
        default_branch = self._request("")["default_branch"]
        data = self._request(f"/git/trees/{default_branch}?recursive=1")
        return data.get("tree", [])

    def get_file_url(self, path: str) -> str:
        default_branch = self._request("")["default_branch"]
        return f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/{default_branch}/{path}"

    def get_archive_url(self, branch: str = None) -> str:
        if not branch:
            branch = self._request("")["default_branch"]
        return f"{self.url}/archive/refs/heads/{branch}.zip"

# ========== توابع کمکی ==========
def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024**2:
        return f"{size/1024:.1f} KB"
    elif size < 1024**3:
        return f"{size/(1024**2):.1f} MB"
    return f"{size/(1024**3):.1f} GB"

def format_num(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)

def progress_bar(current: int, total: int, length=15) -> str:
    if total == 0:
        return "█" * length
    ratio = min(current / total, 1.0)
    filled = int(ratio * length)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {ratio*100:.1f}%"

def split_file_zip(file_path: str) -> List[str]:
    """تقسیم فایل به قطعه‌های ZIP هم‌سایز ۱۹MB"""
    parts = []
    base = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        idx = 1
        while chunk := f.read(CHUNK_SIZE):
            zip_name = f"{file_path}.part{idx:03d}.zip"
            with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{base}.chunk{idx:03d}", chunk)
            parts.append(zip_name)
            idx += 1
    return parts

# ذخیره اطلاعات کاربران (chat_id -> dict)
user_data: Dict[int, Dict[str, Any]] = {}

# ========== کیبوردها ==========
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 اطلاعات کلی", callback_data="repo_info"),
         InlineKeyboardButton("📦 ریلیزها", callback_data="repo_releases")],
        [InlineKeyboardButton("👥 مشارکت‌کنندگان", callback_data="repo_contributors"),
         InlineKeyboardButton("📝 زبان‌ها", callback_data="repo_languages")],
        [InlineKeyboardButton("🌿 شاخه‌ها", callback_data="repo_branches"),
         InlineKeyboardButton("📖 README", callback_data="repo_readme")],
        [InlineKeyboardButton("📁 فایل‌ها", callback_data="repo_files"),
         InlineKeyboardButton("⬇️ دانلود ZIP", callback_data="repo_download_zip")],
        [InlineKeyboardButton("🔄 به‌روزرسانی", callback_data="repo_refresh"),
         InlineKeyboardButton("🏠 خانه", callback_data="repo_home")]
    ])

# ========== هندلرها ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎩 **به ریبات مدیریت ریپو پدرت گیتهاب خوش آمدید**\n"
        "لینکتان را بفلستید.\n\n"
        "🔹 **قابلیت‌ها:**\n"
        "• مشاهده اطلاعات کامل ریپازیتوری\n"
        "• دانلود ریلیزها و فایل‌ها\n"
        "• تقسیم خودکار فایل‌های بزرگ به قطعات ۱۹MB\n"
        "• نوار پیشرفت دانلود و آپلود\n\n"
        "📬 ارتباط ادمین: @mindscoder"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if re.match(r'^https?://github\.com/[\w\-\.]+/[\w\-\.]+', text):
        await load_repo(update, text)
    else:
        await update.message.reply_text("🔗 لطفاً یک لینک معتبر گیت‌هاب ارسال کنید یا /start را بزنید.")

async def load_repo(update: Update, url: str) -> None:
    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text("⏳ در حال دریافت اطلاعات...")
    try:
        repo = GitHubRepo(url)
        info = repo.get_info()
        user_data[chat_id] = {
            "repo": repo,
            "info": info,
            "files_page": 0
        }
        text = (
            f"✅ **{info.get('full_name', '---')}**\n"
            f"📝 {info.get('description', 'بدون توضیح')[:200]}\n"
            f"⭐ {format_num(info.get('stargazers_count', 0))} | "
            f"🍴 {format_num(info.get('forks_count', 0))} | "
            f"👁 {format_num(info.get('watchers_count', 0))}\n"
            f"🔤 زبان اصلی: {info.get('language', '---')}\n"
            f"📅 آخرین به‌روزرسانی: {info.get('updated_at', '---')[:10]}\n"
            f"🔗 [مشاهده در گیت‌هاب]({info.get('html_url', url)})"
        )
        await status_msg.delete()
        await update.message.reply_text(text, reply_markup=main_menu())
    except Exception as e:
        await status_msg.edit_text(f"❌ خطا: {str(e)[:200]}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    data = query.data

    if chat_id not in user_data or "repo" not in user_data[chat_id]:
        await query.edit_message_text("⚠️ ابتدا یک ریپازیتوری باز کنید.")
        return

    repo: GitHubRepo = user_data[chat_id]["repo"]

    if data == "repo_info":
        await show_repo_info(query)
    elif data == "repo_releases":
        await show_releases(query)
    elif data == "repo_contributors":
        await show_contributors(query)
    elif data == "repo_languages":
        await show_languages(query)
    elif data == "repo_branches":
        await show_branches(query)
    elif data == "repo_readme":
        await show_readme(query)
    elif data == "repo_files":
        await show_files(query, page=0)
    elif data.startswith("files_page_"):
        page = int(data.split("_")[-1])
        await show_files(query, page)
    elif data.startswith("dl_file_"):
        filename = data[8:]
        await download_file(query, filename)
    elif data.startswith("dl_release_"):
        release_id = data[11:]
        await download_release(query, release_id)
    elif data == "repo_download_zip":
        await download_zip(query)
    elif data == "repo_refresh":
        await refresh_repo(query)
    elif data == "repo_home":
        await query.edit_message_text("📋 منوی اصلی:", reply_markup=main_menu())
    elif data == "back_to_main":
        await query.edit_message_text("📋 منوی اصلی:", reply_markup=main_menu())
    elif data == "files_prev":
        page = user_data[chat_id].get("files_page", 0) - 1
        await show_files(query, max(page, 0))
    elif data == "files_next":
        page = user_data[chat_id].get("files_page", 0) + 1
        await show_files(query, page)

async def show_repo_info(query) -> None:
    info = user_data[query.from_user.id]["info"]
    text = (
        f"📊 **اطلاعات کامل ریپازیتوری**\n\n"
        f"🔹 **نام:** {info.get('full_name')}\n"
        f"🔹 **مالک:** {info.get('owner', {}).get('login', '---')}\n"
        f"🔹 **توضیحات:** {info.get('description', '---')}\n"
        f"🔹 **زبان اصلی:** {info.get('language', '---')}\n"
        f"🔹 **تعداد ستاره:** {format_num(info.get('stargazers_count', 0))}\n"
        f"🔹 **تعداد فورک:** {format_num(info.get('forks_count', 0))}\n"
        f"🔹 **ناظران:** {format_num(info.get('watchers_count', 0))}\n"
        f"🔹 **موضوعات:** {', '.join(info.get('topics', []))}\n"
        f"🔹 **شاخه پیش‌فرض:** {info.get('default_branch', 'main')}\n"
        f"🔹 **تاریخ ایجاد:** {info.get('created_at', '---')[:10]}\n"
        f"🔹 **آخرین به‌روزرسانی:** {info.get('updated_at', '---')[:10]}\n"
        f"🔹 **لایسنس:** {info.get('license', {}).get('spdx_id', '---') if info.get('license') else '---'}"
    )
    await query.edit_message_text(text, reply_markup=main_menu())

async def show_releases(query) -> None:
    repo = user_data[query.from_user.id]["repo"]
    try:
        releases = repo.get_releases()
        if not releases:
            await query.edit_message_text("📦 هیچ ریلیزی یافت نشد.", reply_markup=main_menu())
            return
        text = "📦 **آخرین ریلیزها:**\n\n"
        buttons = []
        for rel in releases[:10]:
            tag = rel.get("tag_name", "---")
            date = rel.get("published_at", "---")[:10]
            assets = ""
            for a in rel.get("assets", [])[:3]:
                assets += f"\n   📎 {a['name']} ({format_size(a['size'])})"
            text += f"**{tag}** - {date}{assets}\n\n"
            buttons.append([InlineKeyboardButton(f"📥 {tag}", callback_data=f"dl_release_{rel['id']}")])
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")])
        await query.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}", reply_markup=main_menu())

async def show_contributors(query) -> None:
    repo = user_data[query.from_user.id]["repo"]
    try:
        contribs = repo.get_contributors()
        text = "👥 **مشارکت‌کنندگان برتر:**\n\n"
        for c in contribs[:10]:
            text += f"🔸 **{c['login']}** - {c.get('contributions', 0)} کامیت\n"
        await query.edit_message_text(text[:4000], reply_markup=main_menu())
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}", reply_markup=main_menu())

async def show_languages(query) -> None:
    repo = user_data[query.from_user.id]["repo"]
    try:
        langs = repo.get_languages()
        total = sum(langs.values())
        text = "📝 **زبان‌های برنامه‌نویسی:**\n\n"
        for lang, bytes_ in sorted(langs.items(), key=lambda x: x[1], reverse=True):
            pct = (bytes_ / total * 100) if total else 0
            text += f"🔹 {lang}: {pct:.1f}% ({format_size(bytes_)})\n"
        await query.edit_message_text(text, reply_markup=main_menu())
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}", reply_markup=main_menu())

async def show_branches(query) -> None:
    repo = user_data[query.from_user.id]["repo"]
    try:
        branches = repo.get_branches()
        text = "🌿 **شاخه‌ها:**\n\n"
        for b in branches[:15]:
            text += f"🔹 {b['name']}\n"
        await query.edit_message_text(text, reply_markup=main_menu())
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}", reply_markup=main_menu())

async def show_readme(query) -> None:
    repo = user_data[query.from_user.id]["repo"]
    try:
        readme = repo.get_readme()
        if readme:
            text = f"📖 **README.md**\n\n{readme[:3500]}{'...' if len(readme) > 3500 else ''}"
        else:
            text = "📖 README یافت نشد."
        await query.edit_message_text(text, reply_markup=main_menu())
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}", reply_markup=main_menu())

async def show_files(query, page: int = 0) -> None:
    repo = user_data[query.from_user.id]["repo"]
    user_data[query.from_user.id]["files_page"] = page
    try:
        tree = repo.get_tree()
        files = [f for f in tree if f["type"] == "blob"]
        per_page = 10
        total_pages = max(1, -(-len(files) // per_page))  # ceil division
        start = page * per_page
        end = start + per_page
        current_files = files[start:end]

        text = f"📁 **فایل‌ها (صفحه {page+1}/{total_pages}):**\n\n"
        for f in current_files:
            text += f"📄 {f['path']} ({format_size(f.get('size', 0))})\n"

        buttons = []
        for f in current_files:
            buttons.append([InlineKeyboardButton(f"📥 {f['path'][:40]}", callback_data=f"dl_file_{f['path']}")])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data="files_prev"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("➡️ بعدی", callback_data="files_next"))
        if nav:
            buttons.append(nav)
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")])

        await query.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}", reply_markup=main_menu())

async def download_file(query, filename: str) -> None:
    repo = user_data[query.from_user.id]["repo"]
    url = repo.get_file_url(filename)
    await download_with_progress(query, url, os.path.basename(filename))

async def download_release(query, release_id: str) -> None:
    repo = user_data[query.from_user.id]["repo"]
    try:
        releases = repo.get_releases()
        asset_url = None
        name = "release.zip"
        for rel in releases:
            if str(rel["id"]) == release_id:
                if rel.get("assets"):
                    asset_url = rel["assets"][0]["browser_download_url"]
                    name = rel["assets"][0]["name"]
                else:
                    asset_url = rel.get("zipball_url")
                break
        if asset_url:
            await download_with_progress(query, asset_url, name)
        else:
            await query.edit_message_text("❌ ریلیز یافت نشد.")
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}")

async def download_zip(query) -> None:
    repo = user_data[query.from_user.id]["repo"]
    info = user_data[query.from_user.id]["info"]
    url = repo.get_archive_url(info.get("default_branch", "main"))
    await download_with_progress(query, url, f"{repo.repo}.zip")

async def download_with_progress(query, url: str, filename: str) -> None:
    chat_id = query.from_user.id
    progress_msg = await query.message.reply_text(f"⬇️ در حال دانلود {filename}...\n{progress_bar(0, 100)}")
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        file_path = DOWNLOAD_DIR / f"{chat_id}_{filename}"
        downloaded = 0
        start_time = time.time()
        with open(file_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total and downloaded % (CHUNK_SIZE // 2) == 0:
                    elapsed = time.time() - start_time
                    speed = downloaded / elapsed if elapsed else 0
                    eta = (total - downloaded) / speed if speed else 0
                    await progress_msg.edit_text(
                        f"⬇️ دانلود {filename}\n{progress_bar(downloaded, total)}\n"
                        f"⚡ {format_size(int(speed))}/s | ⏳ {int(eta)}s"
                    )
        await progress_msg.delete()
        file_size = os.path.getsize(file_path)
        if file_size <= CHUNK_SIZE:
            await send_document(query.message, file_path, filename)
        else:
            await split_and_send(query.message, file_path, filename)
    except Exception as e:
        await progress_msg.edit_text(f"❌ خطا: {str(e)[:200]}")

async def send_document(message, file_path: str, filename: str) -> None:
    with open(file_path, "rb") as f:
        await message.reply_document(document=f, caption=f"📄 {filename}")
    os.remove(file_path)

async def split_and_send(message, file_path: str, filename: str) -> None:
    status_msg = await message.reply_text("📦 در حال تقسیم فایل...")
    parts = split_file_zip(file_path)
    total = len(parts)
    for i, part_path in enumerate(parts, 1):
        part_name = f"{filename}.part{i:03d}.zip"
        await status_msg.edit_text(f"📤 ارسال قطعه {i}/{total}...\n{progress_bar(i, total)}")
        with open(part_path, "rb") as f:
            await message.reply_document(document=f, caption=f"📦 {part_name} (قطعه {i}/{total})")
        os.remove(part_path)
        await asyncio.sleep(0.5)
    await status_msg.delete()
    os.remove(file_path)

async def refresh_repo(query) -> None:
    repo = user_data[query.from_user.id]["repo"]
    # بازخوانی اطلاعات
    info = repo.get_info()
    user_data[query.from_user.id]["info"] = info
    text = (
        f"✅ **{info.get('full_name', '---')}**\n"
        f"📝 {info.get('description', 'بدون توضیح')[:200]}\n"
        f"⭐ {format_num(info.get('stargazers_count', 0))} | "
        f"🍴 {format_num(info.get('forks_count', 0))} | "
        f"👁 {format_num(info.get('watchers_count', 0))}\n"
        f"🔤 زبان اصلی: {info.get('language', '---')}\n"
        f"📅 آخرین به‌روزرسانی: {info.get('updated_at', '---')[:10]}\n"
        f"🔗 [مشاهده در گیت‌هاب]({info.get('html_url', repo.url)})"
    )
    await query.edit_message_text(text, reply_markup=main_menu())

# ========== اجرای ربات ==========
def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .base_url(BASE_URL)
        .base_file_url(BASE_FILE_URL)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 ربات مدیریت گیت‌هاب اجرا شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
