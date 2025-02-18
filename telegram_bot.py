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
        'Bonjour! Je suis votre assistant IA. Vous pouvez m\'envoyer du texte ou des images à analyser!'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        'Vous pouvez m\'envoyer:\n' +
        '1. Un message texte pour une conversation\n' +
        '2. Une image pour l\'analyse'
    )

async def analyze_image_with_openai(image_data):
    """Analyze image using OpenAI's Vision model."""
    try:
        logger.info("Starting image analysis with OpenAI")
        response = openai_client.chat.completions.create(
            model="gpt-4-vision-preview",  # Use vision-specific model
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Décrivez cette image en détail en français."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=500
        )
        logger.info("Successfully received OpenAI response")
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error analyzing image with OpenAI: {str(e)}")
        return "Désolé, une erreur s'est produite lors de l'analyse de l'image. Veuillez réessayer."

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos."""
    try:
        # Get the photo with the highest resolution
        photo = update.message.photo[-1]
        logger.info(f"Received photo with file_id: {photo.file_id}")

        # Send initial processing message
        processing_message = await update.message.reply_text("Traitement de votre image en cours...")

        # Download the photo
        photo_file = await context.bot.get_file(photo.file_id)
        photo_bytes = await photo_file.download_as_bytearray()

        # Convert to base64
        import base64
        image_base64 = base64.b64encode(photo_bytes).decode('utf-8')
        logger.info("Successfully converted image to base64")

        # Analyze the image with OpenAI
        analysis = await analyze_image_with_openai(image_base64)

        # Send the analysis
        await processing_message.edit_text(analysis)

    except Exception as e:
        logger.error(f"Error handling photo: {str(e)}")
        await update.message.reply_text(
            "Désolé, une erreur s'est produite lors du traitement de votre image. Veuillez réessayer."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages and respond using OpenAI."""
    try:
        message_text = update.message.text
        logger.info(f"Received message: {message_text}")

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Vous êtes un assistant serviable qui répond en français."},
                {"role": "user", "content": message_text}
            ]
        )

        ai_response = response.choices[0].message.content
        await update.message.reply_text(ai_response)

    except Exception as e:
        logger.error(f"Error handling message: {str(e)}")
        await update.message.reply_text(
            "Désolé, une erreur s'est produite. Veuillez réessayer."
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