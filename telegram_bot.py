import eventlet
eventlet.monkey_patch()

import os
import logging
import asyncio
import time
import openai
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
from flask import Blueprint
from flask import jsonify, request, session
from models import TelegramConversation, TelegramMessage

# Import models after eventlet patch
from models import TelegramUser, TelegramConversation, TelegramMessage
from database import db

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
    from app import get_db_context
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

def prepare_messages_for_model(messages_query, current_message=None, current_content=None, current_model=None):
    """
    Prépare les messages pour l'API en évitant les messages consécutifs du même rôle
    pour les modèles qui ne les supportent pas (comme deepseek-reasoner)

    Args:
        messages_query: Liste de TelegramMessage triés par date (plus ancien au plus récent)
        current_message: Message actuel à exclure (optionnel)
        current_content: Contenu du message actuel à exclure (optionnel)
        current_model: Modèle AI actuel (optionnel)

    Returns:
        Liste des messages formatés pour l'API
    """
    previous_messages = []
    processed_ids = set()
    last_role = None
    first_message_role = None  # Pour suivre le rôle du premier message

    for msg in messages_query:
        # Exclure le message actuel s'il est déjà dans la base
        if (current_message and msg.role == 'user' and 
            msg.content == current_message and msg.id not in processed_ids):
            continue

        # Exclure le message avec contenu spécifique (pour handle_photo)
        if current_content and msg.role == 'user' and msg.content == current_content:
            continue

        role = msg.role if msg.role == 'user' else 'assistant'

        # Si c'est le premier message, enregistrer son rôle
        if first_message_role is None:
            first_message_role = role

        # Vérifier si ce message a le même rôle que le précédent
        if role == last_role and current_model == 'deepseek-reasoner':
            # Fusionner avec le message précédent si même rôle
            logger.debug(f"Fusion de deux messages consécutifs avec rôle '{role}'")
            previous_messages[-1]["content"] += "\n\n" + msg.content
        else:
            # Sinon, ajouter normalement
            previous_messages.append({
                "role": role,
                "content": msg.content
            })
            last_role = role

        processed_ids.add(msg.id)

    # S'assurer que le premier message est toujours un message utilisateur pour deepseek-reasoner
    if current_model == 'deepseek-reasoner' and previous_messages and previous_messages[0]["role"] == "assistant":
        logger.debug("Le premier message est de type 'assistant', ajout d'un message utilisateur fictif en première position")
        previous_messages.insert(0, {
            "role": "user",
            "content": "Bonjour"  # Message utilisateur fictif minimaliste
        })

    return previous_messages

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
                with db_retry_session() as sess:
                    # Utilise conversation_id_value dans le filtre
                    messages_query = TelegramMessage.query.filter(
                         TelegramMessage.conversation_id == conversation_id_value # <<< Utilise ID
                    ).order_by(TelegramMessage.created_at.desc()).limit(CONTEXT_MESSAGE_LIMIT).all()

                    # Utilise la fonction utilitaire pour préparer les messages
                    previous_messages = prepare_messages_for_model(
                        reversed(messages_query),
                        current_message=message_text,
                        current_model=CURRENT_MODEL
                    )
                
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
                    logger.debug(f"Messages sent to AI ({CURRENT_MODEL}): {previous_messages}")
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

# Crée un Blueprint pour les routes admin spécifiques à Telegram
telegram_admin_bp = Blueprint('telegram_admin', __name__, url_prefix='/admin/telegram')

