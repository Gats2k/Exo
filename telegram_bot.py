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
    logger.info("Received /start command")
    await update.message.reply_text(
        'Hello! I am your AI assistant. How can I help you today?'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages and respond using OpenAI."""
    try:
        message_text = update.message.text
        logger.info(f"Received message: {message_text}")

        # Call OpenAI API to get a response
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": message_text}
            ]
        )

        # Extract and send the response
        ai_response = response.choices[0].message.content
        logger.info(f"AI Response: {ai_response}")
        await update.message.reply_text(ai_response)

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        await update.message.reply_text(
            "I apologize, but I encountered an error processing your message. Please try again."
        )

async def run_telegram_bot_async():
    """Run the telegram bot asynchronously."""
    try:
        # Create and setup application
        application = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("Starting Telegram bot...")
        await application.initialize()
        await application.start()
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error in run_telegram_bot: {e}", exc_info=True)

def run_telegram_bot():
    """Run the telegram bot in its own event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_telegram_bot_async())
    except Exception as e:
        logger.error(f"Error in telegram bot event loop: {e}", exc_info=True)
    finally:
        loop.close()