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
from app import get_db_context

def get_app_config():
    """
    Récupère dynamiquement les configurations actuelles depuis le fichier de configuration.
    Cela permet de toujours obtenir les dernières valeurs sans redémarrer le bot.
    """
    import app
    import json
    import os

    # Utiliser un chemin absolu pour le fichier de configuration
    config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_config.json')

    # Essayer d'abord de lire depuis le fichier de configuration
    try:
        if os.path.exists(config_file_path):
            with open(config_file_path, 'r') as f:
                config_data = json.load(f)

            # Log la configuration trouvée pour débogage
            logger.info(f"Found config in file: model={config_data['CURRENT_MODEL']}, timestamp={config_data.get('timestamp', 0)}")

            # Retourner les configurations depuis le fichier sans vérifier l'âge
            return {
                'CURRENT_MODEL': config_data['CURRENT_MODEL'],
                'get_ai_client': app.get_ai_client,
                'get_model_name': app.get_model_name,
                'get_system_instructions': app.get_system_instructions,
                'call_gemini_api': app.call_gemini_api
            }
    except Exception as e:
        logger.error(f"Error reading config file ({config_file_path}): {str(e)}")

    # Fallback aux configurations du module app
    app_config = app.get_app_config()
    current_model = app_config.get('CURRENT_MODEL', 'deepseek')
    logger.info(f"Using config from app module: {current_model}")
    return {
        'CURRENT_MODEL': current_model,
        'get_ai_client': app.get_ai_client,
        'get_model_name': app.get_model_name,
        'get_system_instructions': app.get_system_instructions,
        'call_gemini_api': app.call_gemini_api
    }

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
def db_retry_session(max_retries=3, retry_delay=0.5):
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

