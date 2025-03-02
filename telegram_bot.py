import os
import logging
import asyncio
import time
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from openai import OpenAI, OpenAIError
from collections import defaultdict
import aiohttp
from pathlib import Path
import uuid
from datetime import datetime
import base64
import requests
from models import TelegramUser, TelegramConversation, TelegramMessage
from database import db
from app import get_db_context
from contextlib import contextmanager

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  
)
logger = logging.getLogger(__name__)

# Initialize OpenAI client with error handling
try:
    openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    ASSISTANT_ID = os.environ.get("OPENAI_ASSISTANT_ID")
    if not ASSISTANT_ID:
        raise ValueError("OPENAI_ASSISTANT_ID environment variable is not set")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {str(e)}", exc_info=True)
    raise

# Store thread IDs for each user
user_threads = defaultdict(lambda: None)

@contextmanager
def db_retry_session(max_retries=3, retry_delay=1):
    """Context manager for database operations with retry logic"""
    for attempt in range(max_retries):
        try:
            with get_db_context():
                yield db.session
                break
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Database error after {max_retries} attempts: {str(e)}", exc_info=True)
                raise
            logger.warning(f"Database operation failed, retrying... (attempt {attempt + 1}/{max_retries})")
            time.sleep(retry_delay)

async def get_or_create_telegram_user(user_id: int) -> TelegramUser:
    """Get or create a TelegramUser record."""
    try:
        with db_retry_session() as session:
            logger.info(f"Attempting to get or create TelegramUser for ID: {user_id}")
            user = TelegramUser.query.get(user_id)
            if not user:
                logger.info(f"Creating new TelegramUser for ID: {user_id}")
                user = TelegramUser(telegram_id=user_id)
                session.add(user)
                session.commit()
                logger.info(f"Successfully created TelegramUser: {user.telegram_id}")
            else:
                logger.info(f"Found existing TelegramUser: {user.telegram_id}")
            return user
    except Exception as e:
        logger.error(f"Error in get_or_create_telegram_user: {str(e)}", exc_info=True)
        raise

async def create_telegram_conversation(user_id: int, thread_id: str) -> TelegramConversation:
    """Create a new TelegramConversation record."""
    try:
        with db_retry_session() as session:
            logger.info(f"Creating new TelegramConversation for user {user_id} with thread {thread_id}")
            conversation = TelegramConversation(
                telegram_user_id=user_id,
                thread_id=thread_id,
                title="Nouvelle conversation"
            )
            session.add(conversation)
            session.commit()
            logger.info(f"Successfully created TelegramConversation: {conversation.id}")
            return conversation
    except Exception as e:
        logger.error(f"Error in create_telegram_conversation: {str(e)}", exc_info=True)
        raise