# Si vous utilisez un Blueprint nommé 'telegram_bp': @telegram_bp.route(...)
@telegram_admin_bp.route('/conversations/<int:conversation_id>/send', methods=['POST'])
async def send_admin_telegram_message(conversation_id):
    """Envoie un message admin à une conversation Telegram spécifique."""
    try:
        # Vérification Admin
        if not session.get('is_admin'):
            logger.warning("Tentative d'accès non autorisé à l'envoi de message admin Telegram.")
            return jsonify({'error': 'Unauthorized access'}), 403

        # Récupération du contenu
        data = request.json
        message_content = data.get('message')
        if not message_content or message_content.strip() == '':
            logger.warning("Tentative d'envoi de message admin Telegram vide.")
            return jsonify({'error': 'Message content is required'}), 400

        # Trouver la conversation Telegram
        tg_conv = TelegramConversation.query.get(conversation_id)
        if not tg_conv:
            logger.warning(f"Conversation Telegram ID {conversation_id} non trouvée.")
            return jsonify({'error': 'Telegram Conversation not found'}), 404

        # Récupérer l'utilisateur Telegram associé via l'ID stocké dans la conversation
        # (Assure-toi que ta classe TelegramConversation a bien un attribut telegram_user_id)
        if not tg_conv.telegram_user_id:
             logger.error(f"L'attribut telegram_user_id est manquant pour la conversation Telegram ID {conversation_id}.")
             return jsonify({'error': 'Missing user association in conversation'}), 500

        tg_user = TelegramUser.query.get(tg_conv.telegram_user_id)
        if not tg_user:
             logger.warning(f"Utilisateur Telegram avec ID {tg_conv.telegram_user_id} (associé à conv {conversation_id}) non trouvé.")
             return jsonify({'error': 'Associated Telegram User not found'}), 404

        # Récupérer le chat_id depuis l'objet TelegramUser
        # (Assure-toi que ta classe TelegramUser a bien un attribut chat_id)
        user_chat_id = tg_user.telegram_id
        if not user_chat_id:
             logger.error(f"Chat ID manquant pour l'utilisateur Telegram ID {tg_conv.telegram_user_id} (associé à conv {conversation_id}).")
             return jsonify({'error': 'Missing Chat ID for the associated user'}), 500


        newly_saved_message_db_id = None
        success = False # Sera mis à True si la tâche d'envoi est lancée
        error_msg = None

        # 1. Sauvegarder le message dans la base de données Telegram
        try:
            new_message = TelegramMessage(
                conversation_id=tg_conv.id,
                role='admin',
                content=message_content,
                created_at=datetime.utcnow()
            )
            db.session.add(new_message)
            db.session.commit()
            newly_saved_message_db_id = new_message.id
            logger.info(f"Message admin sauvegardé pour conversation Telegram ID: {conversation_id}, Message ID: {newly_saved_message_db_id}")
        except Exception as db_error:
            db.session.rollback()
            logger.exception(f"Erreur DB sauvegarde message admin Telegram: {db_error}")
            return jsonify({'error': f'Database error during save: {str(db_error)}'}), 500

        # 2. Lancer l'envoi via l'API Telegram (de manière asynchrone non bloquante)
        try:
            logger.info(f"Préparation de l'envoi async Telegram vers chat_id: {user_chat_id}")
            # Utiliser await directement car la fonction de route est maintenant async
            await application.bot.send_message(chat_id=user_chat_id, text=message_content)
            logger.info(f"Message admin envoyé avec succès à chat_id {user_chat_id}")
            success = True # L'envoi a réussi si aucune exception n'est levée

        except Exception as tg_send_error:
            logger.error(f"Erreur lors de l'envoi direct Telegram à {user_chat_id}: {tg_send_error}", exc_info=True)
            error_msg = f"Failed to send Telegram message: {str(tg_send_error)}"
            success = False
            # Note : Le message est sauvegardé en DB mais n'a pas pu être envoyé.

        # 3. Réponse au Frontend
        if success:
            message_data = {
                'id': newly_saved_message_db_id, # ID du message sauvegardé
                'role': 'admin',
                'content': message_content,
                'created_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S') # Heure de sauvegarde/envoi
            }
            return jsonify({'success': True, 'message': 'Telegram admin message processed', 'message_data': message_data})
        else:
            # Si l'erreur vient du spawn ou d'une logique avant l'API
            return jsonify({'error': error_msg or 'Failed to process Telegram admin message'}), 500

    except Exception as e:
        logger.exception(f"Erreur générale dans send_admin_telegram_message pour conversation {conversation_id}: {e}")
        # Assurer un rollback si une erreur DB s'est produite avant le commit final
        db.session.rollback()
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

