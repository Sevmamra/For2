import os
import re
import asyncio
import logging
from typing import Optional

from telegram import Update, Message
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackContext
)
from config import Config

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class ForwardSession:
    def __init__(self):
        self.current_topic_name: Optional[str] = None
        self.current_thread_id: Optional[int] = None
        self.start_message_id: Optional[int] = None
        self.end_message_id: Optional[int] = None
        self.progress_message: Optional[Message] = None

    def reset(self):
        self.__init__()

    def validate_user(self, user_id: int) -> bool:
        return user_id in Config.AUTHORIZED_USER_IDS

session = ForwardSession()

def extract_message_id(link: str) -> Optional[int]:
    """Extract message ID from Telegram link (e.g., t.me/c/123/45 → 45)"""
    match = re.search(r"/(\d+)$", link)
    return int(match.group(1)) if match else None

async def copy_content(context: CallbackContext, message_id: int) -> bool:
    """SMART COPY: Removes forward tags + handles all media"""
    try:
        # Step 1: Fetch original message
        msg = (await context.bot.get_messages(
            chat_id=Config.SOURCE_CHANNEL_ID,
            message_ids=[message_id]
        ))[0]

        if not msg:
            return False

        # Step 2: Reconstruct and send manually (NO FORWARD TAG)
        if msg.text:
            await context.bot.send_message(
                chat_id=Config.DESTINATION_GROUP_ID,
                text=msg.text,
                message_thread_id=session.current_thread_id,
                entities=msg.entities,
                parse_mode=None
            )
        elif msg.photo:
            await context.bot.send_photo(
                chat_id=Config.DESTINATION_GROUP_ID,
                photo=msg.photo[-1].file_id,
                caption=msg.caption,
                caption_entities=msg.caption_entities,
                message_thread_id=session.current_thread_id,
                parse_mode=None
            )
        elif msg.video:
            await context.bot.send_video(
                chat_id=Config.DESTINATION_GROUP_ID,
                video=msg.video.file_id,
                caption=msg.caption,
                caption_entities=msg.caption_entities,
                message_thread_id=session.current_thread_id,
                parse_mode=None
            )
        elif msg.document:
            await context.bot.send_document(
                chat_id=Config.DESTINATION_GROUP_ID,
                document=msg.document.file_id,
                caption=msg.caption,
                caption_entities=msg.caption_entities,
                message_thread_id=session.current_thread_id,
                parse_mode=None
            )
        elif msg.sticker:
            await context.bot.send_sticker(
                chat_id=Config.DESTINATION_GROUP_ID,
                sticker=msg.sticker.file_id,
                message_thread_id=session.current_thread_id
            )
        else:
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to copy message {message_id}: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not session.validate_user(update.message.from_user.id):
        return
    await update.message.reply_text(
        "🚀 *Content Copier Bot*\n\n"
        "1. /create_topic TOPIC_NAME\n"
        "2. Send START link\n"
        "3. Send END link\n"
        "4. Bot copies ALL messages (NO FORWARD TAGS)",
        parse_mode="Markdown"
    )

async def create_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not session.validate_user(update.message.from_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return
    if not context.args:
        await update.message.reply_text("Usage: /create_topic TOPIC_NAME")
        return

    session.reset()
    session.current_topic_name = " ".join(context.args)

    try:
        result = await context.bot.create_forum_topic(
            chat_id=Config.DESTINATION_GROUP_ID,
            name=session.current_topic_name
        )
        session.current_thread_id = result.message_thread_id
        await update.message.reply_text(
            f"✅ Topic '{session.current_topic_name}' created!\n"
            "Now send STARTING message link:"
        )
    except Exception as e:
        logger.error(f"Topic creation failed: {e}")
        await update.message.reply_text("⚠️ Failed to create topic")
        session.reset()

async def handle_message_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not session.validate_user(update.message.from_user.id):
        return
    if not session.current_thread_id:
        await update.message.reply_text("⚠️ First create a topic with /create_topic")
        return

    message_id = extract_message_id(update.message.text)
    if not message_id:
        await update.message.reply_text("❌ Invalid link. Send proper Telegram message link.")
        return

    if not session.start_message_id:
        session.start_message_id = message_id
        await update.message.reply_text("🔗 Got START link! Now send END link:")
    elif not session.end_message_id:
        session.end_message_id = message_id
        if session.end_message_id < session.start_message_id:
            await update.message.reply_text("❌ END link must come after START link!")
            session.reset()
            return

        total = session.end_message_id - session.start_message_id + 1
        session.progress_message = await update.message.reply_text(f"⏳ Copying {total} messages...")
        asyncio.create_task(process_messages(update, context))

async def process_messages(update: Update, context: CallbackContext):
    try:
        success = failed = 0
        total = session.end_message_id - session.start_message_id + 1

        for msg_id in range(session.start_message_id, session.end_message_id + 1):
            try:
                if await copy_content(context, msg_id):
                    success += 1
                else:
                    failed += 1

                if (success + failed) % 5 == 0 or msg_id == session.end_message_id:
                    await session.progress_message.edit_text(
                        f"⏳ Progress: {success + failed}/{total}\n"
                        f"✅ Copied: {success}\n"
                        f"❌ Failed: {failed}"
                    )
                await asyncio.sleep(Config.DELAY_BETWEEN_FORWARDS)
            except Exception as e:
                logger.warning(f"Skipped message {msg_id}: {e}")
                failed += 1

        await update.message.reply_text(
            f"✅ Done!\n\n"
            f"Topic: {session.current_topic_name}\n"
            f"Total: {total}\n"
            f"Success: {success}\n"
            f"Failed: {failed}"
        )
    except Exception as e:
        logger.error(f"Process failed: {e}")
        await update.message.reply_text("⚠️ Process failed")
    finally:
        session.reset()

def main():
    Config.validate()
    app = ApplicationBuilder().token(Config.TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler(["create_topic", "createtopic"], create_topic))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        handle_message_link
    ))

    logger.info("Bot started in polling mode")
    app.run_polling()

if __name__ == "__main__":
    main()