async def add_telegram_message(conversation_id: int, role: str, content: str, image_url: str = None):
    """Add a new message to a conversation."""
    try:
        with db_retry_session() as session:
            logger.info(f"Adding new TelegramMessage to conversation {conversation_id}")
            message = TelegramMessage(
                conversation_id=conversation_id,
                role=role,
                content=content,
                image_url=image_url
            )
            session.add(message)
            session.commit()
            logger.info(f"Successfully added TelegramMessage: {message.id}")
    except Exception as e:
        logger.error(f"Error in add_telegram_message: {str(e)}", exc_info=True)
        raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user_id = update.effective_user.id
    try:
        # Create or get the user in our database
        await get_or_create_telegram_user(user_id)

        # Create a new thread for the user
        thread = openai_client.beta.threads.create()
        user_threads[user_id] = thread.id
        logger.info(f"Created new thread {thread.id} for user {user_id}")

        # Create a new conversation in our database
        await create_telegram_conversation(user_id, thread.id)

        await update.message.reply_text(
            'Hello! I am your AI assistant. How can I help you today?'
        )
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "I'm having trouble setting up our conversation. Please try again in a moment."
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        'You can send me any message and I will respond using AI!'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages and respond using OpenAI Assistant."""
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    logger.info(f"Processing message from user {user_id}")

    try:
        # Get or create user first
        user = await get_or_create_telegram_user(user_id)
        logger.info(f"User {user_id} retrieved/created successfully")

        with db_retry_session() as session:
            # Get or create thread ID for this user
            thread_id = user_threads[user_id]
            if not thread_id:
                thread = openai_client.beta.threads.create()
                thread_id = thread.id
                user_threads[user_id] = thread_id
                logger.info(f"Created new thread {thread_id} for user {user_id}")
                # Create a new conversation in our database
                conversation = await create_telegram_conversation(user_id, thread_id)
            else:
                # Get existing conversation
                conversation = TelegramConversation.query.filter_by(thread_id=thread_id).first()
                if not conversation:
                    logger.error(f"No conversation found for thread_id {thread_id}")
                    conversation = await create_telegram_conversation(user_id, thread_id)

            # Add the user's message to the thread
            message_text = update.message.text
            logger.info(f"Received message from user {user_id}: {message_text}")

            # Store the user's message in our database
            await add_telegram_message(conversation.id, 'user', message_text)

            # Start typing indication
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action=constants.ChatAction.TYPING
            )

            openai_client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message_text
            )

            # Run the assistant
            run = openai_client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID
            )

            # Wait for the run to complete while maintaining typing indication
            while True:
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action=constants.ChatAction.TYPING
                )

                run_status = openai_client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
                if run_status.status == 'completed':
                    break
                elif run_status.status in ['failed', 'cancelled', 'expired']:
                    error_msg = f"Assistant run failed with status: {run_status.status}"
                    logger.error(error_msg)
                    raise Exception(error_msg)
                await asyncio.sleep(4.5)

            # Get the assistant's response
            messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
            assistant_message = messages.data[0].content[0].text.value

            # Store the assistant's response in our database
            await add_telegram_message(conversation.id, 'assistant', assistant_message)

            logger.info(f"Sending response to user {user_id}: {assistant_message}")
            await update.message.reply_text(assistant_message)

    except OpenAIError as openai_error:
        logger.error(f"OpenAI API error: {str(openai_error)}", exc_info=True)
        await update.message.reply_text(
            "I'm having trouble connecting to my AI brain. Please try again in a moment."
        )
    except Exception as e:
        logger.error(f"Error handling message: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "I apologize, but I encountered an error processing your message. Please try again."
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages containing photos"""
    user_id = update.effective_user.id
    try:
        # Get or create user first
        user = await get_or_create_telegram_user(user_id)
        logger.info(f"User {user_id} retrieved/created successfully")

        with db_retry_session() as session:
            logger.info(f"Receiving photo from user {user_id}")

            if not update.message or not update.message.photo:
                logger.error("No photo found in the message")
                return

            # Get or create thread ID for this user
            thread_id = user_threads[user_id]
            if not thread_id:
                thread = openai_client.beta.threads.create()
                thread_id = thread.id
                user_threads[user_id] = thread_id
                logger.info(f"Created new thread {thread_id} for user {user_id}")
                # Create a new conversation in our database
                conversation = await create_telegram_conversation(user_id, thread_id)
            else:
                # Get existing conversation
                conversation = TelegramConversation.query.filter_by(thread_id=thread_id).first()
                if not conversation:
                    logger.error(f"No conversation found for thread_id {thread_id}")
                    conversation = await create_telegram_conversation(user_id, thread_id)

            logger.info(f"Photo details: {update.message.photo[-1]}")

            # Get file URL directly from Telegram
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            file_url = file.file_path
            logger.info(f"Got file URL from Telegram: {file_url}")

            # Start typing indication
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action=constants.ChatAction.TYPING
            )

            # Create message content with image
            message_content = [{
                "type": "image_url",
                "image_url": {
                    "url": file_url
                }
            }]

            # Add caption if present
            caption = update.message.caption or "Image sent"
            message_content.append({
                "type": "text",
                "text": caption
            })

            # Store the user's message in our database
            await add_telegram_message(conversation.id, 'user', caption, file_url)

            # Send to OpenAI
            logger.info(f"Sending message to OpenAI thread {thread_id}")
            openai_client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message_content
            )
            logger.info("Message sent to OpenAI")

            # Run the assistant
            run = openai_client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID
            )
            logger.info("Assistant run created")

            # Wait for completion
            while True:
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action=constants.ChatAction.TYPING
                )

                run_status = openai_client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
                if run_status.status == 'completed':
                    logger.info("Assistant run completed")
                    break
                elif run_status.status in ['failed', 'cancelled', 'expired']:
                    error_msg = f"Assistant run failed with status: {run_status.status}"
                    logger.error(error_msg)
                    raise Exception(error_msg)
                await asyncio.sleep(4.5)

            # Get and send response
            messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
            assistant_message = messages.data[0].content[0].text.value

            # Store the assistant's response in our database
            await add_telegram_message(conversation.id, 'assistant', assistant_message)

            logger.info(f"Sending response: {assistant_message[:100]}...")
            await update.message.reply_text(assistant_message)

    except Exception as e:
        logger.error(f"Error handling photo: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "I apologize, but I encountered an error processing your image. Please try again."
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.error(f'Update "{update}" caused error "{context.error}"', exc_info=True)

def setup_telegram_bot():
    """Initialize and setup the Telegram bot."""
    try:
        logger.info("Starting Telegram bot setup...")

        # Create the Application
        application = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        logger.info("Handlers added successfully")

        # Add error handler
        application.add_error_handler(error_handler)
        logger.info("Error handler added")

        logger.info("Telegram bot setup completed successfully")
        return application
    except Exception as e:
        logger.error(f"Error setting up Telegram bot: {str(e)}", exc_info=True)
        raise

def run_telegram_bot():
    """Run the Telegram bot."""
    try:
        # Only run if explicitly enabled
        if not os.environ.get('RUN_TELEGRAM_BOT'):
            logger.info("Telegram bot is disabled. Set RUN_TELEGRAM_BOT=true to enable.")
            return

        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        application = setup_telegram_bot()
        logger.info("Starting Telegram bot polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error running Telegram bot: {str(e)}", exc_info=True)
        raise

if __name__ == '__main__':
    run_telegram_bot()