# --- NOUVELLE ROUTE POUR DÉCLENCHER L'IA COMME UTILISATEUR TELEGRAM ---
@telegram_admin_bp.route('/trigger_ai_as_user/<int:conversation_id>', methods=['POST'])
async def trigger_ai_as_user_telegram(conversation_id):
    """
    Reçoit un message de l'admin, le traite comme un message utilisateur Telegram
    pour déclencher l'IA, envoie la réponse de l'IA à l'utilisateur,
    mais NE sauvegarde PAS le message initial de l'admin.
    Nécessite d'être async car on await l'envoi Telegram.
    """
    # 1. Vérification Admin
    if not session.get('is_admin'):
        logger.warning("Tentative non autorisée de déclencher l'IA comme utilisateur Telegram.")
        return jsonify({'error': 'Unauthorized access'}), 403

    try:
        # 2. Récupération du contenu du message (envoyé par l'admin)
        data = request.json
        admin_message_content = data.get('message')
        if not admin_message_content or admin_message_content.strip() == '':
            logger.warning("Tentative de déclencher l'IA Telegram avec un message vide.")
            return jsonify({'error': 'Message content is required'}), 400

        logger.info(f"Déclenchement IA comme utilisateur pour conversation Telegram ID {conversation_id} avec contenu: '{admin_message_content[:50]}...'")

        # 3. Trouver la conversation Telegram et les infos nécessaires
        tg_conv = None
        user_chat_id = None
        telegram_user_id = None
        with db_retry_session() as sess: # <<< Bloc corrigé
             tg_conv = sess.get(TelegramConversation, conversation_id)
             if not tg_conv:
                  logger.error(f"Conversation Telegram ID {conversation_id} non trouvée lors du déclenchement IA.")
                  # Important de retourner *dans* le bloc with si on ne trouve pas la conv
                  return jsonify({'error': 'Telegram conversation not found'}), 404

             # Récupérer l'ID utilisateur associé
             if not tg_conv.telegram_user_id:
                 logger.error(f"L'attribut telegram_user_id est manquant pour la conversation Telegram ID {conversation_id}.")
                 return jsonify({'error': 'Missing user association in conversation'}), 500
             telegram_user_id = tg_conv.telegram_user_id # Stocker l'ID utilisateur

             # Récupérer l'utilisateur Telegram
             tg_user = sess.get(TelegramUser, telegram_user_id) # Utiliser sess.get() est plus direct
             if not tg_user:
                 logger.warning(f"Utilisateur Telegram avec ID {telegram_user_id} (associé à conv {conversation_id}) non trouvé.")
                 return jsonify({'error': 'Associated Telegram User not found'}), 404

             # Récupérer le chat_id depuis l'utilisateur (en utilisant telegram_id)
             user_chat_id = tg_user.telegram_id # <<< CORRECTION ICI
             if not user_chat_id:
                 logger.error(f"Telegram ID (utilisé comme Chat ID) manquant pour l'utilisateur Telegram ID {telegram_user_id}.")
                 return jsonify({'error': 'Missing Telegram ID (Chat ID) for the associated user'}), 500


        if not user_chat_id:
             logger.error(f"Chat ID manquant pour la conversation Telegram {conversation_id}.")
             return jsonify({'error': 'Missing Chat ID for this conversation'}), 500

        # --- NE PAS SAUVEGARDER admin_message_content ---

        # 4. Générer la réponse de l'IA
        ai_response_text = None
        try:
            # Récupérer la configuration AI
            config = get_app_config()
            CURRENT_MODEL = config['CURRENT_MODEL']
            get_ai_client = config['get_ai_client']
            get_model_name = config['get_model_name']
            get_system_instructions = config['get_system_instructions']

            logger.debug(f"Appel IA ({CURRENT_MODEL}) pour conv Telegram {conversation_id} (déclenché par admin)")

            # Récupérer l'historique spécifique à Telegram
            with db_retry_session() as hist_sess:
                messages_query = hist_sess.query(TelegramMessage).filter(
                    TelegramMessage.conversation_id == conversation_id
                ).order_by(TelegramMessage.created_at.desc()).limit(CONTEXT_MESSAGE_LIMIT).all()

                # Préparer l'historique pour l'API (réutiliser la fonction existante)
                history_for_api = prepare_messages_for_model(
                    reversed(messages_query),
                    current_model=CURRENT_MODEL
                    # Ne pas passer current_message/content car on ne sauvegarde pas l'input admin
                )

            # Ajouter le message "utilisateur" (admin) à l'historique API
            history_for_api.append({"role": "user", "content": admin_message_content})

            # Ajouter les instructions système si nécessaire (pour modèles non-assistant)
            if CURRENT_MODEL != 'openai':
                 system_instructions = get_system_instructions()
                 if system_instructions:
                     history_for_api.insert(0, {"role": "system", "content": system_instructions})

            # Appeler l'API IA appropriée
            ai_client = get_ai_client()
            model_name = get_model_name() # Peut être None pour OpenAI Assistant

            if CURRENT_MODEL == 'openai':
                 # Logique spécifique OpenAI Assistant API v2 (si applicable ici)
                 # Assurez-vous que vous avez le bon thread_id associé à conversation_id
                 openai_thread_id = tg_conv.thread_id if tg_conv else None
                 if not openai_thread_id:
                      raise ValueError("Missing OpenAI thread_id for this Telegram conversation.")

                 openai_client.beta.threads.messages.create(
                    thread_id=openai_thread_id, role="user", content=admin_message_content
                 )
                 run = openai_client.beta.threads.runs.create(
                    thread_id=openai_thread_id, assistant_id=ASSISTANT_ID
                 )
                 # Boucle d'attente (peut nécessiter adaptation pour async/eventlet)
                 while True:
                      run_status = openai_client.beta.threads.runs.retrieve(thread_id=openai_thread_id, run_id=run.id)
                      if run_status.status == 'completed': break
                      if run_status.status in ['failed', 'cancelled', 'expired']: raise Exception(f"OpenAI Run {run.id} failed: {run_status.status}")
                      await asyncio.sleep(1) # Utiliser asyncio.sleep dans une route async

                 messages_openai = openai_client.beta.threads.messages.list(thread_id=openai_thread_id, order='desc', limit=1)
                 if messages_openai.data and messages_openai.data[0].role == 'assistant':
                     ai_response_text = messages_openai.data[0].content[0].text.value
                 else:
                      raise Exception("Failed to retrieve assistant message from OpenAI thread.")

            else: # Modèles Chat Completion
                 if not model_name: raise ValueError("Model name is required for Chat Completions.")
                 response = ai_client.chat.completions.create(
                     model=model_name,
                     messages=history_for_api
                 )
                 ai_response_text = response.choices[0].message.content

            logger.info(f"Réponse IA générée pour déclenchement admin (conv Telegram {conversation_id}): '{ai_response_text[:50]}...'")

        except Exception as ai_error:
            logger.error(f"Erreur lors de la génération IA (déclenchement admin) pour conv Telegram {conversation_id}: {ai_error}", exc_info=True)
            return jsonify({'error': f'AI response generation failed: {str(ai_error)}'}), 500

        # 5. Envoyer la réponse de l'IA à l'utilisateur réel via Telegram
        try:
            logger.info(f"Envoi async de la réponse IA déclenchée par admin à chat_id {user_chat_id}")
            # Utilisation directe de await car la route est async
            await application.bot.send_message(chat_id=user_chat_id, text=ai_response_text)
            logger.info(f"Réponse IA envoyée avec succès à chat_id {user_chat_id}")
        except Exception as send_error:
            logger.error(f"Erreur lors de l'envoi Telegram de la réponse IA (déclenchée par admin) à {user_chat_id}: {send_error}", exc_info=True)
            # Renvoyer une erreur à l'admin, car l'utilisateur n'a rien reçu
            return jsonify({'error': f'Failed to send AI response via Telegram API: {str(send_error)}'}), 500


        # 6. Sauvegarder la réponse de l'IA dans la DB Telegram
        try:
            await add_telegram_message(conversation_id, 'assistant', ai_response_text)
            logger.info(f"Réponse IA (déclenchée par admin) sauvegardée pour conv Telegram {conversation_id}")
        except Exception as db_error:
            logger.error(f"Erreur sauvegarde réponse IA (déclenchée par admin) pour conv Telegram {conversation_id}: {db_error}")
            pass # Ne pas planter ici

        # 7. Émettre l'événement Socket.IO pour l'UI Admin
        try:
            from app import socketio # Assure-toi que socketio est accessible
            message_data_for_socket = {
                'role': 'assistant',
                'content': ai_response_text,
                'image_url': None,
                'created_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'conversation_identifier': conversation_id, # ID numérique pour Telegram
                'platform': 'telegram'
            }
            socketio.emit('new_admin_message', message_data_for_socket)
            logger.info(f"Événement SocketIO 'new_admin_message' émis pour conv Telegram {conversation_id}")
        except Exception as socket_error:
            logger.error(f"Échec de l'émission SocketIO pour le message admin/IA Telegram: {socket_error}")


        # 8. Renvoyer un succès à l'interface admin
        return jsonify({
            'success': True,
            'message': 'AI triggered successfully as Telegram user, response sent and saved.',
            'ai_response_preview': ai_response_text[:100] + ('...' if len(ai_response_text) > 100 else '')
        })

    except Exception as e:
        logger.exception(f"Erreur générale dans trigger_ai_as_user_telegram pour conversation {conversation_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

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
                with db_retry_session() as sess:
                    # La logique de récupération de l'historique reste la même
                    messages_query = TelegramMessage.query.filter_by(conversation_id=conversation.id).order_by(TelegramMessage.created_at.desc()).limit(CONTEXT_MESSAGE_LIMIT).all()

                    # Utilise la fonction utilitaire pour préparer les messages
                    previous_messages = prepare_messages_for_model(
                        reversed(messages_query),
                        current_content=user_store_content,
                        current_model=CURRENT_MODEL
                    )

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

try:
    application = setup_telegram_bot()
    logger.info("Objet 'application' Telegram initialisé pour import.")
except Exception as e:
    logger.error(f"Échec de l'initialisation de l'objet 'application' Telegram au chargement du module: {e}", exc_info=True)
    # Gérer cette erreur critique - peut-être arrêter l'app?
    # Pour l'instant, on logge et on continue, mais la route webhook plantera.
    application = None