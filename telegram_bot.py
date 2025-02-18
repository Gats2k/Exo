import os
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, Update
from openai import OpenAI

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        'Hello! I am your AI assistant. How can I help you today? You can send me text or images!'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        'You can send me any message or image and I will respond using AI!'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages and respond using OpenAI."""
    try:
        # Get the message text
        message_text = update.message.text

        # Call OpenAI API to get a response
        response = openai_client.chat.completions.create(
            model="gpt-4o",  # the newest OpenAI model is "gpt-4o" which was released May 13, 2024
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": message_text}
            ]
        )

        # Extract and send the response
        ai_response = response.choices[0].message.content
        await update.message.reply_text(ai_response)

    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text(
            "I apologize, but I encountered an error processing your message. Please try again."
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos and respond using OpenAI Vision."""
    try:
        # Get the photo file with the highest resolution
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()

        # Get the photo URL
        photo_url = photo_file.file_path

        # Call OpenAI API to analyze the image
        response = openai_client.chat.completions.create(
            model="gpt-4o",  # the newest OpenAI model is "gpt-4o" which was released May 13, 2024
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What's in this image? Please describe it in detail."},
                        {"type": "image_url", "image_url": {"url": photo_url}}
                    ]
                }
            ]
        )

        # Extract and send the response
        ai_response = response.choices[0].message.content
        await update.message.reply_text(ai_response)

    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await update.message.reply_text(
            "I apologize, but I encountered an error processing your image. Please try again."
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.warning(f'Update "{update}" caused error "{context.error}"')

async def setup_telegram_bot():
    """Initialize and setup the Telegram bot."""
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

async def run_telegram_bot():
    """Run the Telegram bot."""
    application = await setup_telegram_bot()
    await application.initialize()
    await application.start()
    await application.run_polling(allowed_updates=Update.ALL_TYPES)