async def get_or_create_telegram_user(user_id: int, first_name: str = None, last_name: str = None):
    """Get or create a TelegramUser record with name information.

    Returns:
        tuple: (TelegramUser, is_new_user) - l'objet utilisateur et un booléen indiquant s'il a été créé
    """
    try:
        with db_retry_session() as session:
            logger.info(f"Attempting to get or create TelegramUser for ID: {user_id}")
            user = TelegramUser.query.get(user_id)
            is_new_user = False

            if not user:
                logger.info(f"Creating new TelegramUser for ID: {user_id}")
                user = TelegramUser(
                    telegram_id=user_id,
                    first_name=first_name or "---",
                    last_name=last_name or "---"
                )
                session.add(user)
                session.commit()
                logger.info(f"Successfully created TelegramUser: {user.telegram_id} ({first_name} {last_name})")
                is_new_user = True
            else:
                # Mettre à jour les noms s'ils ont changé
                updated = False
                if first_name and user.first_name != first_name:
                    user.first_name = first_name
                    updated = True
                if last_name and user.last_name != last_name:
                    user.last_name = last_name
                    updated = True
                if updated:
                    session.commit()
                    logger.info(f"Updated user {user_id} with new name: {first_name} {last_name}")
                logger.info(f"Found existing TelegramUser: {user.telegram_id}")

            # Émettre un événement Socket.IO pour notifier le tableau de bord si nouveau utilisateur
            if is_new_user:
                from app import socketio
                user_data = {
                    'telegram_id': user.telegram_id,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'created_at': user.created_at.strftime('%d/%m/%Y'),
                    'platform': 'telegram'
                }
                socketio.emit('new_telegram_user', user_data)
                logger.info(f"Emitted new_telegram_user event for user {user_id}")

            return user, is_new_user
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

            # Émettre un événement Socket.IO pour notifier le tableau de bord
            from app import socketio

            # Obtenir les informations sur l'utilisateur pour la notification
            user = TelegramUser.query.get(user_id)
            user_name = f"{user.first_name} {user.last_name}" if user else f"Telegram User {user_id}"

            conversation_data = {
                'id': conversation.id,
                'title': conversation.title,
                'thread_id': thread_id,
                'telegram_user_id': user_id,
                'user_name': user_name,
                'created_at': conversation.created_at.strftime('%d/%m/%Y %H:%M'),
                'platform': 'telegram'
            }
            socketio.emit('new_telegram_conversation', conversation_data)
            logger.info(f"Emitted new_telegram_conversation event for conversation {conversation.id}")

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
        user, is_new_user = await get_or_create_telegram_user(user_id, first_name, last_name)

        # Vérifier si l'utilisateur a déjà une conversation active
        with db_retry_session() as session:
            existing_conversation = TelegramConversation.query.filter_by(
                telegram_user_id=user_id
            ).order_by(TelegramConversation.updated_at.desc()).first()

            if not existing_conversation:
                # Create a new thread for the user
                thread = openai_client.beta.threads.create()
                user_threads[user_id] = thread.id
                logger.info(f"Created new thread {thread.id} for user {user_id}")

                # Create a new conversation in our database
                await create_telegram_conversation(user_id, thread.id)
            else:
                # Use existing conversation
                user_threads[user_id] = existing_conversation.thread_id
                logger.info(f"Using existing thread {existing_conversation.thread_id} for user {user_id}")

        # Envoyer le premier message avec l'emoji
        await update.message.reply_text(
            '🤓'
        )

        # Envoyer le second message avec l'ID Telegram si c'est un nouvel utilisateur
        if is_new_user:
            await asyncio.sleep(1)  # Attendre un peu entre les messages
            await update.message.reply_text(
                f"⚠️ *IMPORTANT* ⚠️\n\n"
                f"🔑 Votre ID Telegram est: *{user_id}*\n\n"
                f"📝 Notez cet identifiant précieusement! Il vous permettra de vous connecter à notre plateforme web et d'accéder à davantage de fonctionnalités.\n\n"
                f"🔐 Ne partagez jamais cet identifiant avec d'autres personnes.",
                parse_mode=constants.ParseMode.MARKDOWN
            )
            logger.info(f"Sent Telegram ID information to new user {user_id}")
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
        user, _ = await get_or_create_telegram_user(user_id, first_name, last_name)
        logger.info(f"User {user_id} retrieved/created successfully")

        with db_retry_session() as session:
            # Vérifier d'abord si l'utilisateur a déjà une conversation active dans la base de données
            existing_conversation = TelegramConversation.query.filter_by(
                telegram_user_id=user_id
            ).order_by(TelegramConversation.updated_at.desc()).first()

            # Get the current model configuration dynamically
            config = get_app_config()
            CURRENT_MODEL = config['CURRENT_MODEL']

            if existing_conversation:
                # Utiliser la conversation existante
                thread_id = existing_conversation.thread_id
                conversation = existing_conversation
                logger.info(f"Using existing conversation/thread {thread_id} for user {user_id}")

                # Mettre à jour user_threads pour référence en mémoire
                user_threads[user_id] = thread_id
            else:
                # Aucune conversation existante trouvée, créer une nouvelle
                if CURRENT_MODEL == 'openai':
                    thread = openai_client.beta.threads.create()
                    thread_id = thread.id
                else:
                    # Pour les autres modèles, créer un ID de thread unique
                    thread_id = f"thread_{user_id}_{int(time.time())}"

                user_threads[user_id] = thread_id
                logger.info(f"Created new thread {thread_id} for user {user_id}")
                # Créer une nouvelle conversation dans la base de données
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

        # Get the current model configuration dynamically
        config = get_app_config()
        CURRENT_MODEL = config['CURRENT_MODEL']
        get_ai_client = config['get_ai_client']
        get_model_name = config['get_model_name']
        get_system_instructions = config['get_system_instructions']
        call_gemini_api = config['call_gemini_api']

        logger.info(f"Using AI model: {CURRENT_MODEL} with instructions: {get_system_instructions()}")

        # Different handling based on selected model
        assistant_message = None

        if CURRENT_MODEL == 'openai':
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
                await asyncio.sleep(1)

            # Get the assistant's response
            messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
            assistant_message = messages.data[0].content[0].text.value
        else:
            # For other models (Gemini, Deepseek, Qwen), use direct API calls
            logger.info(f"Using alternative model: {CURRENT_MODEL} with model name: {get_model_name()}")

            # Get previous messages for context (limit to last 10)
            previous_messages = []
            with db_retry_session() as sess:
                messages_query = TelegramMessage.query.filter_by(conversation_id=conversation.id).order_by(TelegramMessage.created_at.desc()).limit(5).all()
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
            if CURRENT_MODEL == 'gemini':
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
                    logger.error(f"Error calling AI API ({CURRENT_MODEL}): {str(e)}")
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
        user, _ = await get_or_create_telegram_user(user_id, first_name, last_name)
        logger.info(f"User {user_id} retrieved/created successfully")

        # Ensure user_threads dict is initialized for this user
        if user_id not in user_threads:
            user_threads[user_id] = None

        with db_retry_session() as session:
            logger.info(f"Receiving photo from user {user_id}")

            if not update.message or not update.message.photo:
                logger.error("No photo found in the message")
                return

            # Get the current model configuration dynamically for thread creation
            config = get_app_config()
            CURRENT_MODEL = config['CURRENT_MODEL']

            # Vérifier d'abord si l'utilisateur a déjà une conversation active dans la base de données
            existing_conversation = TelegramConversation.query.filter_by(
                telegram_user_id=user_id
            ).order_by(TelegramConversation.updated_at.desc()).first()

            if existing_conversation:
                # Utiliser la conversation existante
                thread_id = existing_conversation.thread_id
                conversation = existing_conversation
                logger.info(f"Using existing conversation/thread {thread_id} for user {user_id}")

                # Mettre à jour user_threads pour référence en mémoire
                user_threads[user_id] = thread_id
            else:
                # Aucune conversation existante trouvée, créer une nouvelle
                if CURRENT_MODEL == 'openai':
                    thread = openai_client.beta.threads.create()
                    thread_id = thread.id
                else:
                    # Pour les autres modèles, créer un ID de thread unique
                    thread_id = f"thread_{user_id}_{int(time.time())}"

                user_threads[user_id] = thread_id
                logger.info(f"Created new thread {thread_id} for user {user_id}")
                # Créer une nouvelle conversation dans la base de données
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

            # Get the current model configuration dynamically
            config = get_app_config()
            CURRENT_MODEL = config['CURRENT_MODEL']
            get_ai_client = config['get_ai_client']
            get_model_name = config['get_model_name']
            get_system_instructions = config['get_system_instructions']
            call_gemini_api = config['call_gemini_api']

            logger.info(f"Using AI model for image processing: {CURRENT_MODEL}")

            # Different handling based on selected model
            assistant_message = None

            if CURRENT_MODEL == 'openai':
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
                    await asyncio.sleep(1)

                # Get the assistant's response
                messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
                assistant_message = messages.data[0].content[0].text.value
            else:
                # For other models (Gemini, Deepseek, Qwen), use direct API calls
                logger.info(f"Using alternative model for image: {CURRENT_MODEL} with model name: {get_model_name()}")

                # Get previous messages for context (limit to last 10)
                previous_messages = []
                with db_retry_session() as sess:
                    messages_query = TelegramMessage.query.filter_by(conversation_id=conversation.id).order_by(TelegramMessage.created_at.desc()).limit(5).all()
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
                if CURRENT_MODEL == 'gemini':
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
                        logger.error(f"Error calling AI API ({CURRENT_MODEL}) for image processing: {str(e)}")
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
    """Run the Telegram bot."""
    try:
        # Vérification explicite du token Telegram
        if not os.environ.get('TELEGRAM_BOT_TOKEN'):
            logger.error("TELEGRAM_BOT_TOKEN is not set. Telegram bot cannot start.")
            return

        # Only run if explicitly enabled
        if not os.environ.get('RUN_TELEGRAM_BOT'):
            logger.info("Telegram bot is disabled. Set RUN_TELEGRAM_BOT=true to enable.")
            return

        # Logs détaillés pour le déploiement
        logger.info("==== TELEGRAM BOT INITIALIZATION STARTED ====")
        logger.info(f"Environment: {os.environ.get('FLASK_ENV', 'not set')}")
        logger.info(f"Working directory: {os.getcwd()}")

        # Log current configuration (without using imported values)
        config = get_app_config()
        logger.info(f"Telegram bot starting with model: {config['CURRENT_MODEL']}")
        logger.info(f"System instructions: {config['get_system_instructions']()}")

        # Add a small delay to ensure Flask app is fully initialized
        logger.info("Waiting for 3 seconds to ensure application is fully initialized...")
        import time
        time.sleep(3)

        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        application = setup_telegram_bot()
        logger.info("Starting Telegram bot polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Error running Telegram bot: {str(e)}", exc_info=True)
        # Log l'erreur complète avec la trace d'appel pour mieux diagnostiquer
        import traceback
        logger.error(f"Full error traceback: {traceback.format_exc()}")
        raise

if __name__ == '__main__':
    run_telegram_bot()