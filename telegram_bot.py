import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
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
        'Hello! I am your AI assistant. You can send me text or images, and I will analyze them!'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        'You can send me:\n' +
        '1. Any text message for a conversation\n' +
        '2. Any image for analysis'
    )

async def analyze_image_with_openai(image_data):
    """Analyze image using OpenAI's Vision model."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",  # the newest OpenAI model is "gpt-4o" which was released May 13, 2024
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze this image in detail and describe what you see."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}"
                            }
                        }
                    ]
                }
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error analyzing image with OpenAI: {e}")
        return "Sorry, I encountered an error while analyzing the image. Please try again."

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos."""
    try:
        # Get the photo with the highest resolution
        photo = update.message.photo[-1]

        # Download the photo
        photo_file = await context.bot.get_file(photo.file_id)
        photo_bytes = await photo_file.download_as_bytearray()

        # Convert to base64
        import base64
        image_base64 = base64.b64encode(photo_bytes).decode('utf-8')

        # Send a message while processing
        processing_message = await update.message.reply_text("Processing your image...")

        # Analyze the image with OpenAI
        analysis = await analyze_image_with_openai(image_base64)

        # Send the analysis
        await processing_message.edit_text(analysis)

    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await update.message.reply_text(
            "I apologize, but I encountered an error processing your image. Please try again."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages and respond using OpenAI."""
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

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.warning(f'Update "{update}" caused error "{context.error}"')

def setup_telegram_bot():
    """Initialize and setup the Telegram bot."""
    # Create the Application
    application = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Add error handler
    application.add_error_handler(error_handler)

    return application

def run_telegram_bot():
    """Run the Telegram bot."""
    # Create a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run the bot
    application = setup_telegram_bot()
    application.run_polling(allowed_updates=Update.ALL_TYPES)