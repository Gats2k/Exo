# Move eventlet monkey patch to top
import eventlet
eventlet.monkey_patch()

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
from contextlib import contextmanager
from mathpix_utils import process_image_with_mathpix

# Import models after eventlet patch
from models import TelegramUser, TelegramConversation, TelegramMessage
from database import db
from app import (
get_db_context, 
get_ai_client,
get_model_name,
get_system_instructions,
call_gemini_api,
app  # Import the app instance to access its context
)

# Define getter functions that always access the latest values
def get_current_model():
    """Get the current AI model setting from the app configuration."""
    # Import dynamiquement à chaque appel pour toujours avoir la dernière valeur
    import os
    import importlib

    # Recharger dynamiquement le module app pour obtenir la valeur actualisée
    app_module = importlib.import_module('app')
    importlib.reload(app_module)

    # Vérifier d'abord dans l'environnement (prioritaire)
    env_model = os.environ.get('CURRENT_MODEL')
    if env_model:
        return env_model

    # Sinon utiliser la valeur du module app
    return app_module.CURRENT_MODEL

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

async def get_or_create_telegram_user(user_id: int, first_name: str = None, last_name: str = None) -> TelegramUser:
    """Get or create a TelegramUser record with name information."""
    try:
        with db_retry_session() as session:
            logger.info(f"Attempting to get or create TelegramUser for ID: {user_id}")
            
            # Utiliser une requête directe pour éviter les problèmes de colonnes
            user = session.query(TelegramUser).filter(TelegramUser.telegram_id == user_id).first()
            
            if not user:
                logger.info(f"Creating new TelegramUser for ID: {user_id}")
                try:
                    # Essayer d'abord avec last_name
                    user = TelegramUser(
                        telegram_id=user_id,
                        first_name=first_name or "---",
                        last_name=last_name or "---"
                    )
                except Exception as create_error:
                    logger.warning(f"Error creating user with last_name: {str(create_error)}")
                    # Essayer sans last_name si ça échoue
                    user = TelegramUser(
                        telegram_id=user_id,
                        first_name=first_name or "---"
                    )
                session.add(user)
                session.commit()
                logger.info(f"Successfully created TelegramUser: {user.telegram_id} ({first_name})")
            else:
                # Mettre à jour les noms s'ils ont changé
                updated = False
                if first_name and user.first_name != first_name:
                    user.first_name = first_name
                    updated = True
                
                # Essayer de mettre à jour last_name de manière sécurisée
                try:
                    if last_name and hasattr(user, 'last_name') and user.last_name != last_name:
                        user.last_name = last_name
                        updated = True
                except Exception as last_name_error:
                    logger.warning(f"Error updating last_name: {str(last_name_error)}")
                
                if updated:
                    session.commit()
                    logger.info(f"Updated user {user_id} with new information")
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
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    try:
        # Create or get the user in our database
        await get_or_create_telegram_user(user_id, first_name, last_name)

        # Create a new thread for the user
        thread = openai_client.beta.threads.create()
        user_threads[user_id] = thread.id
        logger.info(f"Created new thread {thread.id} for user {user_id}")

        # Create a new conversation in our database
        await create_telegram_conversation(user_id, thread.id)

        await update.message.reply_text(
            '🤓'
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
    """Handle incoming messages and respond using selected AI model."""
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name or ""  # Handle None values
    logger.info(f"Processing message from user {user_id} ({first_name} {last_name})")

    try:
        # Get or create user first
        user = await get_or_create_telegram_user(user_id, first_name, last_name)
        logger.info(f"User {user_id} retrieved/created successfully")

        # Ensure user_threads dict is initialized for this user
        if user_id not in user_threads:
            user_threads[user_id] = None

        with db_retry_session() as session:
            # Get or create thread ID for this user
            thread_id = user_threads[user_id]
            if not thread_id:
                # Create a new thread ID
                current_model = get_current_model()  # Get latest model setting
                if current_model == 'openai':
                    thread = openai_client.beta.threads.create()
                    thread_id = thread.id
                else:
                    # For other models, create a unique thread ID
                    thread_id = f"thread_{user_id}_{int(time.time())}"
                
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

            # Get the current model selected from dashboard
            current_model = get_current_model()  # Get latest model setting
            logger.info(f"Using AI model: {current_model} with instructions: {get_system_instructions()}")

            # Different handling based on selected model
            assistant_message = None

            if current_model == 'openai':
                # Use OpenAI's assistant API
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
            else:
                # For other models (Gemini, Deepseek, Qwen), use direct API calls
                current_model = get_current_model()  # Get latest model setting
                logger.info(f"Using alternative model: {current_model} with model name: {get_model_name()}")
                
                # Get previous messages for context (limit to last 10)
                previous_messages = []
                with db_retry_session() as sess:
                    messages_query = TelegramMessage.query.filter_by(conversation_id=conversation.id).order_by(TelegramMessage.created_at.desc()).limit(10).all()
                    for msg in reversed(messages_query):
                        previous_messages.append({
                            "role": msg.role,
                            "content": msg.content
                        })

                # Add system instruction
                system_instructions = get_system_instructions()
                if system_instructions:
                    previous_messages.insert(0, {
                        "role": "system",
                        "content": system_instructions
                    })
                
                # Use Gemini's special call function if Gemini is selected
                if current_model == 'gemini':
                    try:
                        assistant_message = call_gemini_api(previous_messages)
                    except Exception as e:
                        logger.error(f"Error calling Gemini API: {str(e)}")
                        raise
                else:
                    # For DeepSeek and Qwen models
                    ai_client = get_ai_client()
                    model = get_model_name()
                    
                    try:
                        # Format messages for the API call
                        response = ai_client.chat.completions.create(
                            model=model,
                            messages=previous_messages
                        )
                        assistant_message = response.choices[0].message.content
                    except Exception as e:
                        logger.error(f"Error calling AI API ({current_model}): {str(e)}")
                        raise

            # Store the assistant's response in our database
            await add_telegram_message(conversation.id, 'assistant', assistant_message)

            logger.info(f"Sending response to user {user_id}: {assistant_message[:100]}...")
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
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name or ""  # Handle None values
    try:
        # Get or create user first
        user = await get_or_create_telegram_user(user_id, first_name, last_name)
        logger.info(f"User {user_id} retrieved/created successfully")

        # Ensure user_threads dict is initialized for this user
        if user_id not in user_threads:
            user_threads[user_id] = None

        with db_retry_session() as session:
            logger.info(f"Receiving photo from user {user_id}")

            if not update.message or not update.message.photo:
                logger.error("No photo found in the message")
                return

            # Get or create thread ID for this user
            thread_id = user_threads[user_id]
            if not thread_id:
                # Create a new thread ID
                current_model = get_current_model()  # Get latest model setting
                if current_model == 'openai':
                    thread = openai_client.beta.threads.create()
                    thread_id = thread.id
                else:
                    # For other models, create a unique thread ID
                    thread_id = f"thread_{user_id}_{int(time.time())}"
                
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

            # Téléchargement et conversion de l'image en base64
            base64_image = await download_telegram_image(file_url)
            if not base64_image:
                logger.error("Failed to download or convert image")
                await update.message.reply_text(
                    "I'm having trouble processing your image. Please try again."
                )
                return

            # Traitement avec Mathpix
            mathpix_result = process_image_with_mathpix(base64_image)

            # Variables pour stocker les résultats
            formatted_summary = None

            # Vérification d'erreur Mathpix
            if "error" in mathpix_result:
                logger.error(f"Mathpix error: {mathpix_result['error']}")
                formatted_summary = "Image content extraction failed. I will analyze the image visually."
            else:
                formatted_summary = mathpix_result.get("formatted_summary", "")
                logger.info(f"Mathpix extraction successful. Content types: math={mathpix_result.get('has_math')}, table={mathpix_result.get('has_table')}, chemistry={mathpix_result.get('has_chemistry')}, geometry={mathpix_result.get('has_geometry')}")

            # Récupération de la légende si présente
            caption = update.message.caption or ""

            # Construction du message pour l'assistant
            message_for_assistant = ""

            # Ajout du message de l'utilisateur s'il existe
            if caption:
                message_for_assistant += f"{caption}\n\n"

            # Ajout des résultats d'extraction Mathpix
            if formatted_summary:
                message_for_assistant += formatted_summary
            else:
                # Message par défaut si pas d'extraction et pas de message utilisateur
                if not caption:
                    message_for_assistant = "Please analyze the image I uploaded."

            # Construction du contenu à stocker en BDD
            user_store_content = caption
            if formatted_summary:
                if caption:
                    user_store_content = f"{caption}\n\n[Extracted Image Content]\n{formatted_summary}"
                else:
                    user_store_content = f"[Extracted Image Content]\n{formatted_summary}"

            # Mise à jour du titre de la conversation si c'est une nouvelle conversation
            if conversation.title == "Nouvelle conversation" and mathpix_result:
                content_types = []
                if mathpix_result.get("has_math"): content_types.append("math")
                if mathpix_result.get("has_table"): content_types.append("table")
                if mathpix_result.get("has_chemistry"): content_types.append("chemistry")
                if mathpix_result.get("has_geometry"): content_types.append("geometry")

                if content_types:
                    new_title = f"Image ({', '.join(content_types)})"
                else:
                    new_title = "Image"

                conversation.title = new_title
                session.commit()
                logger.info(f"Updated conversation title to: {new_title}")

            # Store the user's message in our database
            await add_telegram_message(conversation.id, 'user', user_store_content, file_url)

            # Get the current model selected from dashboard
            current_model = get_current_model()  # Get latest model setting
            logger.info(f"Using AI model for image processing: {current_model}")

            # Different handling based on selected model
            assistant_message = None

            if current_model == 'openai':
                # Send to OpenAI (text only, not image)
                logger.info(f"Sending extracted content to OpenAI thread {thread_id}")
                openai_client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=message_for_assistant
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

                # Get the assistant's response
                messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
                assistant_message = messages.data[0].content[0].text.value
            else:
                # For other models (Gemini, Deepseek, Qwen), use direct API calls
                logger.info(f"Using alternative model for image: {current_model} with model name: {get_model_name()}")
                
                # Get previous messages for context (limit to last 10)
                previous_messages = []
                with db_retry_session() as sess:
                    messages_query = TelegramMessage.query.filter_by(conversation_id=conversation.id).order_by(TelegramMessage.created_at.desc()).limit(10).all()
                    for msg in reversed(messages_query):
                        if msg.role == 'user' and msg.content == user_store_content:
                            # Skip this message as we're adding it below
                            continue
                        previous_messages.append({
                            "role": msg.role,
                            "content": msg.content
                        })
                
                # Add the current message
                previous_messages.append({
                    "role": "user", 
                    "content": message_for_assistant
                })

                # Add system instruction
                system_instructions = get_system_instructions()
                if system_instructions:
                    previous_messages.insert(0, {
                        "role": "system",
                        "content": system_instructions
                    })
                
                # Use Gemini's special call function if Gemini is selected
                if current_model == 'gemini':
                    try:
                        assistant_message = call_gemini_api(previous_messages)
                    except Exception as e:
                        logger.error(f"Error calling Gemini API for image processing: {str(e)}")
                        raise
                else:
                    # For DeepSeek and Qwen models
                    ai_client = get_ai_client()
                    model = get_model_name()
                    
                    try:
                        # Format messages for the API call
                        response = ai_client.chat.completions.create(
                            model=model,
                            messages=previous_messages
                        )
                        assistant_message = response.choices[0].message.content
                    except Exception as e:
                        logger.error(f"Error calling AI API ({current_model}) for image processing: {str(e)}")
                        raise

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

async def download_telegram_image(file_url):
    """Télécharge l'image depuis l'URL Telegram et la convertit en base64"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as response:
                if response.status == 200:
                    image_data = await response.read()
                    # Conversion en base64
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    return f"data:image/jpeg;base64,{base64_image}"
                else:
                    logger.error(f"Failed to download image: HTTP {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error downloading image: {str(e)}")
        return None

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
    try:
        # Only run if explicitly enabled
        if not os.environ.get('RUN_TELEGRAM_BOT'):
            logger.info("Telegram bot is disabled. Set RUN_TELEGRAM_BOT=true to enable.")
            return

        # Log current configuration 
        current_model = get_current_model()  # Get latest model setting
        logger.info(f"Telegram bot starting with model: {current_model}")
        
        # Nous n'appelons pas get_system_instructions() ici car elle peut ne pas être disponible
        # dans ce contexte (importation circulaire potentielle)
        
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        application = setup_telegram_bot()
        logger.info("Starting Telegram bot polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Error running Telegram bot: {str(e)}", exc_info=True)
        raise

if __name__ == '__main__':
    run_telegram_bot()