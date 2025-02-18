import os
import logging
import asyncio
import base64
from io import BytesIO
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from openai import OpenAI, OpenAIError
from collections import defaultdict

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user_id = update.effective_user.id
    try:
        # Create a new thread for the user
        thread = openai_client.beta.threads.create()
        user_threads[user_id] = thread.id
        logger.info(f"Created new thread {thread.id} for user {user_id}")

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
        'You can send me messages or images, and I will assist you!'
    )

async def download_and_encode_image(file):
    """Download image from Telegram and encode it in base64."""
    try:
        logger.info("Starting image download...")
        image_data = await file.download_as_bytearray()
        logger.info(f"Successfully downloaded image, size: {len(image_data)} bytes")

        # Ensure we have valid image data
        if not image_data:
            raise ValueError("Downloaded image data is empty")

        encoded_image = base64.b64encode(image_data).decode('utf-8')
        logger.info("Successfully encoded image to base64")
        return encoded_image
    except Exception as e:
        logger.error(f"Error in download_and_encode_image: {str(e)}", exc_info=True)
        raise

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photo messages."""
    if not update.message or not update.message.photo:
        return

    user_id = update.effective_user.id
    try:
        # Get or create thread ID for this user
        thread_id = user_threads[user_id]
        if not thread_id:
            thread = openai_client.beta.threads.create()
            thread_id = thread.id
            user_threads[user_id] = thread_id
            logger.info(f"Created new thread {thread_id} for user {user_id}")

        # Start typing indication
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=constants.ChatAction.TYPING
        )

        # Get the largest photo (best quality)
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        logger.info(f"Retrieved photo file with ID: {photo.file_id}")

        try:
            # Download and encode the image
            base64_image = await download_and_encode_image(photo_file)
        except Exception as e:
            logger.error(f"Failed to process image: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "I'm having trouble processing the image. Please try sending it again."
            )
            return

        # Get caption if any
        caption = update.message.caption or "Please analyze this image."

        # Create message with image
        try:
            openai_client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=[
                    {
                        "type": "text",
                        "text": caption
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            )
            logger.info("Successfully created message with image in thread")
        except Exception as e:
            logger.error(f"Failed to create message with image: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "I'm having trouble sending the image to the assistant. Please try again."
            )
            return

        # Run the assistant
        try:
            run = openai_client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID
            )
            logger.info(f"Created assistant run with ID: {run.id}")
        except Exception as e:
            logger.error(f"Failed to create assistant run: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "I'm having trouble starting the analysis. Please try again."
            )
            return

        # Wait for the run to complete while maintaining typing indication
        while True:
            # Refresh typing indicator every 4.5 seconds (Telegram's limit is 5 seconds)
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action=constants.ChatAction.TYPING
            )

            try:
                run_status = openai_client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
                if run_status.status == 'completed':
                    break
                elif run_status.status in ['failed', 'cancelled', 'expired']:
                    raise Exception(f"Assistant run failed with status: {run_status.status}")
                await asyncio.sleep(4.5)  # Wait before refreshing typing indicator
            except Exception as e:
                logger.error(f"Error checking run status: {str(e)}", exc_info=True)
                await update.message.reply_text(
                    "I encountered an error while analyzing the image. Please try again."
                )
                return

        # Get the assistant's response
        try:
            messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
            assistant_message = messages.data[0].content[0].text.value
            logger.info(f"Sending response to user {user_id}: {assistant_message}")

            await update.message.reply_text(assistant_message)
        except Exception as e:
            logger.error(f"Error getting assistant response: {str(e)}", exc_info=True)
            await update.message.reply_text(
                "I analyzed the image but had trouble retrieving the response. Please try again."
            )

    except OpenAIError as openai_error:
        logger.error(f"OpenAI API error: {str(openai_error)}", exc_info=True)
        await update.message.reply_text(
            "I'm having trouble analyzing the image. Please try again in a moment."
        )
    except Exception as e:
        logger.error(f"Error handling photo: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "I apologize, but I encountered an error processing your image. Please try again."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages and respond using OpenAI Assistant."""
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    try:
        # Get or create thread ID for this user
        thread_id = user_threads[user_id]
        if not thread_id:
            thread = openai_client.beta.threads.create()
            thread_id = thread.id
            user_threads[user_id] = thread_id
            logger.info(f"Created new thread {thread_id} for user {user_id}")

        # Add the user's message to the thread
        message_text = update.message.text
        logger.info(f"Received message from user {user_id}: {message_text}")

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
            # Refresh typing indicator every 4.5 seconds (Telegram's limit is 5 seconds)
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
                raise Exception(f"Assistant run failed with status: {run_status.status}")
            await asyncio.sleep(4.5)  # Wait before refreshing typing indicator

        # Get the assistant's response
        messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
        assistant_message = messages.data[0].content[0].text.value
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

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.error(f'Update "{update}" caused error "{context.error}"', exc_info=True)

def setup_telegram_bot():
    """Initialize and setup the Telegram bot."""
    try:
        # Create the Application
        application = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

        # Add error handler
        application.add_error_handler(error_handler)

        return application
    except Exception as e:
        logger.error(f"Error setting up Telegram bot: {str(e)}", exc_info=True)
        raise

def run_telegram_bot():
    """Run the Telegram bot."""
    try:
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        application = setup_telegram_bot()
        logger.info("Starting Telegram bot polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error running Telegram bot: {str(e)}", exc_info=True)
        raise