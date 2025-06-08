import os
import re
import asyncio
import logging
from typing import Optional, Tuple

from telegram import Update
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
        self.progress_message: Optional[int] = None

    def reset(self):
        self.__init__()

    def validate_user(self, user_id: int) -> bool:
        return user_id in Config.AUTHORIZED_USER_IDS

session = ForwardSession()

def extract_message_id(link: str) -> Optional[int]:
    """Extract message ID from Telegram message link"""
    match = re.search(r"/(\d+)$", link)
    return int(match.group(1)) if match else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    if not session.validate_user(update.message.from_user.id):
        return
    
    welcome_msg = (
        "🚀 *Content Forwarder Bot*\n\n"
        "1. Use /create_topic TOPIC_NAME to create new topic\n"
        "2. Send STARTING message link from channel\n"
        "3. Send ENDING message link from channel\n"
        "4. Bot will forward all messages between them"
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
        asyncio.create_task(
            forward_messages(update, context)
        )

async def forward_messages(update: Update, context: CallbackContext):
    """Forward messages between start and end IDs"""
    try:
        forwarded_count = 0
        total_messages = session.end_message_id - session.start_message_id + 1

        for msg_id in range(session.start_message_id, session.end_message_id + 1):
            try:
                await context.bot.forward_message(
                    chat_id=Config.DESTINATION_GROUP_ID,
                    from_chat_id=Config.SOURCE_CHANNEL_ID,
                    message_id=msg_id,
                    message_thread_id=session.current_thread_id
                )
                forwarded_count += 1

                # Update progress every 5 messages
                if forwarded_count % 5 == 0 or msg_id == session.end_message_id:
                    await session.progress_message.edit_text(
                        f"⏳ Forwarding: {forwarded_count}/{total_messages} messages..."
                    )

                await asyncio.sleep(Config.DELAY_BETWEEN_FORWARDS)

            except Exception as e:
                logger.warning(f"Skipped message {msg_id}: {e}")
                continue

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Forwarding complete!\n\n"
                 f"• Topic: {session.current_topic_name}\n"
                 f"• Messages forwarded: {forwarded_count}/{total_messages}",
            reply_to_message_id=session.progress_message.message_id
        )

    except Exception as e:
        logger.error(f"Forwarding failed: {e}")
        await update.message.reply_text("⚠️ Forwarding process failed")
    finally:
        session.reset()

def main():
    """Start the bot"""
    Config.validate()
    
    app = ApplicationBuilder().token(Config.TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("create_topic", create_topic))

    # Message link handler
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        handle_message_link
    ))

    logger.info("Bot started in polling mode")
    app.run_polling()

if __name__ == "__main__":
    main()
