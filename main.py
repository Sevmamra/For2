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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, Config.LOG_LEVEL)
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
    """Extract message ID from Telegram message link"""
    match = re.search(r"/(\d+)$", link)
    return int(match.group(1)) if match else None

async def copy_content(update: Update, context: CallbackContext, message_id: int) -> bool:
    """Universal content copier that works with all message types"""
    try:
        # First try to forward (works for most content)
        await context.bot.forward_message(
            chat_id=Config.DESTINATION_GROUP_ID,
            from_chat_id=Config.SOURCE_CHANNEL_ID,
            message_id=message_id,
            message_thread_id=session.current_thread_id
        )
        return True
    except Exception as e:
        logger.warning(f"Forward failed for {message_id}, trying manual copy: {e}")
        try:
            # Fallback to manual copy for problematic content
            msg = await context.bot.get_messages(
                chat_id=Config.SOURCE_CHANNEL_ID,
                message_ids=[message_id]
            )
            msg = msg[0] if msg else None
            
            if not msg:
                return False

            if msg.text:
                await context.bot.send_message(
                    chat_id=Config.DESTINATION_GROUP_ID,
                    text=msg.text,
                    message_thread_id=session.current_thread_id,
                    entities=msg.entities
                )
            elif msg.photo:
                await context.bot.send_photo(
                    chat_id=Config.DESTINATION_GROUP_ID,
                    photo=msg.photo[-1].file_id,
                    caption=msg.caption,
                    caption_entities=msg.caption_entities,
                    message_thread_id=session.current_thread_id
                )
            elif msg.video:
                await context.bot.send_video(
                    chat_id=Config.DESTINATION_GROUP_ID,
                    video=msg.video.file_id,
                    caption=msg.caption,
                    caption_entities=msg.caption_entities,
                    message_thread_id=session.current_thread_id
                )
            elif msg.document:
                await context.bot.send_document(
                    chat_id=Config.DESTINATION_GROUP_ID,
                    document=msg.document.file_id,
                    caption=msg.caption,
                    caption_entities=msg.caption_entities,
                    message_thread_id=session.current_thread_id
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
    """Send welcome message"""
    if not session.validate_user(update.message.from_user.id):
        return
    
    welcome_msg = (
        "🚀 *Content Forwarder Bot*\n\n"
        "1. Use /create_topic TOPIC_NAME\n"
        "2. Send STARTING message link\n"
        "3. Send ENDING message link\n"
        "4. Bot will forward all messages"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def create_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /create_topic command"""
    if not session.validate_user(update.message.from_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    if not context.args:
        await update.message.reply_text("Usage: /create_topic TOPIC_NAME")
        return

    session.reset()
    session.current_topic_name = ' '.join(context.args)

    try:
        # Create forum topic in destination group
        result = await context.bot.create_forum_topic(
            chat_id=Config.DESTINATION_GROUP_ID,
            name=session.current_topic_name
        )
        session.current_thread_id = result.message_thread_id
        
        await update.message.reply_text(
            f"✅ Topic '{session.current_topic_name}' created!\n\n"
            "Now send the STARTING message link from channel:"
        )
    except Exception as e:
        logger.error(f"Topic creation failed: {e}")
        await update.message.reply_text("⚠️ Failed to create topic")
        session.reset()

async def handle_message_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process message links for start/end points"""
    if not session.validate_user(update.message.from_user.id):
        return

    if not session.current_thread_id:
        await update.message.reply_text("⚠️ First create a topic with /create_topic")
        return

    message_id = extract_message_id(update.message.text)
    if not message_id:
        await update.message.reply_text("❌ Invalid link format. Send a proper Telegram message link.")
        return

    if not session.start_message_id:
        session.start_message_id = message_id
        await update.message.reply_text(
            "🔗 Got STARTING link!\n"
            "Now send the ENDING message link from channel:"
        )
    elif not session.end_message_id:
        session.end_message_id = message_id
        if session.end_message_id < session.start_message_id:
            await update.message.reply_text("❌ Ending link must come after starting link!")
            session.reset()
            return

        total_messages = session.end_message_id - session.start_message_id + 1
        session.progress_message = await update.message.reply_text(
            f"⏳ Preparing to forward {total_messages} messages..."
        )

        # Start forwarding process
        asyncio.create_task(process_messages(update, context))

async def process_messages(update: Update, context: CallbackContext):
    """Process all messages between start and end IDs"""
    try:
        success_count = 0
        total_messages = session.end_message_id - session.start_message_id + 1
        failed_count = 0

        for msg_id in range(session.start_message_id, session.end_message_id + 1):
            try:
                if await copy_content(update, context, msg_id):
                    success_count += 1
                else:
                    failed_count += 1

                # Update progress every 5 messages
                if (success_count + failed_count) % 5 == 0 or msg_id == session.end_message_id:
                    await session.progress_message.edit_text(
                        f"⏳ Progress: {success_count + failed_count}/{total_messages}\n"
                        f"✅ Success: {success_count}\n"
                        f"❌ Failed: {failed_count}"
                    )

                await asyncio.sleep(Config.DELAY_BETWEEN_FORWARDS)

            except Exception as e:
                logger.warning(f"Skipped message {msg_id}: {e}")
                failed_count += 1
                continue

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Process complete!\n\n"
                 f"• Topic: {session.current_topic_name}\n"
                 f"• Total messages: {total_messages}\n"
                 f"• Successfully processed: {success_count}\n"
                 f"• Failed: {failed_count}",
            reply_to_message_id=session.progress_message.message_id
        )

    except Exception as e:
        logger.error(f"Processing failed: {e}")
        await update.message.reply_text("⚠️ Processing failed")
    finally:
        session.reset()

def main():
    """Start the bot"""
    Config.validate()
    
    app = ApplicationBuilder().token(Config.TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler(["create_topic", "createtopic"], create_topic))

    # Message link handler
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        handle_message_link
    ))

    logger.info("Bot started in polling mode")
    app.run_polling()

if __name__ == "__main__":
    main()
