import os
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)
import yt_dlp
import re
import tempfile

# Get token from environment variable (set this in Render dashboard)
TOKEN = os.environ.get("TOKEN")

# States
WAITING_LINK, WAITING_TYPE, WAITING_QUALITY = range(3)

def clean_title(title):
    """Sanitize filenames by removing special characters"""
    return re.sub(r'[^\w\s\-\(\)]', '', title).strip()[:50]

# ======================
# COMMAND HANDLERS
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌟 *Welcome to DreamDown Media Downloader!* 🌟\n\n"
        "📤 Send me a link from any supported platform and I'll download it for you!\n\n"
        "Use /help for instructions\n"
        "Use /sites for supported platforms",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )
    return WAITING_LINK

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command with usage instructions"""
    help_text = (
        "🆘 *Help Center*\n\n"
        "🔹 *How to use:*\n"
        "1. Send a media link\n"
        "2. Choose video/audio\n"
        "3. Select quality (if video)\n"
        "4. Wait for processing\n\n"
        "📋 *Commands:*\n"
        "/start - Begin new download\n"
        "/help - Show this message\n"
        "/about - Bot capabilities\n"
        "/sites - Supported platforms\n"
        "/developer - Contact info"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart the conversation"""
    await update.message.reply_text("🔄 Restarting...", reply_markup=ReplyKeyboardRemove())
    return await start(update, context)

# ======================
# DOWNLOAD HANDLERS
# ======================
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            context.chat_data['url'] = url
            context.chat_data['title'] = clean_title(info.get('title', 'media'))
            context.chat_data['is_youtube'] = 'youtube.com' in url or 'youtu.be' in url

        await update.message.reply_text(
            "Choose type:",
            reply_markup=ReplyKeyboardMarkup(
                [["🎥 Video", "🎧 Audio"]],
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
        return WAITING_TYPE

    except Exception as e:
        print(f"Error processing link: {e}")  # Logging for Render
        await update.message.reply_text("❌ Invalid link or unsupported platform. Try again.")
        return WAITING_LINK

async def handle_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    context.chat_data['type'] = choice

    if "🎥" in choice:
        keyboard = [["360p", "720p", "Best"]] if context.chat_data.get('is_youtube') else [["Normal", "Best"]]
        await update.message.reply_text(
            "Select quality:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return WAITING_QUALITY
    else:
        await process_audio(update, context)
        return WAITING_LINK

async def handle_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quality = update.message.text
    url = context.chat_data['url']
    title = context.chat_data['title']
    
    format_map = {
        "360p": 'bestvideo[height<=360]+bestaudio/best[height<=360]',
        "720p": 'bestvideo[height<=720]+bestaudio/best[height<=720]',
        "Best": 'bestvideo+bestaudio/best',
        "Normal": 'worst'
    }
    
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            msg = await update.message.reply_text("⏳ Downloading...")
            
            ydl_opts = {
                'format': format_map.get(quality, 'best'),
                'outtmpl': os.path.join(tmp_dir, f"{title}.%(ext)s"),
                'quiet': True,
                'merge_output_format': 'mp4'
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = ydl.prepare_filename(info)

            # Compress if needed (Telegram has 50MB limit)
            final_path = os.path.join(tmp_dir, f"final_{title}.mp4")
            os.system(
                f'ffmpeg -hide_banner -loglevel error -i "{file_path}" '
                '-c:v libx264 -crf 28 -preset fast -c:a aac -b:a 128k '
                f'"{final_path}"'
            )

            file_size = os.path.getsize(final_path) / (1024 * 1024)
            if file_size > 50:
                await msg.edit_text(f"⚠️ File too large ({file_size:.1f}MB). Telegram limit is 50MB.")
                return WAITING_LINK

            await msg.edit_text("📤 Uploading...")
            with open(final_path, 'rb') as f:
                await update.message.reply_video(
                    video=f,
                    caption=f"🎬 {title}",
                    supports_streaming=True,
                    reply_markup=ReplyKeyboardRemove()
                )

        await update.message.reply_text("✅ Done! Send another link.")
        return WAITING_LINK

    except Exception as e:
        print(f"Download error: {e}")  # Logging for Render
        await update.message.reply_text(f"❌ Error: {str(e)[:200]}...")
        return WAITING_LINK

async def process_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = context.chat_data['url']
    title = context.chat_data['title']
    
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            msg = await update.message.reply_text("🎧 Downloading audio...")

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(tmp_dir, f"{title}.%(ext)s"),
                'quiet': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }]
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                file_path = os.path.join(tmp_dir, f"{title}.mp3")

            file_size = os.path.getsize(file_path) / (1024 * 1024)
            if file_size > 50:
                await msg.edit_text(f"⚠️ File too large ({file_size:.1f}MB).")
                return

            await msg.edit_text("📤 Uploading...")
            with open(file_path, 'rb') as f:
                await update.message.reply_audio(
                    audio=f,
                    title=title,
                    performer="Downloaded",
                    reply_markup=ReplyKeyboardRemove()
                )

        await update.message.reply_text("✅ Done! Send another link.")
        
    except Exception as e:
        print(f"Audio error: {e}")
        await update.message.reply_text(f"❌ Audio processing failed: {str(e)[:200]}...")

# ======================
# MAIN SETUP
# ======================
def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)],
            WAITING_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_type)],
            WAITING_QUALITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quality)],
        },
        fallbacks=[
            CommandHandler("restart", restart),
            CommandHandler("help", help_cmd),
        ],
        allow_reentry=True
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restart", restart))

    print("🤖 Bot is running in polling mode...")
    app.run_polling()

if __name__ == "__main__":
    main()
