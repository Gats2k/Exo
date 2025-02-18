import os
import logging
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import uuid
from pathlib import Path
from openai import OpenAI

# Configuration du dossier pour les images
UPLOAD_FOLDER = 'static/uploads'
Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)

async def download_image(file_path: str, save_path: str):
    """Télécharge une image depuis Telegram."""
    async with aiohttp.ClientSession() as session:
        async with session.get(file_path) as response:
            if response.status == 200:
                with open(save_path, 'wb') as f:
                    f.write(await response.read())
                return True
    return False

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les images reçues."""
    try:
        # Obtenir le fichier photo (prendre la plus grande résolution disponible)
        photo = update.message.photo[-1]

        # Obtenir le chemin du fichier
        file = await context.bot.get_file(photo.file_id)

        # Générer un nom unique pour l'image
        filename = f"{uuid.uuid4()}.jpg"
        save_path = os.path.join(UPLOAD_FOLDER, filename)

        # Télécharger l'image
        success = await download_image(file.file_path, save_path)

        if not success:
            await update.message.reply_text("Désolé, je n'ai pas pu traiter votre image.")
            return

        # Lire le fichier en base64
        import base64
        with open(save_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            image_url = f"data:image/jpeg;base64,{encoded_string}"

        # Obtenir le texte de la légende si présent
        caption = update.message.caption or "Analyze this image"

        # Appeler l'API OpenAI avec l'image
        thread = openai_client.beta.threads.create()

        # Créer le message avec l'image
        openai_client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=[
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url
                    }
                },
                {
                    "type": "text",
                    "text": caption
                }
            ]
        )

        # Créer et attendre la réponse
        run = openai_client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=os.environ["OPENAI_ASSISTANT_ID"]
        )

        # Attendre la réponse
        while True:
            run_status = openai_client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            if run_status.status == 'completed':
                break
            elif run_status.status == 'failed':
                await update.message.reply_text("Désolé, une erreur s'est produite lors de l'analyse de l'image.")
                return

        # Récupérer la réponse
        messages = openai_client.beta.threads.messages.list(thread_id=thread.id)
        assistant_message = messages.data[0].content[0].text.value

        # Envoyer la réponse
        await update.message.reply_text(assistant_message)

    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await update.message.reply_text(
            "Je suis désolé, mais j'ai rencontré une erreur en traitant votre image. Veuillez réessayer."
        )

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
        'Hello! I am your AI assistant. How can I help you today?'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        'You can send me any message and I will respond using AI!'
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    return application

def run_telegram_bot():
    """Run the Telegram bot."""
    application = setup_telegram_bot()
    application.run_polling(allowed_updates=Update.ALL_TYPES)
