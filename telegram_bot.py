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
                'get_system_instructions': app.get_system_instructions
            }
    except Exception as e:
        logger.error(f"Error reading config file ({config_file_path}): {str(e)}")

    # Fallback aux configurations du module app
    logger.info(f"Using config from app module: {app.CURRENT_MODEL}")
    return {
        'CURRENT_MODEL': app.CURRENT_MODEL,
        'get_ai_client': app.get_ai_client,
        'get_model_name': app.get_model_name,
        'get_system_instructions': app.get_system_instructions,
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
    CONTEXT_MESSAGE_LIMIT = int(os.environ.get('CONTEXT_MESSAGE_LIMIT', '50'))
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
    if not update.message or (not update.message.text and not update.message.photo): # Accepter aussi les messages sans texte si photo
        logger.warning("Received message without text or photo. Ignoring.")
        return

    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name or ""
    message_text = update.message.text or "" # Utiliser "" si pas de texte (cas photo seule)
    logger.info(f"Processing message (text: {bool(message_text)}) from user {user_id} ({first_name} {last_name})")

    # --- Début de la gestion photo (si présente) ---
    if update.message.photo:
        logger.info("Message contains photo, delegating to handle_photo.")
        await handle_photo(update, context)
        return
    # --- Fin de la gestion photo ---

    # Si on arrive ici, c'est un message TEXTE uniquement.
    if not message_text.strip():
         logger.warning("Received empty text message after checking for photo. Ignoring.")
         return

    # conversation = None # On n'a plus besoin de l'objet conversation en dehors du bloc session initial
    thread_id = None
    assistant_message = None
    conversation_id_value = None # <<< NOUVEAU: Variable pour stocker l'ID de la conversation
    conversation_title_to_update = None # Variable temporaire pour savoir si le titre doit être MAJ

    try:
        # Get or create user first
        user, _ = await get_or_create_telegram_user(user_id, first_name, last_name)
        logger.info(f"User {user_id} retrieved/created successfully")

        # Update last_active timestamp
        if user:
            user.last_active = datetime.utcnow()
            try:
                with db_retry_session() as session_for_update:
                    merged_user = session_for_update.merge(user)
                    merged_user.last_active = datetime.utcnow()
                    session_for_update.commit()
                    logger.debug(f"TelegramUser {user.telegram_id} last_active updated.")
            except Exception as e:
                logger.error(f"Erreur MAJ last_active pour telegram_user {user.telegram_id}: {e}", exc_info=True)

        # Find or create conversation and thread_id, AND get conversation_id_value
        with db_retry_session() as session:
            existing_conversation = TelegramConversation.query.filter_by(
                telegram_user_id=user_id
            ).order_by(TelegramConversation.updated_at.desc()).first()

            config = get_app_config()
            CURRENT_MODEL = config['CURRENT_MODEL']

            if existing_conversation:
                thread_id = existing_conversation.thread_id
                conversation_id_value = existing_conversation.id # <<< Récupère l'ID ici
                logger.info(f"Using existing conversation {conversation_id_value} / thread {thread_id} for user {user_id}")
                user_threads[user_id] = thread_id
                existing_conversation.updated_at = datetime.utcnow()
                session.commit() # Commit update_at ici
            else:
                # No existing conversation, create a new one
                if CURRENT_MODEL == 'openai':
                    thread = openai_client.beta.threads.create()
                    thread_id = thread.id
                else:
                    thread_id = f"thread_{user_id}_{int(time.time())}"

                user_threads[user_id] = thread_id
                logger.info(f"Created new thread {thread_id} for user {user_id}")
                # create_telegram_conversation retourne l'objet conversation
                new_conversation = await create_telegram_conversation(user_id, thread_id)
                conversation_id_value = new_conversation.id # <<< Récupère l'ID de la nouvelle conv
                conversation_title_to_update = new_conversation.title # Marque le titre pour MAJ potentielle

        # --- Opérations après la fermeture de la première session ---

        # Vérification de sécurité : on doit avoir un ID de conversation
        if conversation_id_value is None:
             logger.error("Critical error: conversation_id_value is None after fetching/creating conversation.")
             raise Exception("Failed to obtain a valid conversation ID.")

        # Ajouter le message utilisateur en utilisant l'ID sauvegardé
        await add_telegram_message(conversation_id_value, 'user', message_text) # <<< Utilise conversation_id_value

        # Mettre à jour le titre si c'était une nouvelle conversation
        # On doit re-requêter la conversation dans une nouvelle session pour la modifier
        if conversation_title_to_update == "Nouvelle conversation":
             first_msg_content = message_text.strip()
             if first_msg_content:
                 new_title = first_msg_content[:30] + "..." if len(first_msg_content) > 30 else first_msg_content
                 try:
                     with db_retry_session() as update_session:
                         # Re-fetch the conversation using the ID
                         conv_to_update = update_session.get(TelegramConversation, conversation_id_value)
                         if conv_to_update:
                             conv_to_update.title = new_title
                             update_session.commit()
                             logger.info(f"Updated conversation {conversation_id_value} title to: '{new_title}'")
                             # Émettre l'événement SocketIO pour MAJ UI Admin
                             from app import socketio # Assure-toi que socketio est accessible
                             socketio.emit('telegram_conversation_updated', {
                                 'id': conversation_id_value,
                                 'title': new_title,
                                 'last_message': message_text[:50] + "..."
                             })
                         else:
                             logger.warning(f"Could not re-fetch conversation {conversation_id_value} to update title.")
                 except Exception as title_update_e:
                     logger.error(f"Error updating conversation title for {conversation_id_value}: {title_update_e}", exc_info=True)
                     # On ne bloque pas le reste du traitement pour une erreur de titre

        # Start typing indication
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=constants.ChatAction.TYPING
        )

        # --- AI Processing Logic ---
        config = get_app_config()
        CURRENT_MODEL = config['CURRENT_MODEL']
        get_ai_client = config['get_ai_client']
        get_model_name = config['get_model_name']
        get_system_instructions = config['get_system_instructions']

        logger.info(f"Using AI model: {CURRENT_MODEL}")

        if CURRENT_MODEL == 'openai':
            # --- OpenAI Assistants API Logic ---
            logger.info(f"Processing with OpenAI Assistant API (Thread: {thread_id})")
            # ... (La logique interne de l'API Assistant reste la même, elle utilise thread_id)
            # ... (Elle doit assigner la réponse ou une erreur à assistant_message)
            try:
                # Add user message to the OpenAI thread
                openai_client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=message_text
                )
                # Create and run the assistant
                run = openai_client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=ASSISTANT_ID
                )
                # Wait for run completion
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
                        logger.info(f"OpenAI Assistant run {run.id} completed.")
                        break
                    elif run_status.status in ['failed', 'cancelled', 'expired']:
                        error_msg = f"Assistant run {run.id} failed with status: {run_status.status}"
                        logger.error(error_msg)
                        raise OpenAIError(error_msg)
                    await asyncio.sleep(1)

                # Retrieve the latest message from the assistant
                messages = openai_client.beta.threads.messages.list(thread_id=thread_id, order='desc', limit=1)
                if messages.data and messages.data[0].role == 'assistant' and messages.data[0].content[0].type == 'text':
                    assistant_message = messages.data[0].content[0].text.value
                else:
                    logger.error(f"Could not retrieve valid assistant message from thread {thread_id}.")
                    assistant_message = "Sorry, I couldn't retrieve a valid response from the assistant."

            except OpenAIError as e:
                 logger.error(f"OpenAI API error during Assistant processing: {str(e)}", exc_info=True)
                 assistant_message = "I'm having trouble connecting to my AI brain (Assistant API). Please try again."
            except Exception as e:
                 logger.error(f"Unexpected error during OpenAI Assistant processing: {str(e)}", exc_info=True)
                 assistant_message = "An unexpected error occurred while communicating with the AI assistant."


        elif CURRENT_MODEL in ['deepseek', 'deepseek-reasoner', 'qwen', 'gemini']:
            # --- Chat Completions API Logic ---
            logger.info(f"Processing with Chat Completions API ({CURRENT_MODEL})")
            try:
                # Get previous messages for context using conversation_id_value
                previous_messages = []
                with db_retry_session() as sess:
                    # Utilise conversation_id_value dans le filtre
                    messages_query = TelegramMessage.query.filter(
                         TelegramMessage.conversation_id == conversation_id_value # <<< Utilise ID
                    ).order_by(TelegramMessage.created_at.desc()).limit(CONTEXT_MESSAGE_LIMIT).all()

                    processed_ids = set() # Pour éviter doublons si la query ramène le msg user actuel
                    for msg in reversed(messages_query):
                        # Exclure le message utilisateur actuel si la query le ramène (par sécurité)
                        if msg.role == 'user' and msg.content == message_text and msg.id not in processed_ids:
                             # On veut l'historique SANS le message actuel, qui sera ajouté après
                             continue
                        role = msg.role if msg.role == 'user' else 'assistant'
                        previous_messages.append({
                            "role": role,
                            "content": msg.content
                        })
                        processed_ids.add(msg.id)


                # Add system instruction
                system_instructions = get_system_instructions()
                if system_instructions:
                    previous_messages.insert(0, {
                        "role": "system",
                        "content": system_instructions
                    })

                # Add the current user message (celui en cours de traitement)
                previous_messages.append({
                    "role": "user",
                    "content": message_text
                })

                ai_client = get_ai_client()
                model = get_model_name()

                if not model:
                    logger.error(f"Could not determine model name for CURRENT_MODEL='{CURRENT_MODEL}'")
                    assistant_message = "Internal configuration error: Could not determine AI model name."
                else:
                    # Make the API call
                    response = ai_client.chat.completions.create(
                        model=model,
                        messages=previous_messages
                    )
                    assistant_message = response.choices[0].message.content

            # ... (Blocs except pour cette branche restent similaires, assignent à assistant_message) ...
            except OpenAIError as e:
                logger.error(f"Error calling Chat Completions API ({CURRENT_MODEL}): {str(e)}", exc_info=True)
                if isinstance(e, openai.BadRequestError) and 'provide a model parameter' in str(e):
                     assistant_message = "Internal configuration error: AI model parameter missing."
                else:
                     assistant_message = f"I'm having trouble connecting to my AI brain ({CURRENT_MODEL}). Please try again."
            except Exception as e:
                logger.error(f"Unexpected error during {CURRENT_MODEL} processing: {str(e)}", exc_info=True)
                assistant_message = f"An unexpected error occurred while communicating with the {CURRENT_MODEL} AI."


        else:
            # --- Handle Unknown Model ---
            logger.error(f"Unsupported CURRENT_MODEL configured: {CURRENT_MODEL}")
            assistant_message = "Sorry, the configured AI model is not supported."

    # --- Catch errors from user/conversation lookup or initial DB operations ---
    except Exception as e:
        logger.error(f"Error before AI processing (user/conversation handling): {str(e)}", exc_info=True)
        # Assign error message here as well
        assistant_message = "I apologize, but I encountered an error processing your request before contacting the AI. Please try again."

    # --- Final Sending and Storage ---
    if assistant_message is None:
        logger.error("Assistant message is None after all processing attempts. Assigning generic error.")
        assistant_message = "Sorry, an unknown error occurred while generating the response."

    # Store the final assistant's response (or error message)
    try:
        if conversation_id_value: # Vérifie qu'on a bien un ID
            await add_telegram_message(conversation_id_value, 'assistant', assistant_message) # <<< Utilise conversation_id_value
        else:
             logger.error("Cannot save assistant message because conversation_id_value is None.")
    except Exception as db_error:
        logger.error(f"Failed to save assistant message to DB for conversation {conversation_id_value}: {db_error}", exc_info=True)
        # On continue pour envoyer le message à l'utilisateur même si la sauvegarde échoue

    # Send the final response (or error message) to the user
    try:
        logger.info(f"Sending final response/error to user {user_id}: {assistant_message[:100]}...")
        await update.message.reply_text(assistant_message)
    except Exception as send_error:
        logger.error(f"Failed to send final message to user {user_id}: {send_error}", exc_info=True)

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
                 # For other models (Gemini, Deepseek, Qwen), use direct API calls compatible OpenAI
                logger.info(f"Using alternative model for image: {CURRENT_MODEL} with model name: {get_model_name()}")

                # Get previous messages for context (limit to last N)
                previous_messages = []
                with db_retry_session() as sess:
                    # La logique de récupération de l'historique reste la même
                    messages_query = TelegramMessage.query.filter_by(conversation_id=conversation.id).order_by(TelegramMessage.created_at.desc()).limit(CONTEXT_MESSAGE_LIMIT).all()
                    for msg in reversed(messages_query):
                        # Exclure le message courant qui vient d'être ajouté avec l'image/caption
                        if msg.role == 'user' and msg.content == user_store_content:
                             continue
                        # Convertir le rôle 'assistant' en 'assistant' pour l'API Chat Completion
                        role = msg.role if msg.role == 'user' else 'assistant'
                        previous_messages.append({
                            "role": role,
                            "content": msg.content
                        })

                # Ajouter le message courant (avec caption + extraction mathpix)
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

                # Logique unifiée pour Gemini, DeepSeek, Qwen
                ai_client = get_ai_client() # Obtient le client configuré
                model = get_model_name()    # Obtient le nom de modèle configuré

                try:
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