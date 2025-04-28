import eventlet
eventlet.monkey_patch()

import os
from dotenv import load_dotenv
# Load environment variables before any other imports
load_dotenv()

from flask import Flask, render_template, request, jsonify, url_for, session, redirect, flash
from flask_socketio import SocketIO, emit
from openai import OpenAI
from werkzeug.utils import secure_filename
import base64
from io import BytesIO
from datetime import date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import exc
from flask import request, jsonify
from sqlalchemy import func, desc, or_
from datetime import datetime, timedelta
import shutil
import time
import logging
from contextlib import contextmanager
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
import uuid
from mathpix_utils import process_image_with_mathpix  # Added import
import json
from typing_extensions import override
from openai import AssistantEventHandler
from flask_migrate import Migrate
from telegram import Update
from telegram_bot import application as telegram_app
from telegram_bot import telegram_admin_bp
from flask import request as flask_request
from flask import Response
import asyncio

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Configuration
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Configurations for image cleanup
MAX_UPLOAD_FOLDER_SIZE = 500 * 1024 * 1024  # 500 MB
IMAGE_MAX_AGE_HOURS = 24

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_recycle': 300,  # Recycle connections every 5 minutes
    'pool_pre_ping': True,  # Enable connection pool pre-ping
}

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['SESSION_PERMANENT'] = True

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database
from database import db

db.init_app(app)
migrate = Migrate(app, db)

# Importer les modèles après l'initialisation de db
from models import User, Conversation, Message, TelegramUser, TelegramConversation, TelegramMessage, Subscription, MessageFeedback

# Initialize SocketIO with eventlet
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Initialize OpenAI clients
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
deepseek_client = OpenAI(api_key=os.getenv('DEEPSEEK_API_KEY'),
                         base_url="https://api.deepseek.com")
qwen_client = OpenAI(
    api_key=os.getenv('DASHSCOPE_API_KEY'),
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
gemini_openai_client = OpenAI(
    api_key=os.getenv('GEMINI_API_KEY'),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/" # Endpoint compatible
)

# Clé API pour Gemini (utilisée soit pour l'API REST directe, soit pour l'endpoint compatible OpenAI)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Get the current AI model from environment or default to OpenAI
CURRENT_MODEL = os.environ.get('CURRENT_MODEL', 'openai')

# Assurer qu'un event loop existe pour le contexte async (important dans certains déploiements)
try:
    loop = asyncio.get_event_loop()
    logger.info(f"Event loop obtained: {loop}")
except RuntimeError:
    logger.info("No current event loop, creating a new one.")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

if telegram_app: # Vérifier si l'import a réussi
    logger.info("Initialisation de l'application Telegram (await application.initialize())...")
    try:
        # Exécuter l'initialisation async dans la boucle d'événements existante
        # C'est important de le faire une fois au démarrage
        loop.run_until_complete(telegram_app.initialize())
        logger.info("Application Telegram initialisée avec succès.")
    except Exception as init_error:
        logger.error(f"Échec de l'initialisation de l'application Telegram: {init_error}", exc_info=True)
        # Gérer l'erreur critique si nécessaire
else:
     logger.error("Impossible d'initialiser l'application Telegram car elle n'a pas été importée/créée.")

@app.route('/telegram_webhook', methods=['POST'])
async def telegram_webhook_handler(): # Mettre 'async def' car process_update est async
    logger.debug("Webhook Telegram reçu !")
    if flask_request.content_type == 'application/json':
        json_data = flask_request.get_json(force=True)
        logger.debug(f"Payload JSON: {json_data}")
        try:
            if telegram_app: # Vérifier que l'objet application a été initialisé
                 update = Update.de_json(json_data, telegram_app.bot)
                 logger.debug(f"Update deserialized: {update.update_id}")
                 # Laisser python-telegram-bot gérer le dispatching vers les bons handlers (handle_message, etc.)
                 await telegram_app.process_update(update)
                 logger.debug(f"Update {update.update_id} processed.")
            else:
                 logger.error("Objet application Telegram non initialisé, impossible de traiter le webhook.")
                 # Répondre OK à Telegram même en cas d'erreur interne pour éviter re-essais constants
                 return Response(status=500) # Ou 200, voir note ci-dessous

            # Répondre 200 OK à Telegram pour indiquer qu'on a bien reçu l'update
            return Response(status=200)

        except Exception as e:
            logger.error(f"Erreur lors du traitement du webhook Telegram: {e}", exc_info=True)
            # Répondre 200 OK à Telegram même en cas d'erreur pour éviter que Telegram ne réessaie sans fin
            return Response(status=200)
    else:
        logger.warning(f"Requête Webhook reçue avec Content-Type incorrect: {flask_request.content_type}")
        return Response(status=400) # Bad Request


def load_instructions_from_file(file_path, default_value):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    return default_value


DEEPSEEK_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('DEEPSEEK_INSTRUCTIONS_FILE', 'instructions/deepseek.txt'),
    'You are a helpful educational assistant')
DEEPSEEK_REASONER_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('DEEPSEEK_REASONER_INSTRUCTIONS_FILE',
                   'instructions/deepseek_reasoner.txt'),
    'You are a helpful educational assistant focused on reasoning')
QWEN_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('QWEN_INSTRUCTIONS_FILE', 'instructions/qwen.txt'),
    'You are a helpful educational assistant')
GEMINI_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('GEMINI_INSTRUCTIONS_FILE', 'instructions/gemini.txt'),
    'You are a helpful educational assistant')
CONTEXT_MESSAGE_LIMIT = int(os.environ.get('CONTEXT_MESSAGE_LIMIT', '50'))


def get_ai_client():
    """Returns the appropriate AI client based on the current model setting"""
    if CURRENT_MODEL in ['deepseek', 'deepseek-reasoner']:
        return deepseek_client
    elif CURRENT_MODEL == 'qwen':
        return qwen_client
    elif CURRENT_MODEL == 'gemini': # AJOUTÉ
        return gemini_openai_client # Retourne le nouveau client compatible OpenAI
    else:
        # Par défaut, on retourne le client pour OpenAI Assistants API v1 (si utilisé pour 'openai')
        return openai_client


def get_model_name():
    """Returns the appropriate model name based on the current model setting"""
    if CURRENT_MODEL == 'deepseek':
        return "deepseek-chat"
    elif CURRENT_MODEL == 'deepseek-reasoner':
        return "deepseek-reasoner"
    elif CURRENT_MODEL == 'qwen':
        return "qwen-max-latest"
    elif CURRENT_MODEL == 'gemini':
        return "gemini-2.5-flash-preview-04-17" # Ou un autre modèle compatible listé par l'API
    return None # Pour OpenAI Assistants v1 (qui utilise assistant_id)


def get_system_instructions():
    """Returns the appropriate system instructions based on the current model setting"""
    if CURRENT_MODEL == 'deepseek':
        return DEEPSEEK_INSTRUCTIONS
    elif CURRENT_MODEL == 'deepseek-reasoner':
        return DEEPSEEK_REASONER_INSTRUCTIONS
    elif CURRENT_MODEL == 'qwen':
        return QWEN_INSTRUCTIONS
    elif CURRENT_MODEL == 'gemini':
        return GEMINI_INSTRUCTIONS
    return None  # For OpenAI, instructions are set in the assistant


class OpenAIAssistantEventHandler(AssistantEventHandler):

    def __init__(self, socket, message_id):
        super().__init__()
        self.socket = socket
        self.message_id = message_id
        self.full_response = ""
        self._AssistantEventHandler__stream = None
        self.time_module = time
        self.run_id = None

    @override
    def on_event(self, event):
      if event.event == 'thread.run.created':
        self.run_id = event.data.id
        logger.info(f"EventHandler: Run créé avec ID: {self.run_id}")

    @override
    def on_text_created(self, text) -> None:
        # Initialisation du texte - pas besoin d'envoyer de contenu ici
        pass

    @override
    def on_text_delta(self, delta, snapshot):
        # Ajouter le delta au texte complet
        self.full_response += delta.value

        # Émettre le nouveau contenu à l'utilisateur
        self.socket.emit(
            'response_stream', {
                'content': delta.value,
                'message_id': self.message_id,
                'is_final': False
            })

    @override
    def on_run_completed(self):
        # Émettre l'événement final quand le run est terminé
        self.socket.emit(
            'response_stream', {
                'content': '',
                'message_id': self.message_id,
                'is_final': True,
                'full_response': self.full_response
            })

    @override
    def on_tool_call_created(self, tool_call):
        # Pour gérer les appels d'outils comme code_interpreter si nécessaire
        pass

    @override
    def on_tool_call_delta(self, delta, snapshot):
        # Gérer les mises à jour des appels d'outils
        if delta.type == 'code_interpreter':
            if delta.code_interpreter and delta.code_interpreter.input:
                self.full_response += f"\n```python\n{delta.code_interpreter.input}\n```\n"
                self.socket.emit(
                    'response_stream', {
                        'content':
                        f"\n```python\n{delta.code_interpreter.input}\n```\n",
                        'message_id': self.message_id,
                        'is_final': False
                    })

            if delta.code_interpreter and delta.code_interpreter.outputs:
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        self.full_response += f"\n```\n{output.logs}\n```\n"
                        self.socket.emit(
                            'response_stream', {
                                'content': f"\n```\n{output.logs}\n```\n",
                                'message_id': self.message_id,
                                'is_final': False
                            })

            if delta.code_interpreter and delta.code_interpreter.outputs:
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        self.full_response += f"\n```\n{output.logs}\n```\n"
                        self.socket.emit(
                            'response_stream', {
                                'content': f"\n```\n{output.logs}\n```\n",
                                'message_id': self.message_id,
                                'is_final': False
                            })


# Initialize LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Import models after db initialization to avoid circular imports
from models import Conversation, Message, User, TelegramUser, TelegramConversation, TelegramMessage, Subscription, MessageFeedback
from whatsapp_bot import whatsapp, WhatsAppMessage

# Create tables within application context
with app.app_context():
    db.create_all()

# Register the WhatsApp blueprint
app.register_blueprint(whatsapp, url_prefix='/whatsapp')

# Register the Telegram blueprint
app.register_blueprint(telegram_admin_bp)


# Contexte d'application pour les commandes flask
@app.cli.command("init-db")
def init_db():
    db.create_all()
    print("Base de données initialisée !")


# Fonction utilitaire pour récupérer les messages stockés en session si nécessaire
# Fonction utilitaire pour récupérer les messages stockés en session si nécessaire
@app.route('/api/recover_message/<int:message_id>', methods=['GET'])
def recover_message(message_id):
    """Endpoint pour récupérer un message qui n'a pas pu être sauvegardé en BD ou dont le streaming s'est interrompu"""
    try:
        # D'abord, vérifier dans la base de données
        message = Message.query.get(message_id)

        # Si le message existe et a du contenu en BD
        if message and message.content and message.content.strip():
            logger.info(f"Récupération du message {message_id} depuis la BD")
            return jsonify({'success': True, 'content': message.content})

        # Sinon, vérifier dans la session
        if 'message_recovery' in session and str(
                message_id) in session['message_recovery']:
            content = session['message_recovery'][str(message_id)]

            # Si le message existe en BD mais est vide, le mettre à jour
            if message and (not message.content
                            or message.content.strip() == ''):
                try:
                    message.content = content
                    db.session.commit()
                    # Si succès, supprimer de la session
                    del session['message_recovery'][str(message_id)]
                    logger.info(
                        f"Message {message_id} récupéré de la session et sauvegardé en BD"
                    )
                except Exception as e:
                    logger.error(
                        f"Échec de mise à jour du message {message_id} en BD: {str(e)}"
                    )

            return jsonify({'success': True, 'content': content})

        # Message non trouvé
        logger.warning(
            f"Message {message_id} non trouvé ni en BD ni en session")
        return jsonify({'success': False, 'error': 'Message non trouvé'})

    except Exception as e:
        logger.error(
            f"Erreur lors de la récupération du message {message_id}: {str(e)}"
        )
        return jsonify({'success': False, 'error': str(e)})


@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))


@contextmanager
def db_retry_session(max_retries=3, retry_delay=0.5):
    """Context manager for database operations with retry logic"""
    for attempt in range(max_retries):
        try:
            yield db.session
            break
        except exc.OperationalError as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(
                f"Database connection failed, retrying... (attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(retry_delay)
        except Exception as e:
            raise


def get_db_context():
    """Get the Flask application context for database operations."""
    return app.app_context()


def get_or_create_conversation(thread_id=None, message_content=None):
    with db_retry_session() as session:
        if thread_id:
            conversation = Conversation.query.filter_by(
                thread_id=thread_id).first()
            # Vérifier si cette conversation appartient à l'utilisateur actuel
            if conversation and current_user.is_authenticated and conversation.user_id == current_user.id:
                # Vérifier si le thread OpenAI existe toujours (uniquement pour le modèle OpenAI)
                if CURRENT_MODEL == 'openai':
                    try:
                        # Tester si le thread existe dans OpenAI
                        client = get_ai_client()
                        client.beta.threads.messages.list(thread_id=thread_id,
                                                          limit=1)
                        # Si on arrive ici, le thread existe
                        return conversation
                    except Exception as e:
                        logger.warning(
                            f"Thread {thread_id} not found or invalid: {str(e)}"
                        )
                        # On continue pour créer un nouveau thread
                else:
                    # Pour les autres modèles, pas besoin de vérifier
                    return conversation
            # Si la conversation n'appartient pas à l'utilisateur actuel, on ignore ce thread_id

        # Create new thread and conversation
        client = get_ai_client()
        if CURRENT_MODEL == 'openai':
            # Only create thread for OpenAI
            thread = client.beta.threads.create()
            thread_id = thread.id
        else:
            # For other models, generate a UUID as thread_id
            thread_id = str(uuid.uuid4())

        # Associer la conversation avec l'utilisateur connecté
        user_id = None
        if current_user.is_authenticated:
            user_id = current_user.id

        # Create appropriate title based on message content if available
        title = None
        if message_content:
            # Use message content for title (trimmed if needed)
            title = message_content[:30] + "..." if len(message_content) > 30 else message_content
            logger.info(f"Creating conversation with title from message: '{title}'")

        conversation = Conversation(thread_id=thread_id, user_id=user_id, title=title)
        session.add(conversation)
        session.commit()

        logger.info(f"Conversation {conversation.id} créée/récupérée, événement non émis à ce stade")

        return conversation


@app.route('/privacy-policy')
def privacy_policy():
    """Privacy Policy page"""
    return render_template('privacy_policy.html')


@app.route('/')
@login_required
def chat():
    try:
        with db_retry_session() as db_session:

            conversation_history = []

            # Vérifier si l'utilisateur est connecté via Telegram ou WhatsApp
            is_telegram_user = session.get('is_telegram_user', False)
            telegram_id = session.get('telegram_id')
            is_whatsapp_user = session.get('is_whatsapp_user', False)
            whatsapp_number = session.get('whatsapp_number')

            # Vérifier si l'utilisateur actuel est réellement l'utilisateur Telegram indiqué
            if is_telegram_user and telegram_id and current_user.is_authenticated:
                if not current_user.phone_number.startswith(
                        f"telegram_{telegram_id}"):
                    # Les identifiants ne correspondent pas, nettoyer les données Telegram
                    session.pop('is_telegram_user', None)
                    session.pop('telegram_id', None)
                    is_telegram_user = False
                    telegram_id = None
                    logger.warning(
                        f"Session Telegram incohérente détectée pour l'utilisateur {current_user.id}, nettoyage effectué"
                    )

            # Vérifier si l'utilisateur actuel est réellement l'utilisateur WhatsApp indiqué
            if is_whatsapp_user and whatsapp_number and current_user.is_authenticated:
                if not current_user.phone_number.startswith(
                        f"whatsapp_{whatsapp_number}"):
                    # Les identifiants ne correspondent pas, nettoyer les données WhatsApp
                    session.pop('is_whatsapp_user', None)
                    session.pop('whatsapp_number', None)
                    is_whatsapp_user = False
                    whatsapp_number = None
                    logger.warning(
                        f"Session WhatsApp incohérente détectée pour l'utilisateur {current_user.id}, nettoyage effectué"
                    )

            else:
                # Ce bloc gère maintenant TOUS les utilisateurs connectés (Web, WhatsApp via Web, Telegram via Web)
                if current_user.is_authenticated: # Vérification si l'utilisateur est authentifié
                    # Récupère les conversations de la table Conversation liées à cet user_id
                    # (Fonctionne pour 'user_123', 'whatsapp_...', ET 'telegram_...')
                    recent_conversations = Conversation.query.filter_by(
                        deleted=False, user_id=current_user.id).order_by(
                            Conversation.updated_at.desc()).limit(
                                CONTEXT_MESSAGE_LIMIT).all()

                    for conv in recent_conversations:
                        # Chercher le premier message de l'utilisateur dans cette conversation (pour le titre)
                        first_user_message = Message.query.filter_by(
                            conversation_id=conv.id, role='user').order_by(
                                Message.created_at.asc()).first()

                        # Définir le titre basé sur le premier message ou le titre existant
                        title = conv.title
                        if first_user_message and first_user_message.content and not title:
                            message_text = first_user_message.content.strip()
                            # Exclure le contenu extrait d'image si présent
                            if '[Extracted Image Content]' in message_text:
                                message_text = message_text.split('[Extracted Image Content]')[0].strip()

                            if message_text:
                                title = message_text[:30] + "..." if len(message_text) > 30 else message_text

                        # Utiliser le titre par défaut si aucun titre n'a été défini
                        if not title:
                            title = f"Conversation du {conv.created_at.strftime('%d/%m/%Y')}"

                        # Ajouter à l'historique pour la barre latérale (sans marqueur de plateforme)
                        conversation_history.append({
                            'id': conv.id,
                            'title': title,
                            'subject': 'Général', # Peut être ajusté si nécessaire
                            'time': conv.created_at.strftime('%H:%M')
                            # PAS de clé 'is_telegram' ou 'is_whatsapp' ici
                        })

            return render_template('chat.html',
                                   history=[],
                                   conversation_history=conversation_history,
                                   # is_telegram=is_telegram_user, # Ligne supprimée
                                   credits=42)
    except Exception as e:
        logger.error(f"Error in chat route: {str(e)}")
        return render_template(
            'chat.html',
            history=[],
            conversation_history=[],
            credits=42,
            error="Une erreur est survenue. Veuillez réessayer.")


ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')


def get_interleaved_messages(conversation_id, current_message=None):
    """Returns properly interleaved messages for DeepSeek Reasoner"""
    messages = Message.query.filter_by(conversation_id=conversation_id)\
        .order_by(Message.created_at).all()

    # Start with system message
    formatted_messages = [{
        "role": "system",
        "content": get_system_instructions()
    }]

    # Process past messages ensuring alternation
    prev_role = None
    for msg in messages:
        # Skip consecutive messages with the same role
        if msg.role != prev_role:
            formatted_messages.append({
                "role": msg.role,
                "content": msg.content
            })
            prev_role = msg.role

    # Add current message if provided
    if current_message:
        # Only add if it wouldn't create consecutive user messages
        if not formatted_messages[-1]["role"] == "user":
            formatted_messages.append({
                "role": "user",
                "content": current_message
            })

    return formatted_messages

def conversation_is_valid(conversation, user):
    """Vérifie si un objet Conversation est valide et appartient à l'utilisateur."""
    if not conversation:
        return False # N'existe pas en DB ou marquée supprimée (car on filtre par deleted=False)

    # Vérifier l'appartenance à l'utilisateur (important si authentification activée)
    if not user.is_authenticated or conversation.user_id != user.id:
        logger.warning(f"Validation échec: Conversation {conversation.id} n'appartient pas à l'utilisateur {user.id}")
        return False

    # Vérifier si le thread existe chez OpenAI (uniquement si c'est le modèle OpenAI)
    if CURRENT_MODEL == 'openai':
        try:
            ai_client = get_ai_client() # Assurez-vous que cette fonction est accessible ici
            ai_client.beta.threads.retrieve(thread_id=conversation.thread_id)
            # Le thread existe chez OpenAI
        except Exception as e:
            logger.warning(f"Validation échec: Thread OpenAI {conversation.thread_id} introuvable ou invalide: {str(e)}.")
            return False # Thread OpenAI invalide

    # Si toutes les vérifications passent
    return True

@socketio.on('send_message')
def handle_message(data):
    logger.info(f"--- handle_message called. Current Flask session thread_id: {session.get('thread_id')}")
    try:
        # Vérifier si l'utilisateur est connecté via Telegram
        is_telegram_user = session.get('is_telegram_user', False)
        telegram_id = session.get('telegram_id')

        # Get the appropriate AI client based on current model setting
        ai_client = get_ai_client()

        # Variables to store Mathpix results
        mathpix_result = None
        formatted_summary = None

        session_thread_id = session.get('thread_id')
        frontend_thread_id = data.get('thread_id_from_localstorage') # Récupérer l'ID envoyé par le client
        conversation = None

        # 1. Essayer avec l'ID de la session Flask en priorité
        if session_thread_id:
            logger.info(f"--- handle_message: Trying thread_id from SESSION: {session_thread_id}")
            conv_from_session = Conversation.query.filter_by(thread_id=session_thread_id, deleted=False).first()
            logger.info(f"--- DB Query Result for session thread_id {session_thread_id}: {conv_from_session}")
            if conversation_is_valid(conv_from_session, current_user):
                logger.info(f"--- handle_message: Using VALIDATED thread_id from session: {session_thread_id}")
                conversation = conv_from_session
                # Mettre à jour la date d'accès si trouvé dans la session et valide
                conversation.updated_at = datetime.utcnow()
                db.session.commit() # Commit juste la mise à jour de la date
            else:
                logger.warning(f"--- handle_message: Session thread_id {session_thread_id} is INVALID. Clearing from session.")
                session.pop('thread_id', None) # Nettoyer session invalide

        # 2. Si session vide OU invalide, essayer l'ID du frontend (localStorage)
        if not conversation and frontend_thread_id:
            logger.warning(f"--- handle_message: Session empty/invalid, trying thread_id from FRONTEND: {frontend_thread_id}")
            conv_from_frontend = Conversation.query.filter_by(thread_id=frontend_thread_id, deleted=False).first()
            logger.info(f"--- DB Query Result for frontend thread_id {frontend_thread_id}: {conv_from_frontend}")
            if conversation_is_valid(conv_from_frontend, current_user):
                logger.info(f"--- handle_message: Using VALIDATED thread_id from frontend: {frontend_thread_id}. Updating session.")
                conversation = conv_from_frontend
                session['thread_id'] = frontend_thread_id # Mettre à jour la session Flask immédiatement
                # Mettre à jour la date d'accès si trouvé via frontend et valide
                conversation.updated_at = datetime.utcnow()
                db.session.commit() # Commit la mise à jour de la date et potentiellement la session (selon config)
            else:
                logger.warning(f"--- handle_message: Frontend thread_id {frontend_thread_id} is INVALID.")
                # Ne pas nettoyer la session ici, car elle était déjà vide ou invalide

        # 3. Si toujours pas de conversation valide, en créer une nouvelle
        logger.info(f"--- handle_message: About to check 'if not conversation'. Current conversation object: {conversation}")
        if not conversation:
            message_content = data.get('message', '').strip()
            # S'assurer qu'on a au moins l'image si le message est vide
            if not message_content and data.get('image'):
                message_content = "Analyse d'image" # Ou un autre placeholder

            logger.info(f"Aucun thread_id valide en session ou thread inexistant. Création d'une nouvelle conversation avec le titre basé sur le message: '{message_content[:30]}...'")
            conversation = get_or_create_conversation(thread_id=None, message_content=message_content) # Pass message content for title
            session['thread_id'] = conversation.thread_id # Mettre à jour la session avec le NOUVEAU thread_id
            logger.info(f"--- handle_message: NEW conversation created. Flask session 'thread_id' set to: {session.get('thread_id')}")
            logger.info(f"Nouvelle conversation {conversation.id} créée avec thread_id {conversation.thread_id} et titre '{conversation.title}'")

            # Émettre l'événement new_conversation pour la sidebar
            title = conversation.title or "Nouvelle conversation"
            emit('new_conversation', {
                'id': conversation.id, # Envoyer l'ID DB pour l'UI
                'thread_id': conversation.thread_id, # Envoyer aussi le thread_id pour localStorage
                'title': title,
                'subject': 'Général',
                'time': conversation.created_at.strftime('%H:%M')
            }, broadcast=False) # broadcast=False car seul cet utilisateur doit l'ajouter

        # Mettre à jour la date de la conversation utilisée (si elle existe - sécurité)
        if conversation:
            # La mise à jour de updated_at est maintenant faite dans les blocs de validation ci-dessus
            logger.info(f"Utilisation de la conversation {conversation.id} avec thread_id {conversation.thread_id}")
            # S'assurer que le thread_id est bien dans la session pour les étapes suivantes
            if 'thread_id' not in session or session['thread_id'] != conversation.thread_id:
                 logger.warning(f"--- Double check: Correcting session thread_id to {conversation.thread_id}")
                 session['thread_id'] = conversation.thread_id

        if current_user.is_authenticated and not session.get('is_telegram_user') and not session.get('is_whatsapp_user'): # Assurer que c'est un user web standard
            try:
                # Pas besoin de requêter current_user à nouveau, Flask-Login le gère
                current_user.last_active = datetime.utcnow()
                db.session.commit() # Commit cette petite mise à jour
                logger.debug(f"User {current_user.id} last_active updated.")
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Erreur MAJ last_active pour user {current_user.id}: {e}")
        else:
            # Sécurité: si 'conversation' est toujours None, c'est une erreur interne
            logger.error("Erreur critique: Impossible d'obtenir ou de créer une conversation valide APRÈS TOUTES LES VÉRIFICATIONS.")
            emit('receive_message', {'message': 'Erreur serveur critique: Impossible de gérer la conversation.', 'id': 0})
            return

        # ======================
        # TRAITEMENT DES IMAGES - UTILISER LA MÉTHODE NON-STREAMING
        # ======================
        if 'image' in data and data['image']:
            try:
                logger.info(
                    "Traitement d'image détecté: utilisation de la méthode non-streaming"
                )
                filename = save_base64_image(data['image'])
                image_url = request.url_root.rstrip('/') + url_for(
                    'static', filename=f'uploads/{filename}')

                # Process image with Mathpix
                mathpix_result = process_image_with_mathpix(data['image'])
                logger.debug(
                    f"Résultat Mathpix obtenu: {len(str(mathpix_result))} caractères"
                )

                # Check if an error occurred
                if "error" in mathpix_result:
                    logger.error(
                        f"Mathpix error: {mathpix_result['error']}")
                    formatted_summary = "Image content extraction failed. I will analyze the image visually."
                else:
                    formatted_summary = mathpix_result.get(
                        "formatted_summary", "")
                    logger.debug(
                        f"Contenu formaté extrait: {len(formatted_summary)} caractères"
                    )

                # Build user message with image extraction
                user_content = data.get('message', '')
                if formatted_summary:
                    user_store_content = f"{user_content}\n\n[Extracted Image Content]\n{formatted_summary}" if user_content else f"[Extracted Image Content]\n{formatted_summary}"
                else:
                    user_store_content = user_content

                # Store user message with image and extracted content
                user_message = Message(conversation_id=conversation.id,
                                       role='user',
                                       content=user_store_content,
                                       image_url=image_url)
                db.session.add(user_message)
                db.session.commit()  # Commit pour obtenir l'ID du message

                # Prepare message text for assistant
                message_for_assistant = data.get(
                    'message', '') + "\n\n" if data.get('message') else ""
                message_for_assistant += formatted_summary if formatted_summary else "Please analyze the image I uploaded."

                # Créer un message vide pour l'assistant, à remplir plus tard
                db_message = Message(
                    conversation_id=conversation.id,
                    role='assistant',
                    content=""  # Contenu initial vide
                )
                db.session.add(db_message)
                db.session.commit()  # Commit pour obtenir l'ID

                # Envoyer un message initial pour démarrer l'affichage du loader côté client
                emit('message_started', {'message_id': db_message.id})

                # Détecter et définir un titre si c'est une nouvelle conversation
                if not conversation.title or conversation.title == "Nouvelle conversation" or (conversation.title and conversation.title.startswith("Conversation du")):
                    if 'image' in data and data['image']:
                        conversation.title = "Analyse d'image"
                        logger.info(
                            f"Définition du titre pour nouvelle conversation avec image: 'Analyse d'image'"
                        )
                    else:
                        # Fallback to message text or default title
                        conversation.title = data.get(
                            'message', '')[:30] + "..." if data.get(
                                'message', '') else "Nouvelle Conversation"

                    # Avant de mettre à jour le titre
                    should_update = True  # Par défaut pour les nouvelles conversations
                    if conversation.title and conversation.title != "Nouvelle conversation":
                        # Pour les conversations existantes, suivre la même logique que le frontend
                        current_title = conversation.title
                        new_title = "Analyse d'image" if 'image' in data and data['image'] else (data.get('message', '')[:30] + "..." if data.get('message', '') else "Nouvelle conversation")
                        should_update = current_title.startswith("Conversation du") or new_title != current_title

                    # N'appliquer la mise à jour que si nécessaire
                    if should_update:
                        logger.info(f"Mise à jour du titre: '{conversation.title}' → '{conversation.title}'")
                        # Sauvegarder le nouveau titre
                        db.session.commit()
                    else:
                        logger.info(f"Conservation du titre existant: '{conversation.title}'")

                    # Émettre l'événement pour informer tous les clients
                    emit('new_conversation', {
                        'id': conversation.id,
                        'title': conversation.title,
                        'subject': 'Général',
                        'time': conversation.created_at.strftime('%H:%M'),
                        'is_image': 'image' in data and data['image']
                    },
                         broadcast=True)

                # Traitement selon le modèle sélectionné (unifié et NON-STREAMING pour images)
                assistant_message = "" # Initialiser

                # Préparer les messages pour l'API (commun à tous les modèles)
                conversation_messages = Message.query.filter_by(conversation_id=conversation.id)\
                                                    .order_by(Message.created_at).all()
                # Formatage spécifique pour Reasoner si besoin, sinon standard
                if CURRENT_MODEL == 'deepseek-reasoner':
                     messages = get_interleaved_messages(conversation.id, message_for_assistant)
                     # Ajustements potentiels nécessaires à get_interleaved_messages pour exclure user_message.id
                else:
                     messages = [{"role": "system", "content": get_system_instructions()}]
                     for msg in conversation_messages:
                         if msg.id == user_message.id: continue # Exclure le message courant
                         role = msg.role if msg.role == 'user' else 'assistant'
                         if msg.content and msg.content.strip():
                             messages.append({"role": role, "content": msg.content})
                         else:
                             logger.warning(f"Skipping historical message ID {msg.id} with empty content during image processing.")
                     if message_for_assistant and message_for_assistant.strip():
                         messages.append({"role": "user", "content": message_for_assistant})
                     else:
                         logger.error("Cannot send request: message_for_assistant is empty after processing image/caption.")
                         emit('response_stream', {'content': "Erreur: Impossible de traiter le contenu de l'image.", 'message_id': db_message.id, 'is_final': True, 'error': True})
                         db_message.content = "Erreur: Contenu image vide"; db.session.commit(); return


                # Gestion spécifique au modèle AVEC STREAMING NATIF (si possible)

                assistant_message = "" # Pour stocker la réponse complète
                update_success = False
                max_update_attempts = 3

                if CURRENT_MODEL == 'openai':
                    # Utiliser EXPLICITEMENT le client OpenAI standard et le streaming Assistants
                    logger.info("Utilisation d'OpenAI pour l'image en mode streaming (Assistant API)")
                    openai_assist_client = openai_client
                    try:
                        # Ajouter message utilisateur (texte seul pour l'instant)
                        # NOTE: Pour que l'assistant voie l'image, il faudrait gérer l'upload de fichier
                        # et passer le file_id ici, ce qui n'est pas fait.
                        openai_assist_client.beta.threads.messages.create(
                            thread_id=conversation.thread_id,
                            role="user",
                            content=message_for_assistant
                        )

                        # Créer un gestionnaire d'événements pour traiter les événements de streaming
                        event_handler = OpenAIAssistantEventHandler(socketio, db_message.id)

                        # Utiliser la méthode de streaming native de l'API Assistants
                        logger.info(f"Appel à runs.stream pour thread {conversation.thread_id} (Image Path)")
                        with openai_assist_client.beta.threads.runs.stream(
                            thread_id=conversation.thread_id,
                            assistant_id=ASSISTANT_ID,
                            event_handler=event_handler,
                        ) as stream:
                            stream.until_done() # Attend la fin du stream

                        # Récupérer la réponse complète depuis l'event handler
                        assistant_message = event_handler.full_response
                        logger.info(f"Stream OpenAI Assistant terminé. Réponse complète obtenue (longueur: {len(assistant_message)}).")

                    except Exception as stream_error:
                        logger.error(f"Erreur pendant le streaming OpenAI Assistant (Image): {str(stream_error)}", exc_info=True)
                        assistant_message = f"Erreur lors du streaming OpenAI Assistant: {str(stream_error)}"
                        # Émettre un message d'erreur final si le handler n'a pas pu le faire
                        emit('response_stream', {
                            'content': assistant_message,
                            'message_id': db_message.id,
                            'is_final': True,
                            'error': True,
                            'full_response': assistant_message
                        })

                else: # Logique pour Gemini (via compatible), DeepSeek, Qwen AVEC STREAMING NATIF
                     chat_comp_client = get_ai_client()
                     model_name = get_model_name()
                     logger.info(f"Utilisation de {CURRENT_MODEL} (model: {model_name}) pour l'image en mode STREAMING via endpoint compatible")
                     if model_name is None: # Fallback
                         # ... (logique fallback model_name) ...
                         if CURRENT_MODEL == 'deepseek': model_name = "deepseek-chat"
                         elif CURRENT_MODEL == 'deepseek-reasoner': model_name = "deepseek-reasoner"
                         elif CURRENT_MODEL == 'qwen': model_name = "qwen-max-latest"
                         elif CURRENT_MODEL == 'gemini': model_name = "gemini-pro"
                         else: model_name = "deepseek-chat"
                         logger.warning(f"Model name was None, using fallback: {model_name}")

                     try:
                         if not messages or len(messages) <= 1: raise ValueError("Liste messages API vide ou invalide.")

                         response = chat_comp_client.chat.completions.create(
                             model=model_name,
                             messages=messages,
                             stream=True # <<< STREAMING ACTIVÉ ICI >>>
                         )

                         # Itérer sur les chunks et émettre
                         for chunk in response:
                             chunk_content = None
                             if chunk.choices and len(chunk.choices) > 0:
                                 delta = chunk.choices[0].delta
                                 if delta and hasattr(delta, 'content'):
                                     chunk_content = delta.content

                             if chunk_content:
                                 assistant_message += chunk_content
                                 emit('response_stream', {
                                     'content': chunk_content,
                                     'message_id': db_message.id,
                                     'is_final': False
                                 })
                                 # (Optionnel: Sauvegarde incrémentale DB)

                         # Envoyer l'événement final après la boucle de streaming
                         emit('response_stream', {
                             'content': '',
                             'message_id': db_message.id,
                             'is_final': True,
                             'full_response': assistant_message
                         })
                         logger.info(f"Stream {CURRENT_MODEL} terminé. Réponse complète obtenue (longueur: {len(assistant_message)}).")

                     except Exception as stream_error:
                         logger.error(f"Erreur pendant le streaming {CURRENT_MODEL} (Image): {str(stream_error)}", exc_info=True)
                         assistant_message = f"Erreur lors du streaming {CURRENT_MODEL}: {str(stream_error)}"
                         # Émettre un message d'erreur final
                         emit('response_stream', {
                             'content': assistant_message,
                             'message_id': db_message.id,
                             'is_final': True,
                             'error': True,
                             'full_response': assistant_message
                         })

                # ----- Sauvegarde finale en DB (après le if/else du modèle) -----
                try:
                    # S'assurer qu'on a une réponse (ou un message d'erreur) à sauvegarder
                    if assistant_message is None: # Ne devrait pas arriver, mais sécurité
                         assistant_message = "Erreur: Aucune réponse n'a été générée."
                         logger.error("Assistant message is None before final save.")

                    current_db_message = db.session.get(Message, db_message.id)
                    if current_db_message:
                        current_db_message.content = assistant_message
                        db.session.commit()
                        logger.info(f"Réponse/Erreur pour image sauvegardée (Streamed, Message ID: {db_message.id})")
                        update_success = True # Marquer comme succès pour ne pas utiliser la session
                    else:
                        logger.error(f"Impossible de trouver le message {db_message.id} pour sauvegarder la réponse/erreur image (Streamed).")
                except Exception as final_save_error:
                     logger.error(f"Erreur sauvegarde finale réponse/erreur image (Streamed): {str(final_save_error)}")
                     db.session.rollback()
                     update_success = False # Marquer comme échec pour utiliser la session

                # Sauvegarde en session si échec BD (uniquement si la sauvegarde a échoué)
                if not update_success and assistant_message is not None:
                     if 'message_recovery' not in session: session['message_recovery'] = {}
                     session['message_recovery'][str(db_message.id)] = assistant_message
                     logger.warning(f"Sauvegarde de secours réponse/erreur image (Streamed) {db_message.id} dans session")

                # Mettre à jour le message de l'assistant dans la base de données avec la réponse complète
                try:
                    current_db_message = db.session.get(Message, db_message.id)
                    if current_db_message:
                        current_db_message.content = assistant_message
                        db.session.commit()
                        logger.info(f"Réponse pour image sauvegardée (Message ID: {db_message.id})")
                    else:
                        logger.error(f"Impossible de trouver le message {db_message.id} pour sauvegarder la réponse image.")
                except Exception as final_save_error:
                     logger.error(f"Erreur sauvegarde finale réponse image: {str(final_save_error)}")
                     db.session.rollback()

            except Exception as img_error:
                logger.error(f"Image processing error: {str(img_error)}",
                             exc_info=True)
                emit(
                    'receive_message', {
                        'message':
                        'Failed to process image. Please make sure it\'s a valid image file.',
                        'id': 0
                    })
                return

        # ======================
        # TRAITEMENT DU TEXTE - UTILISER LA MÉTHODE STREAMING
        # ======================
        else: # Si pas d'image
            # 1. Récupérer le message utilisateur actuel
            current_user_message_content = data.get('message', '')

            # Vérifier si le message est vide ou contient seulement des espaces
            if not current_user_message_content or current_user_message_content.isspace():
                logger.warning("Received an empty or whitespace-only message. Ignoring.")
                # Optionnel: Envoyer un message à l'utilisateur pour l'informer
                emit('receive_message', {
                    'message': 'Cannot process an empty message.',
                    'id': 0, # Ou un ID spécifique pour les erreurs
                    'error': True
                })
                return # Ne pas continuer si le message est vide

            # 2. Créer l'objet Message pour l'utilisateur MAIS NE PAS ENCORE COMMIT
            user_message = Message(conversation_id=conversation.id,
                                   role='user',
                                   content=current_user_message_content)
            db.session.add(user_message)
            # PAS DE COMMIT ICI POUR L'INSTANT

            # 3. Créer le message placeholder pour l'assistant (celui-ci peut être commit pour avoir un ID)
            db_message = Message(
                conversation_id=conversation.id,
                role='assistant',
                content=""
            )
            db.session.add(db_message)
            db.session.commit() # Commit seulement pour obtenir l'ID de db_message

            # Envoyer un message initial pour démarrer l'affichage du loader côté client
            emit('message_started', {'message_id': db_message.id})

            assistant_message = "" # Sera rempli par le streaming

            # 4. Traiter l'appel API si nécessaire
            if CURRENT_MODEL in [
                    'deepseek', 'deepseek-reasoner', 'qwen', 'gemini'
            ]:
                logger.info(f"Traitement de texte avec modèle {CURRENT_MODEL} via endpoint compatible OpenAI (streaming)")
                ai_client = get_ai_client()
                model_name = get_model_name()

                # 5. RÉCUPÉRER L'HISTORIQUE AVANT DE SAUVEGARDER LE MESSAGE ACTUEL
                conversation_messages = Message.query.filter_by(conversation_id=conversation.id)\
                                                     .order_by(Message.created_at).all()

                # 6. Construire la liste des messages pour l'API à partir de l'historique SEULEMENT
                if CURRENT_MODEL == 'deepseek-reasoner':
                    # Pour simplifier ici, on fait comme pour les autres modèles :
                    messages = [{"role": "system", "content": get_system_instructions()}]
                    last_role = None
                    for msg in conversation_messages: # Utilise l'historique SANS le nouveau message
                        role = msg.role if msg.role == 'user' else 'assistant'
                        if msg.content and msg.content.strip():
                            # Logique spécifique Reasoner: s'assurer de l'alternance
                            if role != last_role:
                                messages.append({"role": role, "content": msg.content})
                                last_role = role
                            else:
                                # Que faire si rôles consécutifs? Ignorer? Concaténer? Pour l'instant, on ignore.
                                logger.warning(f"Skipping consecutive message role '{role}' for Deepseek Reasoner (Msg ID: {msg.id})")
                        else:
                            logger.warning(f"Skipping historical message ID {msg.id} with empty content.")

                else: # Pour deepseek-chat, qwen, gemini
                    messages = [{"role": "system", "content": get_system_instructions()}]
                    for msg in conversation_messages: # Utilise l'historique SANS le nouveau message
                        role = msg.role if msg.role == 'user' else 'assistant'
                        if msg.content and msg.content.strip():
                            messages.append({"role": role, "content": msg.content})
                        else:
                            logger.warning(f"Skipping historical message ID {msg.id} with empty content.")

                # 7. AJOUTER le message utilisateur ACTUEL (non vide) à la liste pour l'API
                if current_user_message_content and current_user_message_content.strip():
                    # S'assurer de l'alternance pour Reasoner
                    if CURRENT_MODEL == 'deepseek-reasoner':
                        if not messages or messages[-1]['role'] != 'user':
                            messages.append({"role": "user", "content": current_user_message_content})
                        else:
                            logger.warning("Skipping current user message for Deepseek Reasoner due to consecutive roles.")
                    else:
                        messages.append({"role": "user", "content": current_user_message_content})
                else:
                    # Le cas du message utilisateur vide est déjà géré plus haut par le `return`
                    pass # On ne devrait pas arriver ici si le message était vide

                # 8. MAINTENANT, on peut commit le message utilisateur qui avait été ajouté à la session db plus tôt
                try:
                    db.session.commit() # Sauvegarde user_message et db_message (qui a déjà été commit mais ça ne pose pas de problème)
                    logger.info(f"User message ID {user_message.id} and Assistant placeholder ID {db_message.id} committed.")
                except Exception as commit_error:
                    logger.error(f"Error committing user message after preparing API call: {commit_error}")
                    db.session.rollback()
                    # Gérer l'erreur (peut-être annuler l'appel API ?)
                    emit('response_stream', {
                        'content': "Erreur lors de la sauvegarde de votre message.",
                        'message_id': db_message.id,
                        'is_final': True, 'error': True
                    })
                    return # Arrêter ici

                # Vérifier si on a assez de messages pour appeler l'API
                if len(messages) <= 1 and not (current_user_message_content and current_user_message_content.strip()):
                    logger.error("Cannot send request to Gemini with only a system message and no valid user message.")
                    # Envoyer un message d'erreur à l'utilisateur via SocketIO
                    emit('response_stream', {
                        'content': "Désolé, je ne peux pas traiter un message vide ou une conversation sans message.",
                        'message_id': db_message.id if 'db_message' in locals() else 0,
                        'is_final': True, 'error': True
                    })
                    # Sauvegarder l'erreur si l'objet db_message a été créé
                    if 'db_message' in locals() and db_message:
                        try:
                            db_message.content = "Erreur: Tentative d'envoyer un message vide à l'API."
                            db.session.commit()
                        except Exception as save_err:
                            logger.error(f"Failed to save empty message error to DB: {save_err}")
                            db.session.rollback()
                    return # Important: Stopper l'exécution de la fonction ici pour ne pas appeler l'API

                try:
                    response = ai_client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        stream=True  # <<--- STREAMING NATIF ACTIVÉ POUR TOUS DANS CE BLOC
                    )

                    assistant_message = ""
                    update_success = False
                    max_update_attempts = 3

                    for chunk in response:
                        # Extraction standard du contenu du chunk delta
                        chunk_content = None
                        if chunk.choices and len(chunk.choices) > 0:
                            delta = chunk.choices[0].delta
                            if delta and hasattr(delta, 'content'):
                                chunk_content = delta.content

                        if chunk_content:
                            assistant_message += chunk_content
                            emit('response_stream', {
                                'content': chunk_content,
                                'message_id': db_message.id,
                                'is_final': False
                            })
                            # (Optionnel) Mise à jour incrémentale de la BD peut être ajoutée ici

                    # Mise à jour finale de la base de données (avec tentatives)
                    for attempt in range(max_update_attempts):
                        try:
                            # S'assurer que db_message existe toujours
                            current_db_message = db.session.get(Message, db_message.id)
                            if current_db_message:
                                current_db_message.content = assistant_message
                                db.session.commit()
                                logger.info(f"Message {db_message.id} ({CURRENT_MODEL} Stream) sauvegardé avec succès en base de données (tentative {attempt+1})")
                                update_success = True
                                break
                            else:
                                logger.warning(f"Message {db_message.id} non trouvé pour sauvegarde finale ({CURRENT_MODEL} Stream).")
                                # Pas de nouvelle tentative si le message n'existe plus
                                break
                        except Exception as e:
                            logger.error(f"Échec de sauvegarde du message {db_message.id} ({CURRENT_MODEL} Stream) (tentative {attempt+1}): {str(e)}")
                            db.session.rollback()
                            time.sleep(0.5)

                    # Émettre le message final
                    emit('response_stream', {
                        'content': '',
                        'message_id': db_message.id,
                        'is_final': True,
                        'full_response': assistant_message,
                        'db_saved': update_success
                    })

                    # Sauvegarde en session si échec BD
                    if not update_success:
                        if 'message_recovery' not in session:
                            session['message_recovery'] = {}
                        session['message_recovery'][str(db_message.id)] = assistant_message
                        logger.warning(f"Sauvegarde de secours du message {db_message.id} ({CURRENT_MODEL} Stream) dans la session")

                except Exception as stream_error:
                    logger.error(f"Erreur pendant le streaming {CURRENT_MODEL} (compatible OpenAI): {str(stream_error)}", exc_info=True)
                    error_content = f"Erreur lors de la communication avec {CURRENT_MODEL}: {stream_error}"
                    emit('response_stream', {
                        'content': error_content,
                        'message_id': db_message.id,
                        'is_final': True,
                        'error': True
                    })
                    # Essayer de sauvegarder l'erreur dans la BD
                    try:
                        current_db_message = db.session.get(Message, db_message.id)
                        if current_db_message:
                            current_db_message.content = error_content
                            db.session.commit()
                    except Exception as e_save:
                        logger.error(f"Impossible de sauvegarder l'erreur {CURRENT_MODEL} dans la BD: {e_save}")
                        db.session.rollback()

            else: # Si CURRENT_MODEL est 'openai' (ou autre non listé)
                # Utiliser OpenAI's threads API with streaming
                logger.info("Traitement de texte avec OpenAI en mode streaming")

                # Envoyer le message utilisateur au thread
                ai_client.beta.threads.messages.create(
                    thread_id=conversation.thread_id,
                    role="user",
                    content=data.get('message', ''))

                # Dans la partie où vous vérifiez les runs actifs avant d'en créer un nouveau
                try:
                    # Vérifier si un run est déjà actif pour ce thread
                    runs_list = ai_client.beta.threads.runs.list(thread_id=conversation.thread_id, limit=1)

                    if runs_list.data and len(runs_list.data) > 0:
                        active_run = runs_list.data[0]

                        # Vérifier si le run est vraiment actif ou juste non terminé
                        if active_run.status in ['queued', 'in_progress']:
                            logger.warning(f"Run actif détecté ({active_run.id}, statut: {active_run.status}). Tentative d'annulation...")

                            try:
                                ai_client.beta.threads.runs.cancel(thread_id=conversation.thread_id, run_id=active_run.id)
                                # Attendre un moment pour que l'annulation soit effective
                                time.sleep(1)
                                logger.info(f"Run précédent {active_run.id} annulé avec succès")
                            except Exception as cancel_error:
                                logger.error(f"Impossible d'annuler le run actif: {str(cancel_error)}")
                                # Si impossible d'annuler, attendre un peu plus longtemps
                                time.sleep(2)
                        elif active_run.status in ['cancelling', 'expired']:
                            # Ces statuts indiquent que le run est en cours de fermeture, attendre un peu
                            logger.info(f"Run {active_run.id} en cours de fermeture (statut: {active_run.status}), attente...")
                            time.sleep(2)
                        elif active_run.status not in ['completed', 'failed', 'cancelled']:
                            # Statut inconnu ou inattendu, attendre par précaution
                            logger.warning(f"Run {active_run.id} dans un état inattendu: {active_run.status}, attente...")
                            time.sleep(1)

                    # Créer un gestionnaire d'événements pour traiter les événements de streaming
                    event_handler = OpenAIAssistantEventHandler(
                        socketio, db_message.id)

                    # Utiliser la méthode de streaming native de l'API
                    logger.info(f"Appel à runs.stream pour thread {conversation.thread_id}")
                    with ai_client.beta.threads.runs.stream(
                        thread_id=conversation.thread_id,
                        assistant_id=ASSISTANT_ID,
                        event_handler=event_handler,
                    ) as stream:
                        stream.until_done()
                        # À la fin du stream réussi, le run_id devrait être dans l'event_handler
                        if event_handler.run_id:
                            logger.info(f"Stream terminé pour run ID: {event_handler.run_id}")
                        else:
                            logger.warning("Stream terminé mais run_id non capturé par EventHandler.")

                    # Récupérer la réponse complète
                    assistant_message = event_handler.full_response

                except Exception as stream_error:
                    logger.error(f"Error streaming assistant response: {str(stream_error)}")

                    # Fallback: Essayer de récupérer le résultat du run créé *avant* l'erreur de streaming
                    logger.warning("Tentative de récupération du résultat en mode non-streaming après échec du stream.")
                    assistant_message = "" # Réinitialiser au cas où
                    try:
                        # Vérifier si l'EventHandler a pu capturer un run_id
                        if event_handler and event_handler.run_id:
                            run_id_to_check = event_handler.run_id
                            logger.info(f"Vérification du statut du run {run_id_to_check} (capturé par EventHandler) après échec du stream.")
                            logger.info(f"Vérification du statut du run {run_id_to_check} créé avant l'échec du stream.")

                            # Attendre que le run soit terminé (ou échoue/expire)
                            timeout = 45 # Timeout plus long pour le fallback
                            start_time = time.time()
                            run_completed_fallback = False

                            while time.time() - start_time < timeout:
                                run_status = ai_client.beta.threads.runs.retrieve(
                                    thread_id=conversation.thread_id,
                                    run_id=run_id_to_check
                                )

                                if run_status.status == 'completed':
                                    run_completed_fallback = True
                                    logger.info(f"Run {run_id_to_check} terminé avec succès (fallback).")
                                    break
                                elif run_status.status in ['failed', 'cancelled', 'expired']:
                                    error_msg = f"Le traitement du run {run_id_to_check} a échoué ou expiré (statut: {run_status.status})."
                                    if hasattr(run_status, 'last_error') and run_status.last_error:
                                        error_msg += f" Erreur: {run_status.last_error.message}"

                                    logger.error(error_msg)
                                    emit('response_stream', {
                                        'content': error_msg,
                                        'message_id': db_message.id,
                                        'is_final': True, 'error': True
                                    })
                                    return # Sortir de handle_message si le run échoue

                                # Attendre avant la prochaine vérification
                                eventlet.sleep(2) # Attente plus longue dans le fallback

                            if not run_completed_fallback:
                                logger.error(f"Timeout lors de l'attente du run {run_id_to_check} en mode fallback.")
                                # Essayer d'annuler le run s'il est toujours actif
                                try:
                                    current_status = ai_client.beta.threads.runs.retrieve(thread_id=conversation.thread_id, run_id=run_id_to_check).status
                                    if current_status in ['queued', 'in_progress']:
                                        ai_client.beta.threads.runs.cancel(thread_id=conversation.thread_id, run_id=run_id_to_check)
                                        logger.info(f"Tentative d'annulation du run {run_id_to_check} après timeout du fallback.")
                                except Exception as cancel_fallback_error:
                                    logger.warning(f"Impossible d'annuler le run {run_id_to_check} après timeout du fallback: {cancel_fallback_error}")

                                emit('response_stream', {
                                    'content': 'La requête a expiré (fallback).',
                                    'message_id': db_message.id,
                                    'is_final': True, 'error': True
                                })
                                return # Sortir de handle_message

                            # Si le run est terminé, récupérer les messages
                            messages_fallback = ai_client.beta.threads.messages.list(
                                thread_id=conversation.thread_id,
                                order="desc",
                                limit=1 # Obtenir le dernier message (la réponse de l'assistant)
                            )

                            if messages_fallback.data and len(messages_fallback.data) > 0:
                                # Vérifier que le dernier message est bien de l'assistant
                                if messages_fallback.data[0].role == 'assistant':
                                    assistant_message = messages_fallback.data[0].content[0].text.value
                                    logger.info(f"Réponse récupérée avec succès pour le run {run_id_to_check} (fallback).")

                                    # Simuler un streaming pour l'utilisateur (identique au code supprimé)
                                    words = assistant_message.split()
                                    for i in range(0, len(words), 5):
                                        chunk = ' '.join(words[i:i+5]) + ' '
                                        emit('response_stream', {
                                            'content': chunk,
                                            'message_id': db_message.id,
                                            'is_final': False
                                        })
                                        eventlet.sleep(0.05)

                                    # Émettre le signal final
                                    emit('response_stream', {
                                        'content': '',
                                        'message_id': db_message.id,
                                        'is_final': True,
                                        'full_response': assistant_message
                                    })
                                else:
                                    logger.error(f"Le dernier message du thread {conversation.thread_id} n'est pas de l'assistant (role: {messages_fallback.data[0].role}). Impossible de récupérer la réponse.")
                                    assistant_message = "Erreur: Impossible de récupérer la réponse finale de l'assistant."
                                    emit('response_stream', {'content': assistant_message, 'message_id': db_message.id, 'is_final': True, 'error': True})

                            else:
                                logger.error(f"Aucun message trouvé dans le thread {conversation.thread_id} après complétion du run {run_id_to_check} (fallback).")
                                assistant_message = "Erreur: Aucune réponse de l'assistant trouvée après traitement."
                                emit('response_stream', {'content': assistant_message, 'message_id': db_message.id, 'is_final': True, 'error': True})

                        else:
                            # Si EventHandler est None ou n'a pas de run_id, l'erreur s'est produite très tôt
                            logger.error("EventHandler n'a pas capturé de run_id. L'erreur est survenue avant ou pendant la création du run par stream.")
                            assistant_message = "Erreur critique: Impossible de suivre l'exécution de la requête."
                            emit('response_stream', {'content': assistant_message, 'message_id': db_message.id, 'is_final': True, 'error': True})

                    except Exception as fallback_error:
                        logger.error(f"Erreur majeure dans l'approche fallback non-streaming: {str(fallback_error)}")
                        assistant_message = f"Une erreur interne est survenue lors de la récupération de la réponse: {str(fallback_error)}"
                        emit('response_stream', {'content': assistant_message, 'message_id': db_message.id, 'is_final': True, 'error': True})
                        pass # L'erreur sera gérée par l'émission finale ci-dessous si assistant_message est vide

                    # Si le fallback n'a pas réussi à récupérer un message, envoyer une erreur générique
                    if not assistant_message:
                        logger.error("Échec final de récupération de la réponse après erreur de streaming.")
                        assistant_message = "Une erreur est survenue pendant le traitement de votre requête après un problème initial."
                        emit('response_stream', {
                            'content': assistant_message,
                            'message_id': db_message.id,
                            'is_final': True, 'error': True
                        })
                        # Sauvegarder l'erreur dans db_message ici si nécessaire
                        db_message.content = assistant_message
                        db.session.commit()
                        return # Sortir si on n'a pas pu récupérer de réponse

                # Mettre à jour le message de l'assistant dans la base de données avec la réponse complète
                if 'db_message' in locals() and db_message:
                    db_message.content = assistant_message
                    db.session.commit()
                else:
                    logger.error("Variable db_message non trouvée lors de la sauvegarde finale.")

                # Generate and set conversation title if this is the first message
                if conversation.title == "Nouvelle conversation" or conversation.title.startswith("Conversation du") or not conversation.title:
                    logger.info(
                        f"Création du titre pour une nouvelle conversation - image présente: {'image' in data}"
                    )

                    # Définir le titre en priorité pour les images, indépendamment du mode de traitement
                    if 'image' in data and data['image']:
                        title = "Analyse d'image"
                        logger.info(
                            "Image détectée, titre défini prioritairement à: 'Analyse d'image'"
                        )
                    else:
                        # Sinon utiliser le texte du message
                        message_text = data.get('message', '').strip()
                        if message_text:
                            title = message_text[:30] + "..." if len(message_text) > 30 else message_text
                            logger.info(
                                f"Titre basé sur le texte du message: '{title}'"
                            )
                        else:
                            # Si pas de texte, titre par défaut
                            title = "Nouvelle conversation"
                            logger.info(
                                "Aucun contenu détecté, titre par défaut utilisé"
                            )

                    should_update = True  # Par défaut pour les nouvelles conversations
                    if conversation.title and conversation.title != "Nouvelle conversation":
                        # Pour les conversations existantes, suivre la même logique que le frontend
                        should_update = conversation.title.startswith("Conversation du") or title != conversation.title

                    # N'appliquer la mise à jour que si nécessaire
                    if should_update:
                        logger.info(f"Mise à jour du titre: '{conversation.title}' → '{title}'")
                        conversation.title = title
                        db.session.commit()
                    else:
                        logger.info(f"Conservation du titre existant: '{conversation.title}'")

                    # Toujours émettre l'événement pour mettre à jour l'interface utilisateur
                    # Utiliser broadcast=True pour assurer que tous les clients sont notifiés
                    logger.info(
                        f"Émission de l'événement new_conversation pour la conversation {conversation.id} avec titre: {title}"
                    )
                    emit('new_conversation', {
                        'id': conversation.id,
                        'title': title,
                        'subject': 'Général',
                        'time': conversation.created_at.strftime('%H:%M'),
                        'is_image': 'image' in data and data['image']
                    },
                         broadcast=True)
                else:
                    # Si la conversation a déjà un titre, émettre quand même l'événement pour mettre à jour l'interface
                    emit('new_conversation', {
                        'id': conversation.id,
                        'title': conversation.title,
                        'subject': 'Général',
                        'time': conversation.created_at.strftime('%H:%M')
                    },
                         broadcast=True)

    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}", exc_info=True)
        error_message = str(e)
        if "image" in error_message.lower():
            emit(
                'receive_message', {
                    'message':
                    'Error processing image. Please ensure the image is in a supported format (JPG, PNG, GIF) and try again.',
                    'id': 0
                })
        else:
            emit(
                'receive_message', {
                    'message':
                    f'An error occurred while processing your message. Please try again.',
                    'id': 0
                })


@app.route('/admin/conversations/<platform>/<int:conv_id>/status', methods=['PUT'])
# @login_required # Décommenter si l'admin doit être loggué via Flask-Login
def update_conversation_status(platform, conv_id):
    """Met à jour le statut (active/archived) d'une conversation Web ou Telegram."""
    # Vérifier si l'utilisateur est admin (utilise la session admin)
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized access'}), 403

    try:
        data = request.get_json()
        new_status = data.get('status')

        if not new_status or new_status not in ['active', 'archived']:
            return jsonify({'error': 'Invalid or missing status parameter'}), 400

        conversation = None
        conv_model = None

        if platform == 'web':
            conv_model = Conversation
            conversation = Conversation.query.get(conv_id)
        elif platform == 'telegram':
             conv_model = TelegramConversation
             conversation = TelegramConversation.query.get(conv_id)
        #elif platform == 'whatsapp':
        #    # Logique future pour archiver un thread WhatsApp si implémenté
        #    pass
        else:
             return jsonify({'error': 'Platform not supported for status change'}), 400

        if not conversation:
            return jsonify({'error': 'Conversation not found'}), 404

        # Vérifier si la colonne status existe (elle devrait après la migration)
        if not hasattr(conversation, 'status'):
             logger.error(f"Tentative de mise à jour du statut mais colonne 'status' manquante pour {platform} conversation {conv_id}")
             return jsonify({'error': f"Status column missing for this platform type"}), 500

        conversation.status = new_status
        conversation.updated_at = datetime.utcnow() # Mettre à jour aussi updated_at
        db.session.commit()

        logger.info(f"Statut de la conversation {platform} ID {conv_id} mis à jour à '{new_status}'")
        return jsonify({'success': True, 'message': 'Conversation status updated successfully'})

    except Exception as e:
        db.session.rollback()
        app.logger.exception(f"Error updating status for conversation {conv_id} on {platform}: {e}")
        return jsonify({'error': 'Internal server error during status update'}), 500

@socketio.on('rename_conversation')
def handle_rename(data):
    try:
        conversation = Conversation.query.get(data['id'])
        if conversation:
            conversation.title = data['title']
            db.session.commit()
            # Include the title and id in the emit event to allow header title update
            emit('conversation_updated', {
                'success': True, 
                'title': conversation.title,
                'id': conversation.id
            })
    except Exception as e:
        emit('conversation_updated', {'success': False, 'error': str(e)})


@socketio.on('delete_conversation')
def handle_delete(data):
    try:
        conversation = Conversation.query.get(data['id'])
        if conversation:
            # Delete associated messages first
            Message.query.filter_by(conversation_id=conversation.id).delete()
            db.session.delete(conversation)
            db.session.commit()
            emit('conversation_deleted', {'success': True})
    except Exception as e:
        emit('conversation_deleted', {'success': False, 'error': str(e)})


# Modification complète de cette section du code pour corriger le bug
@socketio.on('open_conversation')
def handle_open_conversation(data):
    try:
        # Si ce n'est pas une conversation WhatsApp ou Telegram, c'est une conversation web normale
        conversation = Conversation.query.get(data['id'])
        if conversation:
            # Update session with the opened conversation
            session['thread_id'] = conversation.thread_id

            # Get messages for this conversation
            messages = Message.query.filter_by(
                conversation_id=conversation.id).order_by(
                    Message.created_at).all()
            messages_data = []

            # Import needed for current_user
            from flask_login import current_user
            user_id = current_user.id if current_user.is_authenticated else None

            for msg in messages:
                # Filtrer le contenu pour supprimer le texte extrait par Mathpix
                filtered_content = msg.content

                # Seulement pour les messages utilisateur qui contiennent du texte extrait
                if msg.role == 'user' and '[Extracted Image Content]' in filtered_content:
                    # Ne garder que la partie avant le texte extrait
                    filtered_content = filtered_content.split(
                        '[Extracted Image Content]')[0].strip()

                    # Si le message ne contient que le texte extrait (donc vide maintenant)
                    if not filtered_content and msg.image_url:
                        filtered_content = ""  # Message vide car l'image sera affichée

                # Add base message data
                message_data = {
                    'id': msg.id,  # Include message ID for feedback tracking
                    'role': msg.role,
                    'content': filtered_content,  # Utiliser le contenu filtré
                    'image_url': msg.image_url,
                }

                # If it's an assistant message, check for existing feedback
                if msg.role == 'assistant':
                    # Get existing feedback for this message from the current user
                    feedback = MessageFeedback.query.filter_by(
                        message_id=msg.id, user_id=user_id).first()

                    if feedback:
                        message_data['feedback'] = feedback.feedback_type

                messages_data.append(message_data)

            emit(
                'conversation_opened', {
                    'success':
                    True,
                    'messages':
                    messages_data,
                    'conversation_id':
                    conversation.id,
                    'thread_id':
                    conversation.thread_id,
                    'title':
                    conversation.title or
                    f"Conversation du {conversation.created_at.strftime('%d/%m/%Y')}"
                })
        else:
            emit('conversation_opened', {
                'success': False,
                'error': 'Conversation introuvable'
            })
    except Exception as e:
        app.logger.error(f"Error opening conversation: {str(e)}")
        emit('conversation_opened', {'success': False, 'error': str(e)})


@socketio.on('clear_session')
def handle_clear_session():
    try:
        logger.info("L'utilisateur a demandé une nouvelle conversation")

        # Supprimer l'ancien thread_id de la session
        session.pop('thread_id', None)

        # Ne pas créer de conversation - simplement notifier que la session est effacée
        emit('session_cleared', {'success': True})

        logger.info("Session effacée - aucune conversation créée à ce stade")
    except Exception as e:
        logger.error(
            f"Erreur lors de l'effacement de la session: {str(e)}"
        )
        emit('session_cleared', {'success': False, 'error': str(e)})


@socketio.on('restore_session')
def handle_restore_session(data):
    """Restore a previous session based on a stored thread_id"""
    logger.info(f"--- handle_restore_session called with data: {data}")
    try:
        thread_id = data.get('thread_id')
        user_id_from_js = data.get('user_id')
        logger.info(f"--- Trying to restore using thread_id: {thread_id} (JS User ID: {user_id_from_js})")
        conversation = None

        if thread_id:
            logger.info(
                f"Attempting to restore session with thread_id: {thread_id}")
            # Vérifier si la conversation existe avec le thread_id correct
            conversation = Conversation.query.filter_by(thread_id=thread_id).first()
            logger.info(f"--- DB Query Result for thread_id {thread_id}: {conversation}")

            # Vérifier si la conversation appartient à l'utilisateur actuel
            if conversation and current_user.is_authenticated and conversation.user_id == current_user.id:
                logger.info(f"--- Ownership check PASSED for user {current_user.id} and conversation user {conversation.user_id}")
                # Vérifier l'existence du thread chez OpenAI si nécessaire
                ai_client = get_ai_client()
                valid_openai_thread = True
                if CURRENT_MODEL == 'openai':
                    try:
                         ai_client.beta.threads.retrieve(thread_id=thread_id)
                         logger.info(f"Thread OpenAI {thread_id} confirmé existant pour restauration.")
                    except Exception as e:
                         logger.warning(f"Thread OpenAI {thread_id} introuvable ou invalide pour restauration: {str(e)}.")
                         valid_openai_thread = False
                         logger.warning(f"--- Ownership check FAILED for user {current_user.id} vs conversation user {conversation.user_id}")
                         conversation = None # Ne pas restaurer si le thread distant n'existe plus
                         session.pop('thread_id', None) # Nettoyer la session Flask si l'ID était invalide

                # Si on arrive ici, la restauration a échoué ou aucun thread_id n'a été fourni
                if not conversation:
                     logger.warning(f"--- Restore session FAILED. No valid conversation found or validated for thread_id: {thread_id}")
                     session.pop('thread_id', None) # S'assurer que la session est propre

                if valid_openai_thread and conversation:
                     # Mettre à jour la session Flask UNIQUEMENT si tout est valide
                     logger.info(f"--- Preparing to restore session for valid thread_id: {conversation.thread_id}")
                     session['thread_id'] = conversation.thread_id
                     logger.info(f"--- Flask session 'thread_id' UPDATED to: {session.get('thread_id')}")
                     logger.info(
                         f"Session restored for thread_id: {conversation.thread_id}"
                     )
                     # Émettre les messages de la conversation restaurée (logique existante)
                     messages = Message.query.filter_by(
                         conversation_id=conversation.id).order_by(
                             Message.created_at).all()
                     messages_data = []
                     for msg in messages:
                         # ... (formatage des messages comme dans votre code existant) ...
                         message_data = { 'id': msg.id, 'role': msg.role, 'content': msg.content, 'image_url': msg.image_url } # Simplifié
                         messages_data.append(message_data)
                     emit(
                         'conversation_opened', {
                             'success': True,
                             'messages': messages_data,
                             'conversation_id': conversation.id,
                             'thread_id': conversation.thread_id,
                             'title': conversation.title or f"Conversation du {conversation.created_at.strftime('%d/%m/%Y')}"
                         })
                     # Mettre à jour la date de dernière modification
                     conversation.updated_at = datetime.utcnow()
                     db.session.commit()
                     return # Important: sortir si la restauration a réussi
                # Mettre à jour la session Flask avec le thread_id
                session['thread_id'] = conversation.thread_id
                logger.info(
                    f"Session restored for thread_id: {conversation.thread_id}"
                )
        else:
            # Pas de conversation trouvée, ni par thread_id, ni récente
            if thread_id:
                logger.warning(
                    f"Conversation with id {thread_id} not found for session restoration"
                )
            else:
                logger.warning(
                    f"No existing conversation found for current user")
    except Exception as e:
        logger.error(f"Error in handle_restore_session: {str(e)}")
        logger.error(f"Error restoring session: {str(e)}")


@socketio.on('submit_feedback')
def handle_feedback(data):
    """Handle feedback submission for a message"""
    try:
        message_id = data.get('message_id')
        feedback_type = data.get('feedback_type')

        # Utiliser current_user de Flask-Login si l'utilisateur est authentifié
        from flask_login import current_user
        user_id = current_user.id if current_user.is_authenticated else None

        if not message_id or not feedback_type:
            emit('feedback_submitted', {
                'success': False,
                'error': 'Missing required parameters'
            })
            return

        if feedback_type not in ['positive', 'negative']:
            emit('feedback_submitted', {
                'success': False,
                'error': 'Invalid feedback type'
            })
            return

        with db_retry_session(
        ) as db_session:  # Renommer pour éviter la confusion
            # Check if this user already gave feedback on this message
            existing_feedback = MessageFeedback.query.filter_by(
                message_id=message_id, user_id=user_id).first()

            if existing_feedback:
                # Update existing feedback
                existing_feedback.feedback_type = feedback_type
                db_session.commit()
            else:
                # Create new feedback entry
                new_feedback = MessageFeedback(message_id=message_id,
                                               user_id=user_id,
                                               feedback_type=feedback_type)
                db_session.add(new_feedback)
                db_session.commit()

            # Émettre le succès à l'utilisateur qui a soumis le feedback
            emit('feedback_submitted', {'success': True})

            # Calculer les nouvelles statistiques de satisfaction
            total_feedbacks = MessageFeedback.query.count()
            positive_feedbacks = MessageFeedback.query.filter_by(
                feedback_type='positive').count()
            satisfaction_rate = round((positive_feedbacks / total_feedbacks) *
                                      100) if total_feedbacks > 0 else 0

            # Émettre la mise à jour à tous les clients connectés (y compris le tableau de bord admin)
            socketio.emit(
                'feedback_stats_updated', {
                    'satisfaction_rate': satisfaction_rate,
                    'total_feedbacks': total_feedbacks,
                    'positive_feedbacks': positive_feedbacks
                })
    except Exception as e:
        logger.error(f"Error submitting feedback: {str(e)}")
        emit('feedback_submitted', {'success': False, 'error': str(e)})


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_base64_image(base64_string):
    # Extract image type and data
    header, encoded = base64_string.split(",", 1)

    # Generate a unique filename
    filename = f"{uuid.uuid4()}.jpg"

    # Decode the image
    img_data = base64.b64decode(encoded)

    # Save the image
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    with open(filepath, "wb") as f:
        f.write(img_data)

    return filename


def cleanup_uploads():
    """Cleans up the uploads folder of old images and checks the total size"""
    try:
        # Delete files older than IMAGE_MAX_AGE_HOURS
        current_time = datetime.now()
        for filename in os.listdir(UPLOAD_FOLDER):
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
            if current_time - file_modified > timedelta(
                    hours=IMAGE_MAX_AGE_HOURS):
                os.remove(filepath)

        # Check the total size of the folder
        total_size = sum(
            os.path.getsize(os.path.join(UPLOAD_FOLDER, f))
            for f in os.listdir(UPLOAD_FOLDER))

        # If the size exceeds the limit, delete the oldest files
        if total_size > MAX_UPLOAD_FOLDER_SIZE:
            files = [(os.path.join(UPLOAD_FOLDER, f),
                      os.path.getmtime(os.path.join(UPLOAD_FOLDER, f)))
                     for f in os.listdir(UPLOAD_FOLDER)]
            files.sort(key=lambda x: x[1])  # Sort by modification date

            for filepath, _ in files:
                os.remove(filepath)
                total_size = sum(
                    os.path.getsize(os.path.join(UPLOAD_FOLDER, f))
                    for f in os.listdir(UPLOAD_FOLDER))
                if total_size <= MAX_UPLOAD_FOLDER_SIZE:
                    break

    except Exception as e:
        print(f"Error during upload cleanup: {str(e)}")


@socketio.on('heartbeat')
def handle_heartbeat():
    """Simple heartbeat to keep the connection alive"""
    # Vérifier si un thread_id est dans la session
    thread_id = session.get('thread_id')
    if thread_id:
        # Mettre à jour le timestamp de la conversation pour la garder active
        try:
            with db_retry_session() as db_session:
                conversation = Conversation.query.filter_by(thread_id=thread_id).first()
                if conversation:
                    conversation.updated_at = datetime.utcnow()
                    db_session.commit()
        except Exception as e:
            logger.warning(f"Error updating conversation timestamp during heartbeat: {str(e)}")

    # Retourner un simple ACK
    return {'status': 'ok'}


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_mode = request.form.get('login_mode', 'web')

        if login_mode == 'web' or login_mode == 'whatsapp':
            # Nettoyer les données Telegram de la session
            session.pop('is_telegram_user', None)
            session.pop('telegram_id', None)

            phone_number = request.form.get('phone_number')
            password = request.form.get('password')

            # S'assurer que le numéro commence par +225 si ce n'est pas déjà le cas
            if not phone_number.startswith('+'):
                phone_number = '+225' + phone_number

            # Vérifier le format du numéro de téléphone
            if not phone_number.startswith('+225') or len(
                    phone_number) != 12 or not phone_number[1:].isdigit():
                flash(
                    'Le numéro de téléphone doit être au format +22500000000.',
                    'error')
                return redirect(url_for('login'))

            # Check for admin credentials first
            if phone_number == os.environ.get('ADMIN_PHONE') and \
               password == os.environ.get('ADMIN_PASSWORD'):
                session['is_admin'] = True
                flash('Connecté en tant qu\'administrateur.', 'success')
                return redirect(url_for('admin_dashboard'))

            # Vérifier si le numéro existe quelque part dans la base de données
            if not phone_number_exists(phone_number):
                # Rediriger avec paramètre d'erreur "no_account"
                return redirect(url_for('login', error='no_account'))

            # Normaliser le numéro en supprimant le + pour les formats spéciaux
            normalized_number = phone_number.replace('+', '')

            # Traitement spécifique pour login WhatsApp
            if login_mode == 'whatsapp':
                # Vérifier si un utilisateur web "normal" existe avec ce numéro
                web_user = User.query.filter_by(
                    phone_number=phone_number).first()

                # Vérifier si un utilisateur Telegram existe avec ce numéro
                telegram_user = TelegramUser.query.filter(
                    TelegramUser.phone_number != "---",
                    TelegramUser.phone_number == phone_number).first()

                # Si l'utilisateur existe dans la base de données web ou Telegram, afficher un message approprié
                if web_user:
                    # Rediriger avec un paramètre spécial pour afficher le modal indiquant que c'est un compte web
                    return redirect(
                        url_for('login',
                                error='web_account',
                                phone=phone_number))

                if telegram_user:
                    # Rediriger avec un paramètre spécial pour afficher le modal indiquant que c'est un compte Telegram
                    return redirect(
                        url_for('login',
                                error='telegram_account',
                                phone=phone_number))

                # Si l'utilisateur n'existe pas en tant que compte web ou Telegram, continuer avec la logique WhatsApp
                # Vérifier si un utilisateur web existe déjà pour ce numéro avec préfixe WhatsApp
                user = User.query.filter_by(
                    phone_number=f"whatsapp_{normalized_number}").first()

                if not user:
                    # Vérifier si le numéro existe dans les messages WhatsApp
                    whatsapp_message = WhatsAppMessage.query.filter_by(
                        from_number=normalized_number).first()

                    if not whatsapp_message:
                        # Pas de message WhatsApp trouvé pour ce numéro
                        flash('Aucun compte WhatsApp trouvé avec ce numéro.',
                              'error')
                        return redirect(
                            url_for('login', error='no_whatsapp_account'))

                    # Créer un nouvel utilisateur web pour ce numéro WhatsApp
                    user = User(
                        first_name="WhatsApp",
                        last_name="User",
                        age=18,  # Valeur par défaut
                        phone_number=
                        f"whatsapp_{normalized_number}",  # Format spécial pour identifier les utilisateurs WhatsApp
                        study_level="Non spécifié",
                        grade_goals="average"  # Valeur par défaut
                    )
                    # Définir le mot de passe entré
                    user.set_password(password)

                    db.session.add(user)
                    db.session.commit()

                    # Émettre l'événement de nouvel utilisateur Web pour le tableau de bord
                    socketio.emit(
                        'new_web_user', {
                            'id': user.id,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'phone_number': user.phone_number
                        })
                else:
                    # Si l'utilisateur existe, vérifier le mot de passe
                    if not user.check_password(password):
                        return redirect(
                            url_for('login', error='wrong_password'))

                # Définir les variables de session pour indiquer une connexion via WhatsApp
                session['is_whatsapp_user'] = True
                session['whatsapp_number'] = normalized_number

                # Connecter l'utilisateur et rediriger vers le chat
                login_user(user)
                flash('Connecté via WhatsApp avec succès!', 'success')
                return redirect(url_for('chat'))

            # Logique pour login Web standard - vérifier tous les types d'utilisateurs
            # D'abord essayer de trouver un utilisateur web standard
            user = User.query.filter_by(phone_number=phone_number).first()

            if not user:
                # Vérifier s'il existe un message WhatsApp pour ce numéro
                whatsapp_message = WhatsAppMessage.query.filter_by(
                    from_number=normalized_number).first()
                if whatsapp_message:
                    # Rediriger vers login avec paramètre d'erreur 'whatsapp_account'
                    return redirect(
                        url_for('login',
                                error='whatsapp_account',
                                phone=phone_number))

                # Vérifier s'il existe un utilisateur WhatsApp pour ce numéro
                whatsapp_user = User.query.filter_by(
                    phone_number=f"whatsapp_{normalized_number}").first()
                if whatsapp_user:
                    # Rediriger vers login avec paramètre d'erreur 'whatsapp_account'
                    return redirect(
                        url_for('login',
                                error='whatsapp_account',
                                phone=phone_number))

                # Si aucun compte WhatsApp, vérifier Telegram
                telegram_user = TelegramUser.query.filter(
                    TelegramUser.phone_number != "---",
                    TelegramUser.phone_number == phone_number).first()

                if telegram_user:
                    # Obtenir ou créer un utilisateur Web associé à ce TelegramUser
                    user = get_or_create_web_user_for_telegram(telegram_user)
                    session['is_telegram_user'] = True
                    session['telegram_id'] = telegram_user.telegram_id
                else:
                    # Si aucun utilisateur trouvé, rediriger avec erreur
                    return redirect(url_for('login', error='no_account'))
            else:
                # Si l'utilisateur est un utilisateur web standard
                session.pop('is_whatsapp_user', None)
                session.pop('whatsapp_number', None)
                session.pop('is_telegram_user', None)
                session.pop('telegram_id', None)

            # Vérifier si le mot de passe est correct
            if not user.check_password(password):
                # Rediriger avec paramètre d'erreur "wrong_password"
                return redirect(url_for('login', error='wrong_password'))

            # Si tout est correct, connecter l'utilisateur
            login_user(user)
            return redirect(url_for('chat'))

        elif login_mode == 'telegram':
            # Récupérer l'ID Telegram et le numéro de téléphone
            telegram_id = request.form.get('telegram_id')
            telegram_phone = request.form.get('telegram_phone')

            # Validation de l'ID Telegram
            if not telegram_id or not telegram_id.strip().isdigit():
                flash('Veuillez entrer un ID Telegram valide (numérique).',
                      'error')
                return redirect(url_for('login'))

            # Validation du numéro de téléphone
            if not telegram_phone:
                flash('Veuillez entrer un numéro de téléphone.', 'error')
                return redirect(url_for('login'))

            # S'assurer que le numéro commence par +225 si ce n'est pas déjà le cas
            if not telegram_phone.startswith('+'):
                telegram_phone = '+225' + telegram_phone

            # Vérifier le format du numéro
            if not telegram_phone.startswith('+225') or len(
                    telegram_phone) != 12 or not telegram_phone[1:].isdigit():
                flash(
                    'Le numéro de téléphone doit être au format +22500000000.',
                    'error')
                return redirect(url_for('login'))

            # Convertir en entier
            telegram_id = int(telegram_id)

            # Vérifier si cet ID existe dans la base de données
            telegram_user = TelegramUser.query.get(telegram_id)

            if not telegram_user:
                flash('Aucun compte Telegram trouvé avec cet ID.', 'error')
                return redirect(url_for('login'))

            # Mettre à jour le numéro de téléphone de l'utilisateur Telegram s'il n'en a pas encore
            if telegram_user.phone_number == "---":
                telegram_user.phone_number = telegram_phone
                db.session.commit()

            # Obtenir ou créer un utilisateur Web associé à cet utilisateur Telegram
            user = get_or_create_web_user_for_telegram(telegram_user)

            # Connecter l'utilisateur
            login_user(user)

            # Définir des variables de session pour indiquer une connexion via Telegram
            session['is_telegram_user'] = True
            session['telegram_id'] = telegram_id

            flash('Connecté via Telegram avec succès!', 'success')
            return redirect(url_for('chat'))

        flash('Identifiants de connexion incorrects.', 'error')
        return redirect(url_for('login'))

    return render_template('login.html')

def get_or_create_web_user_for_telegram(telegram_user):
    """Crée ou récupère un User associé à un TelegramUser pour l'authentification Flask-Login"""
    # Vérifier si un User existe déjà pour cet ID Telegram
    user = User.query.filter_by(
        phone_number=f"telegram_{telegram_user.telegram_id}").first()

    if not user:
        # Créer un nouvel utilisateur Web lié à ce TelegramUser
        user = User(
            first_name=telegram_user.first_name
            if telegram_user.first_name != "---" else "Telegram",
            last_name=telegram_user.last_name
            if telegram_user.last_name != "---" else "User",
            age=18,  # Valeur par défaut
            phone_number=
            f"telegram_{telegram_user.telegram_id}",  # Format spécial pour identifier les utilisateurs Telegram
            study_level=telegram_user.study_level
            if telegram_user.study_level != "---" else "Non spécifié",
            grade_goals="average"  # Valeur par défaut
        )
        # Définir un mot de passe aléatoire (ne sera pas utilisé car l'authentification se fait par ID Telegram)
        user.set_password(str(uuid.uuid4()))

        db.session.add(user)
        db.session.commit()

        # Associer le vrai numéro de téléphone au TelegramUser pour les requêtes futures
        logger.info(
            f"Nouvel utilisateur Telegram créé avec ID {telegram_user.telegram_id} et numéro {telegram_user.phone_number}"
        )

    return user


@app.route('/logout')
@login_required
def logout():
    """Logout route for all users"""
    # Nettoyer toutes les données de session pertinentes
    session.pop('is_telegram_user', None)
    session.pop('telegram_id', None)
    session.pop('thread_id', None)
    session.pop('is_admin', None)
    logout_user()  # Fonction de Flask-Login pour déconnecter l'utilisateur
    flash('Vous avez été déconnecté.', 'success')
    return redirect(url_for('login'))

@app.route('/refresh_session', methods=['POST'])
def refresh_session():
    """Endpoint pour maintenir la session active"""
    # Simplement renvoyer un succès pour maintenir la session
    return jsonify({'success': True})


@app.route('/admin')
def admin_dashboard():
    """Admin dashboard route that displays platform statistics"""
    # Check if user is admin
    if not session.get('is_admin'):
        flash(
            'Accès non autorisé. Veuillez vous connecter en tant qu\'administrateur.',
            'error')
        return redirect(url_for('login'))

    try:
        # Get web platform data
        users = User.query.all()
        conversations = Conversation.query.all()
        today = datetime.today().date()

        # Count today's conversations
        today_conversations = sum(1 for conv in conversations
                                  if conv.created_at.date() == today)

        # Get actual number of users
        active_users = len(users)
        # Count users created today
        active_users_today = sum(1 for user in users
                                 if user.created_at.date() == today)

        # Calculate satisfaction rate based on message feedback
        total_feedbacks = MessageFeedback.query.count()
        positive_feedbacks = MessageFeedback.query.filter_by(
            feedback_type='positive').count()

        # Calculate satisfaction rate (percentage of positive feedback)
        satisfaction_rate = round((positive_feedbacks / total_feedbacks) *
                                  100) if total_feedbacks > 0 else 0

        # Get OpenAI Assistant ID for settings
        openai_assistant_id = os.environ.get('OPENAI_ASSISTANT_ID',
                                             'Non configuré')

        return render_template(
            'admin_dashboard.html',
            active_users=active_users,
            active_users_today=active_users_today,
            today_conversations=today_conversations,
            satisfaction_rate=satisfaction_rate,
            is_admin=True,
            openai_assistant_id=openai_assistant_id,  # Add OpenAI Assistant ID
            current_model=CURRENT_MODEL,  # Add current model selection
            deepseek_instructions=
            DEEPSEEK_INSTRUCTIONS,  # Add DeepSeek instructions
            deepseek_reasoner_instructions=
            DEEPSEEK_REASONER_INSTRUCTIONS,  # Add DeepSeek Reasoner instructions
            qwen_instructions=QWEN_INSTRUCTIONS,  # Add Qwen instructions
            gemini_instructions=GEMINI_INSTRUCTIONS  # Add Gemini instructions
        )
    except Exception as e:
        logger.error(f"Error in admin dashboard: {str(e)}")
        flash('Une erreur est survenue lors du chargement du tableau de bord.',
              'error')
        return redirect(url_for('login'))


def reload_model_settings():
    """
    Recharge les paramètres du modèle depuis l'environnement et les sauvegarde dans un fichier JSON.
    """
    global CURRENT_MODEL, DEEPSEEK_INSTRUCTIONS, DEEPSEEK_REASONER_INSTRUCTIONS, QWEN_INSTRUCTIONS, GEMINI_INSTRUCTIONS

    # Recharger le modèle depuis l'environnement
    CURRENT_MODEL = os.environ.get('CURRENT_MODEL', 'openai')

    # Charger les instructions depuis les fichiers
    DEEPSEEK_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('DEEPSEEK_INSTRUCTIONS_FILE',
                       'instructions/deepseek.txt'),
        'You are a helpful educational assistant')
    DEEPSEEK_REASONER_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('DEEPSEEK_REASONER_INSTRUCTIONS_FILE',
                       'instructions/deepseek_reasoner.txt'),
        'You are a helpful educational assistant focused on reasoning')
    QWEN_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('QWEN_INSTRUCTIONS_FILE', 'instructions/qwen.txt'),
        'You are a helpful educational assistant')
    GEMINI_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('GEMINI_INSTRUCTIONS_FILE', 'instructions/gemini.txt'),
        'You are a helpful educational assistant')

    # Utiliser un chemin absolu pour le fichier de configuration
    config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'ai_config.json')

    # Sauvegarde des configurations dans un fichier JSON
    config_data = {
        'timestamp': time.time(),
        'CURRENT_MODEL': CURRENT_MODEL,
        'DEEPSEEK_INSTRUCTIONS': DEEPSEEK_INSTRUCTIONS,
        'DEEPSEEK_REASONER_INSTRUCTIONS': DEEPSEEK_REASONER_INSTRUCTIONS,
        'QWEN_INSTRUCTIONS': QWEN_INSTRUCTIONS,
        'GEMINI_INSTRUCTIONS': GEMINI_INSTRUCTIONS
    }

    try:
        with open(config_file_path, 'w') as f:
            json.dump(config_data, f)

        # S'assurer que le fichier a les permissions correctes
        os.chmod(config_file_path, 0o666)  # rw-rw-rw-

        logger.info(
            f"AI model settings saved to {config_file_path}: {CURRENT_MODEL}")
    except Exception as e:
        logger.error(
            f"Error saving AI model settings to file ({config_file_path}): {str(e)}"
        )


@app.route('/admin/settings/model', methods=['POST'])
def update_model_settings():
    """Update AI model settings"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        data = request.get_json()
        model = data.get('model')
        instructions = data.get('instructions')

        if model not in [
                'openai', 'deepseek', 'deepseek-reasoner', 'qwen', 'gemini'
        ]:
            return jsonify({'error': 'Invalid model selection'}), 400

        # Update the current model
        global CURRENT_MODEL, DEEPSEEK_INSTRUCTIONS, DEEPSEEK_REASONER_INSTRUCTIONS, QWEN_INSTRUCTIONS, GEMINI_INSTRUCTIONS
        CURRENT_MODEL = model

        # Update environment variables for persistence
        os.environ['CURRENT_MODEL'] = model

        # Ensure instructions directory exists
        os.makedirs('instructions', exist_ok=True)

        # Update instructions based on model
        if model == 'deepseek' and instructions:
            DEEPSEEK_INSTRUCTIONS = instructions
            with open('instructions/deepseek.txt', 'w', encoding='utf-8') as f:
                f.write(instructions)
        elif model == 'deepseek-reasoner' and instructions:
            DEEPSEEK_REASONER_INSTRUCTIONS = instructions
            with open('instructions/deepseek_reasoner.txt',
                      'w',
                      encoding='utf-8') as f:
                f.write(instructions)
        elif model == 'qwen' and instructions:
            QWEN_INSTRUCTIONS = instructions
            with open('instructions/qwen.txt', 'w', encoding='utf-8') as f:
                f.write(instructions)
        elif model == 'gemini' and instructions:
            GEMINI_INSTRUCTIONS = instructions
            with open('instructions/gemini.txt', 'w', encoding='utf-8') as f:
                f.write(instructions)

        # Update .env with only the model selection
        env_path = '.env'
        env_vars = {}

        # Read existing variables
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        env_vars[key] = value

        # Update with new model value
        env_vars['CURRENT_MODEL'] = model

        # Set file paths in env vars
        env_vars['DEEPSEEK_INSTRUCTIONS_FILE'] = 'instructions/deepseek.txt'
        env_vars[
            'DEEPSEEK_REASONER_INSTRUCTIONS_FILE'] = 'instructions/deepseek_reasoner.txt'
        env_vars['QWEN_INSTRUCTIONS_FILE'] = 'instructions/qwen.txt'
        env_vars['GEMINI_INSTRUCTIONS_FILE'] = 'instructions/gemini.txt'

        # Write back to .env
        with open(env_path, 'w') as f:
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")

        # Reload environment variables
        load_dotenv()

        # Recharger les paramètres du modèle
        reload_model_settings()

        return jsonify({
            'success': True,
            'message': 'Model settings updated successfully'
        })
    except Exception as e:
        logger.error(f"Error updating model settings: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


if 'RUN_TELEGRAM_BOT' not in os.environ:
    os.environ['RUN_TELEGRAM_BOT'] = 'true'
    logger.info("Enabled Telegram bot (RUN_TELEGRAM_BOT=true)")

    # Mettre à jour .env également
    env_path = '.env'
    env_vars = {}

    # Lire les variables existantes
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    env_vars[key] = value

    # Mettre à jour avec la nouvelle valeur
    env_vars['RUN_TELEGRAM_BOT'] = 'true'

    # Écrire dans .env
    with open(env_path, 'w') as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")


@app.route('/admin/logout')
def admin_logout():
    """Logout route for admin"""
    session.pop('is_admin', None)
    flash('Vous avez été déconnecté.', 'success')
    return redirect(url_for('login'))


# Fonction utilitaire pour vérifier si un numéro de téléphone existe déjà
def phone_number_exists(phone_number):
    """
    Vérifie si un numéro de téléphone existe déjà dans la base de données
    en cherchant parmi tous les types d'utilisateurs (web, WhatsApp, Telegram)
    """
    # Normaliser le numéro de téléphone en supprimant le '+' du début si présent
    normalized_number = phone_number.replace('+', '')

    # Vérifier dans les utilisateurs web
    web_user = User.query.filter_by(phone_number=phone_number).first()
    if web_user:
        return True

    # Vérifier dans les utilisateurs web avec préfixe WhatsApp
    whatsapp_user = User.query.filter_by(
        phone_number=f"whatsapp_{normalized_number}").first()
    if whatsapp_user:
        return True

    # Vérifier dans les messages WhatsApp
    whatsapp_message = WhatsAppMessage.query.filter_by(
        from_number=normalized_number).first()
    if whatsapp_message:
        return True

    # Vérifier dans les utilisateurs Telegram avec un numéro de téléphone
    telegram_user = TelegramUser.query.filter(
        TelegramUser.phone_number != "---",
        TelegramUser.phone_number == phone_number).first()
    if telegram_user:
        return True

    return False


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Nettoyer les données Telegram de la session pour les nouveaux utilisateurs
        session.pop('is_telegram_user', None)
        session.pop('telegram_id', None)
        session.pop('thread_id', None)

        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        age = request.form.get('age')
        phone_number = request.form.get('phone_number')
        password = request.form.get('password')
        study_level = request.form.get(
            'study_level') or 'Terminal A'  # Default value
        grade_goals = request.form.get(
            'grade_goals') or 'average'  # Default value

        # Basic validation
        if not all([first_name, last_name, age, phone_number, password]):
            flash('Tous les champs obligatoires doivent être remplis.',
                  'error')
            return redirect(url_for('register'))

        # Vérifier le format du numéro de téléphone (doit commencer par +225 suivi de 8 chiffres)
        if not phone_number.startswith('+225') or len(
                phone_number) != 12 or not phone_number[1:].isdigit():
            flash('Le numéro de téléphone doit être au format +22500000000.',
                  'error')
            return redirect(url_for('register'))

        # Vérifier si le numéro existe déjà
        if phone_number_exists(phone_number):
            flash('Ce numéro de téléphone est déjà utilisé.', 'error')
            # Rediriger avec un paramètre pour afficher la modal
            return redirect(url_for('register', error='phone_exists'))

        try:
            # Create new user
            user = User(first_name=first_name,
                        last_name=last_name,
                        age=int(age),
                        phone_number=phone_number,
                        study_level=study_level,
                        grade_goals=grade_goals)
            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            # Émettre l'événement de nouvel utilisateur Web pour le tableau de bord
            socketio.emit(
                'new_web_user', {
                    'id': user.id,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'phone_number': user.phone_number
                })

            # Log the user in
            login_user(user)
            return redirect(url_for('chat'))

        except Exception as e:
            db.session.rollback()
            flash('Une erreur est survenue lors de l\'inscription.', 'error')
            app.logger.error(f"Registration error: {str(e)}")
            return redirect(url_for('register'))

    # Vérifier s'il y a un paramètre d'erreur pour afficher la modal
    error = request.args.get('error')
    return render_template('register.html', error=error)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        account_type = request.form.get('account_type', 'web')
        phone_number = request.form.get('phone_number')
        new_password = request.form.get('new_password')

        if not new_password:
            flash('Veuillez entrer un nouveau mot de passe.', 'error')
            return redirect(url_for('forgot_password'))

        user = None

        if account_type == 'whatsapp':
            # Formater le numéro pour correspondre au format WhatsApp
            if phone_number.startswith('+'):
                whatsapp_number = phone_number[1:]  # Enlever le + si présent
            else:
                whatsapp_number = phone_number

            # Rechercher l'utilisateur avec le préfixe whatsapp_
            user = User.query.filter_by(
                phone_number=f"whatsapp_{whatsapp_number}").first()

            # Si l'utilisateur n'existe pas, vérifier s'il y a des messages WhatsApp pour ce numéro
            if not user:
                whatsapp_message = WhatsAppMessage.query.filter_by(
                    from_number=whatsapp_number).first()

                if whatsapp_message:
                    # Créer un nouvel utilisateur pour ce numéro WhatsApp
                    user = User(
                        first_name="WhatsApp",
                        last_name="User",
                        age=18,  # Valeur par défaut
                        phone_number=f"whatsapp_{whatsapp_number}",
                        study_level="Non spécifié",
                        grade_goals="average"  # Valeur par défaut
                    )
                    db.session.add(user)
                    logger.info(
                        f"Nouvel utilisateur WhatsApp créé lors de la réinitialisation du mot de passe: {whatsapp_number}"
                    )
        else:
            # Recherche standard pour les utilisateurs web
            user = User.query.filter_by(phone_number=phone_number).first()

        if user:
            # Mettre à jour le mot de passe de l'utilisateur
            user.set_password(new_password)
            db.session.commit()
            logger.info(
                f"Mot de passe mis à jour pour l'utilisateur: {user.phone_number}"
            )

            # Passer un paramètre pour afficher le popup
            return render_template('forgot_password.html',
                                   password_updated=True)

        flash(
            f"Aucun compte {'WhatsApp' if account_type == 'whatsapp' else ''} trouvé avec ce numéro.",
            'error')
        return redirect(url_for('forgot_password'))

    return render_template('forgot_password.html')


@app.route('/admin/data/<platform>')
def admin_platform_data(platform):
    """
    Get data required ONLY for the main dashboard view:
    - Efficiently calculated statistics.
    - A small number (e.g., 5) of recent users.
    - A small number (e.g., 5) of recent conversations with last message fetched efficiently.
    """

    today_date = date.today()
    tomorrow_date = today_date + timedelta(days=1)
    data = {'platform': platform} # Initialisation
    RECENT_LIMIT = 5 # Nombre d'éléments récents à afficher sur le dashboard

    try:
        # --- Calcul des Statistiques (copié depuis /stats optimisé) ---
        if platform == 'web':
            active_users_count = db.session.query(func.count(User.id)).scalar() or 0
            today_users_count = db.session.query(func.count(User.id))\
                .filter(User.created_at >= today_date, User.created_at < tomorrow_date).scalar() or 0
            today_conversations_count = db.session.query(func.count(Conversation.id))\
                .filter(Conversation.created_at >= today_date, Conversation.created_at < tomorrow_date).scalar() or 0
            total_feedbacks = db.session.query(func.count(MessageFeedback.id)).scalar() or 0
            positive_feedbacks = db.session.query(func.count(MessageFeedback.id))\
                .filter(MessageFeedback.feedback_type == 'positive').scalar() or 0
            satisfaction_rate = round((positive_feedbacks / total_feedbacks) * 100) if total_feedbacks > 0 else 0

            data.update({
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': satisfaction_rate
            })

        elif platform == 'telegram':
            active_users_count = db.session.query(func.count(TelegramUser.telegram_id)).scalar() or 0
            today_users_count = db.session.query(func.count(TelegramUser.telegram_id))\
                .filter(TelegramUser.created_at >= today_date, TelegramUser.created_at < tomorrow_date).scalar() or 0
            today_conversations_count = db.session.query(func.count(TelegramConversation.id))\
                .filter(TelegramConversation.created_at >= today_date, TelegramConversation.created_at < tomorrow_date).scalar() or 0

            data.update({
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': 0
            })

        elif platform == 'whatsapp':
            active_users_count = db.session.query(func.count(func.distinct(WhatsAppMessage.from_number))).scalar() or 0
            today_users_count = db.session.query(func.count(func.distinct(WhatsAppMessage.from_number)))\
            .filter(WhatsAppMessage.timestamp >= today_date, WhatsAppMessage.timestamp < tomorrow_date).scalar() or 0
            subquery = db.session.query(
                WhatsAppMessage.thread_id,
                func.min(WhatsAppMessage.timestamp).label('first_message_time')
            ).group_by(WhatsAppMessage.thread_id).subquery()
            today_conversations_count = db.session.query(func.count(subquery.c.thread_id))\
            .filter(subquery.c.first_message_time >= today_date, subquery.c.first_message_time < tomorrow_date)\
            .scalar() or 0

            data.update({
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': 0
            })
        else:
             return jsonify({"error": "Platform not supported"}), 404

        # --- Récupération des Utilisateurs Récents (LIMIT 5) ---
        recent_users = []
        if platform == 'web':
            recent_users_query = User.query.order_by(User.created_at.desc()).limit(RECENT_LIMIT).all()
            recent_users = [{
                'first_name': user.first_name, 'last_name': user.last_name,
                'phone_number': user.phone_number, 'age': user.age,
                'study_level': user.study_level,
                'created_at': user.created_at.strftime('%d/%m/%Y')
            } for user in recent_users_query]
        elif platform == 'telegram':
             recent_users_query = TelegramUser.query.order_by(TelegramUser.created_at.desc()).limit(RECENT_LIMIT).all()
             recent_users = [{
                 'telegram_id': user.telegram_id, 'first_name': user.first_name or "---",
                 'last_name': user.last_name or "---", 'phone': user.phone_number,
                 'study_level': user.study_level,
                 'created_at': user.created_at.strftime('%d/%m/%Y')
             } for user in recent_users_query]
        elif platform == 'whatsapp':
             recent_user_numbers = db.session.query(WhatsAppMessage.from_number).distinct().limit(RECENT_LIMIT).all()
             recent_users = []
             for user_num_tuple in recent_user_numbers:
                 user_num = user_num_tuple[0]
                 first_msg = WhatsAppMessage.query.filter_by(from_number=user_num).order_by(WhatsAppMessage.timestamp).first()
                 recent_users.append({
                     'name': f'WhatsApp User {user_num}', 'phone': user_num,
                     'study_level': 'N/A',
                     'created_at': first_msg.timestamp.strftime('%d/%m/%Y') if first_msg else 'N/A'
                 })


        # --- Récupération des Conversations Récentes (LIMIT 5) + Last Message (Optimisé) ---
        recent_conversations = []
        latest_msgs_dict = {} # Pour stocker les derniers messages {id: content}

        if platform == 'web':
            recent_conversations_query = Conversation.query.order_by(Conversation.created_at.desc()).limit(RECENT_LIMIT).all()
            if recent_conversations_query:
                recent_conv_ids = [c.id for c in recent_conversations_query]
                # Récupérer le dernier message pour ces conversations spécifiques (Window Function)
                subq = db.session.query(
                    Message.conversation_id, Message.content,
                    func.row_number().over(
                        partition_by=Message.conversation_id,
                        order_by=desc(Message.created_at)
                    ).label('rn')
                ).filter(Message.conversation_id.in_(recent_conv_ids)).subquery()
                latest_msgs_q = db.session.query(subq.c.conversation_id, subq.c.content).filter(subq.c.rn == 1)
                latest_msgs_dict = dict(latest_msgs_q.all())

            recent_conversations = [{
                'id': conv.id, # Ajouter l'ID si utile pour le frontend
                'title': conv.title or "Sans titre",
                'date': conv.created_at.strftime('%d/%m/%Y'),
                'time': conv.created_at.strftime('%H:%M'),
                'last_message': latest_msgs_dict.get(conv.id, "No messages")
            } for conv in recent_conversations_query]

        elif platform == 'telegram':
            recent_conversations_query = TelegramConversation.query.order_by(TelegramConversation.created_at.desc()).limit(RECENT_LIMIT).all()
            if recent_conversations_query:
                recent_conv_ids = [c.id for c in recent_conversations_query]
                # Récupérer le dernier message pour ces conversations spécifiques
                subq = db.session.query(
                    TelegramMessage.conversation_id, TelegramMessage.content,
                    func.row_number().over(
                        partition_by=TelegramMessage.conversation_id,
                        order_by=desc(TelegramMessage.created_at)
                    ).label('rn')
                ).filter(TelegramMessage.conversation_id.in_(recent_conv_ids)).subquery()
                latest_msgs_q = db.session.query(subq.c.conversation_id, subq.c.content).filter(subq.c.rn == 1)
                latest_msgs_dict = dict(latest_msgs_q.all())

            recent_conversations = [{
                'id': conv.id, # Ajouter l'ID si utile pour le frontend
                'title': conv.title,
                'date': conv.created_at.strftime('%d/%m/%Y'),
                'time': conv.created_at.strftime('%H:%M'),
                'last_message': latest_msgs_dict.get(conv.id, "No messages")
            } for conv in recent_conversations_query]

        elif platform == 'whatsapp':
             # Récupérer les 5 conversations les plus récentes (basé sur le dernier message)
             subq_last_msg_time = db.session.query(
                 WhatsAppMessage.thread_id,
                 func.max(WhatsAppMessage.timestamp).label('last_msg_time')
             ).group_by(WhatsAppMessage.thread_id).subquery()

             recent_threads_q = db.session.query(subq_last_msg_time.c.thread_id, subq_last_msg_time.c.last_msg_time)\
                 .order_by(desc(subq_last_msg_time.c.last_msg_time))\
                 .limit(RECENT_LIMIT)

             recent_conversations_data = recent_threads_q.all() # [(thread_id, last_msg_time), ...]
             if recent_conversations_data:
                 recent_thread_ids = [c[0] for c in recent_conversations_data]
                 # Récupérer le dernier message pour ces threads spécifiques
                 subq_msg = db.session.query(
                     WhatsAppMessage.thread_id, WhatsAppMessage.content,
                     func.row_number().over(
                         partition_by=WhatsAppMessage.thread_id,
                         order_by=desc(WhatsAppMessage.timestamp)
                     ).label('rn')
                 ).filter(WhatsAppMessage.thread_id.in_(recent_thread_ids)).subquery()
                 latest_msgs_q = db.session.query(subq_msg.c.thread_id, subq_msg.c.content).filter(subq_msg.c.rn == 1)
                 latest_msgs_dict = dict(latest_msgs_q.all()) # {thread_id: content}

                 # Créer la liste JSON
                 recent_conversations = [{
                     'id': thread_id, # Utiliser thread_id comme ID pour WA
                     'title': f"Conversation {thread_id}",
                     'date': last_time.strftime('%d/%m/%Y'),
                     'time': last_time.strftime('%H:%M'),
                     'last_message': latest_msgs_dict.get(thread_id, "No messages")
                 } for thread_id, last_time in recent_conversations_data]


        # --- Assemblage final des données pour le dashboard ---
        data['users'] = recent_users
        data['conversations'] = recent_conversations

        return jsonify(data)

    except Exception as e:
        app.logger.error(f"Error fetching dashboard data for platform {platform}: {e}")
        return jsonify({"error": "Failed to retrieve dashboard data"}), 500

# --- ROUTE UTILISATEURS CORRIGÉE (PAGINATION + FILTRE (sans statut web/tg) + RECHERCHE) ---
@app.route('/admin/users/<platform>')
def admin_platform_users(platform):
    """Get a paginated list of users for a specific platform, with filtering and search."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status_filter = request.args.get('status', None, type=str) # 'active', 'inactive' ou None
        search_term = request.args.get('search', None, type=str)

        users_data = []
        pagination_data = {}
        base_query = None
        user_model = None
        last_active_column = None

        # Définir le seuil d'activité (ex: 15 minutes)
        activity_threshold = datetime.utcnow() - timedelta(seconds=900) # 15 minutes

        # 1. Construire la requête de base et identifier le modèle/colonne
        if platform == 'web':
            user_model = User
            base_query = User.query
            last_active_column = User.last_active # <-- Identifier la colonne
            search_fields = [User.first_name, User.last_name, User.phone_number]
        elif platform == 'telegram':
            user_model = TelegramUser
            base_query = TelegramUser.query
            last_active_column = TelegramUser.last_active # <-- Identifier la colonne
            search_fields = [TelegramUser.first_name, TelegramUser.last_name, TelegramUser.phone_number, TelegramUser.telegram_id.cast(db.String)]
        elif platform == 'whatsapp':
             # Logique WhatsApp (inchangée pour la récupération de base)
             base_query = db.session.query(WhatsAppMessage.from_number).distinct()
             if search_term:
                 base_query = base_query.filter(WhatsAppMessage.from_number.ilike(f'%{search_term}%'))
             base_query = base_query.order_by(WhatsAppMessage.from_number) # Trier pour pagination stable
        else:
            return jsonify({"error": "Platform not supported"}), 404

        # 2. Appliquer les filtres (Web/Telegram) - AVANT la pagination
        if platform in ['web', 'telegram']:
            # Filtre de statut
            if status_filter == 'active':
                # Doit avoir une date last_active non nulle ET supérieure au seuil
                # S'assurer que last_active_column n'est pas None avant de filtrer
                if last_active_column is not None:
                    base_query = base_query.filter(last_active_column != None, last_active_column >= activity_threshold)
                else:
                     app.logger.warning(f"Impossible d'appliquer le filtre 'active' car la colonne last_active n'est pas définie pour {platform}")
            elif status_filter == 'inactive':
                # Doit avoir une date last_active nulle OU inférieure au seuil
                if last_active_column is not None:
                    base_query = base_query.filter(or_(last_active_column == None, last_active_column < activity_threshold))
                else:
                    app.logger.warning(f"Impossible d'appliquer le filtre 'inactive' car la colonne last_active n'est pas définie pour {platform}")

            # Filtre de recherche
            if search_term:
                search_conditions = [field.ilike(f'%{search_term}%') for field in search_fields]
                base_query = base_query.filter(or_(*search_conditions))

            # Trier (important pour la pagination)
            base_query = base_query.order_by(desc(user_model.created_at))

        # 3. Appliquer la pagination (après les filtres)
        pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)

        # 4. Traiter les résultats de la page actuelle
        if platform == 'web':
            users_on_page = pagination.items
            users_data = []
            for user in users_on_page:
                # Calculer l'état 'active' basé sur last_active et le seuil
                is_active = user.last_active is not None and user.last_active >= activity_threshold
                users_data.append({
                    'id': user.id,
                    'first_name': user.first_name, 'last_name': user.last_name,
                    'phone_number': user.phone_number, 'age': user.age,
                    'study_level': user.study_level,
                    'created_at': user.created_at.strftime('%d/%m/%Y'),
                    'active': is_active # <-- POINT CLÉ : VRAI booléen calculé
                })

        elif platform == 'telegram':
            users_on_page = pagination.items
            users_data = []
            for user in users_on_page:
                # Calculer l'état 'active' basé sur last_active et le seuil
                is_active = user.last_active is not None and user.last_active >= activity_threshold
                users_data.append({
                    'id': user.telegram_id, # Utilise toujours telegram_id comme ID principal pour TG
                    'telegram_id': user.telegram_id,
                    'first_name': user.first_name or "---", 'last_name': user.last_name or "---",
                    'phone': user.phone_number, 'study_level': user.study_level,
                    'created_at': user.created_at.strftime('%d/%m/%Y'),
                    'active': is_active # <-- POINT CLÉ : VRAI booléen calculé
                })

        elif platform == 'whatsapp':
            # Logique WhatsApp (presque inchangée, juste le seuil d'activité)
            numbers_on_page = [item[0] for item in pagination.items]
            first_message_times = {}
            last_message_times = {}
            if numbers_on_page:
                # ... (récupération first_ts/last_ts inchangée) ...
                first_msg_subq = db.session.query(
                    WhatsAppMessage.from_number, func.min(WhatsAppMessage.timestamp).label('first_ts')
                ).filter(WhatsAppMessage.from_number.in_(numbers_on_page)).group_by(WhatsAppMessage.from_number).subquery()
                first_message_times = dict(db.session.query(first_msg_subq.c.from_number, first_msg_subq.c.first_ts).all())

                last_msg_subq = db.session.query(
                    WhatsAppMessage.from_number, func.max(WhatsAppMessage.timestamp).label('last_ts')
                ).filter(WhatsAppMessage.from_number.in_(numbers_on_page)).group_by(WhatsAppMessage.from_number).subquery()
                last_message_times = dict(db.session.query(last_msg_subq.c.from_number, last_msg_subq.c.last_ts).all())

            users_data = []
            for num in numbers_on_page:
                first_ts = first_message_times.get(num)
                last_ts = last_message_times.get(num)
                # Calculer is_active basé sur le timestamp du dernier message WA et le seuil commun
                is_active = last_ts is not None and last_ts >= activity_threshold
                # Appliquer le filtre status *ici* pour WA
                if status_filter is None or (status_filter == 'active' and is_active) or (status_filter == 'inactive' and not is_active):
                    users_data.append({
                        'id': num, 'name': f'WhatsApp User {num}', 'phone': num,
                        'study_level': 'N/A',
                        'created_at': first_ts.strftime('%d/%m/%Y') if first_ts else 'N/A',
                        'active': is_active # Utilise le booléen calculé
                    })

        # 5. Construire les données de pagination (inchangé)
        pagination_data = {
            'total_items': pagination.total, 'total_pages': pagination.pages,
            'current_page': pagination.page, 'per_page': pagination.per_page,
            'has_next': pagination.has_next, 'has_prev': pagination.has_prev,
            'next_page_num': pagination.next_num, 'prev_page_num': pagination.prev_num
        }

        return jsonify({'users': users_data, 'pagination': pagination_data})

    except Exception as e:
        app.logger.exception(f"Error fetching users for platform {platform}: {e}")
        return jsonify({"error": "Failed to retrieve users"}), 500

@app.route('/admin/conversations/<platform>')
def admin_platform_conversations(platform):
    """Get a paginated list of conversations for a specific platform, with filtering and search."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status_filter = request.args.get('filter', None, type=str) # 'active' ou 'archived'
        search_term = request.args.get('search', None, type=str)

        conversations_on_page_data = [] # Renommé pour clarté
        pagination_data = {}
        base_query = None
        conv_model = None
        message_model = None
        conv_id_col = None
        msg_conv_fk_col = None
        msg_created_at_col = None
        search_fields = []

        # Définir le seuil d'activité (ex: 15 minutes)
        activity_threshold = datetime.utcnow() - timedelta(seconds=900)

        # 1. Identifier les modèles et colonnes pertinents
        if platform == 'web':
            conv_model = Conversation
            message_model = Message
            conv_id_col = Conversation.id
            msg_conv_fk_col = Message.conversation_id
            msg_created_at_col = Message.created_at
            search_fields = [Conversation.title]
            # Requête initiale sur le modèle Conversation
            base_query = db.session.query(conv_model)
        elif platform == 'telegram':
            conv_model = TelegramConversation
            message_model = TelegramMessage
            conv_id_col = TelegramConversation.id
            msg_conv_fk_col = TelegramMessage.conversation_id
            msg_created_at_col = TelegramMessage.created_at
            search_fields = [TelegramConversation.title]
             # Requête initiale sur le modèle TelegramConversation
            base_query = db.session.query(conv_model)
        elif platform == 'whatsapp':
             # Logique WA reste basée sur les threads et leurs derniers messages directs
             last_msg_subq = db.session.query(
                 WhatsAppMessage.thread_id,
                 func.max(WhatsAppMessage.timestamp).label('last_msg_time')
             ).group_by(WhatsAppMessage.thread_id).subquery()
             # La requête de base sélectionne thread_id et last_msg_time
             base_query = db.session.query(
                 last_msg_subq.c.thread_id, last_msg_subq.c.last_msg_time
             )
             # Recherche sur thread_id pour WA
             if search_term:
                 base_query = base_query.filter(last_msg_subq.c.thread_id.ilike(f'%{search_term}%'))
             conv_model = None # Pas de modèle direct pour WA conversation
        else:
            return jsonify({"error": "Platform not supported"}), 404

        # 2. Appliquer le filtre de recherche (Web/Telegram seulement sur titre)
        if platform in ['web', 'telegram']:
            if search_term and search_fields: # S'assurer qu'il y a des champs où chercher
                search_conditions = [field.ilike(f'%{search_term}%') for field in search_fields]
                if search_conditions:
                    base_query = base_query.filter(or_(*search_conditions))

        # 3. Appliquer le filtre de statut basé sur le temps (TOUTES plateformes)
        if platform in ['web', 'telegram']:
            # Sous-requête pour trouver le timestamp du dernier message
            last_message_subquery = db.session.query(
                msg_conv_fk_col,
                func.max(msg_created_at_col).label('last_message_time')
            ).group_by(msg_conv_fk_col).subquery()

            # Joindre la requête de base avec la sous-requête
            # S'assurer de ne joindre que sur les conversations qui ont au moins un message
            base_query = base_query.join(
                last_message_subquery, conv_id_col == last_message_subquery.c.conversation_id
            )

            # Filtrer basé sur le temps du dernier message
            if status_filter == 'active':
                base_query = base_query.filter(last_message_subquery.c.last_message_time >= activity_threshold)
            elif status_filter == 'archived': # Traiter 'archived' comme 'inactive'
                base_query = base_query.filter(last_message_subquery.c.last_message_time < activity_threshold)

            # Ajouter la colonne last_message_time à la sélection et trier par elle
            base_query = base_query.add_columns(last_message_subquery.c.last_message_time)\
                                 .order_by(desc(last_message_subquery.c.last_message_time))

        elif platform == 'whatsapp':
             # Filtrer basé sur last_msg_time déjà calculé
             if status_filter == 'active':
                 base_query = base_query.filter(last_msg_subq.c.last_msg_time >= activity_threshold)
             elif status_filter == 'archived': # Traiter 'archived' comme 'inactive'
                 base_query = base_query.filter(last_msg_subq.c.last_msg_time < activity_threshold)

             # Trier par le timestamp du dernier message
             base_query = base_query.order_by(desc(last_msg_subq.c.last_msg_time))

        # 4. Appliquer la pagination (Après TOUS les filtres et tris)
        pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)

        # 5. Traiter les résultats de la page actuelle et récupérer le dernier message
        latest_msgs_dict = {}
        conversations_on_page_data = [] # Réinitialisé pour clarté

        if platform in ['web', 'telegram']:
            conversations_processed = [] # Pour stocker les objets Conversation
            last_message_times_dict = {} # Pour stocker les timestamps
            conv_ids_on_page = []

            # Les items sont maintenant des tuples (ObjetConversation, last_message_time)
            for item in pagination.items:
                conv_object = item[0]
                last_message_time = item[1]
                conversations_processed.append(conv_object)
                conv_id = conv_object.id
                conv_ids_on_page.append(conv_id)
                last_message_times_dict[conv_id] = last_message_time

            # Récupérer le contenu du dernier message pour ces conversations (optimisé)
            if conv_ids_on_page:
                subq_msg_content = db.session.query(
                    msg_conv_fk_col, message_model.content,
                    func.row_number().over(partition_by=msg_conv_fk_col, order_by=desc(msg_created_at_col)).label('rn')
                ).filter(msg_conv_fk_col.in_(conv_ids_on_page)).subquery()
                latest_msgs_q = db.session.query(subq_msg_content.c.conversation_id, subq_msg_content.c.content).filter(subq_msg_content.c.rn == 1)
                latest_msgs_dict = dict(latest_msgs_q.all())

            # Formater les données pour la réponse JSON
            for conv in conversations_processed:
                last_msg_ts = last_message_times_dict.get(conv.id)
                # Déterminer le statut DYNAMIQUEMENT
                is_active = last_msg_ts is not None and last_msg_ts >= activity_threshold
                current_status = 'active' if is_active else 'archived' # Utiliser 'archived' si le frontend s'y attend
                conv_title = getattr(conv, 'title', None) or (f"Conversation {conv.id}" if platform == 'telegram' else "Sans titre")
                conv_created_at = getattr(conv, 'created_at', datetime.min)

                conversations_on_page_data.append({
                    'id': conv.id,
                    'title': conv_title,
                    'date': conv_created_at.strftime('%d/%m/%Y'),
                    'time': conv_created_at.strftime('%H:%M'), # Utilisation de created_at pour date/time de la conv
                    'last_message': latest_msgs_dict.get(conv.id, "No messages"),
                    'status': current_status # <-- Statut dynamique basé sur le temps
                })

        elif platform == 'whatsapp':
            threads_on_page = pagination.items # [(thread_id, last_msg_time), ...]
            thread_ids_on_page = [item[0] for item in threads_on_page]
            last_message_times_dict = dict(threads_on_page) # Stocker les timestamps

            if thread_ids_on_page:
                # Récupérer le contenu du dernier message (comme avant)
                subq_msg = db.session.query(
                    WhatsAppMessage.thread_id, WhatsAppMessage.content,
                    func.row_number().over(partition_by=WhatsAppMessage.thread_id, order_by=desc(WhatsAppMessage.timestamp)).label('rn')
                ).filter(WhatsAppMessage.thread_id.in_(thread_ids_on_page)).subquery()
                latest_msgs_q = db.session.query(subq_msg.c.thread_id, subq_msg.c.content).filter(subq_msg.c.rn == 1)
                latest_msgs_dict = dict(latest_msgs_q.all())

            # Formater les données pour la réponse JSON
            for thread_id, last_time in threads_on_page:
                 # Déterminer le statut DYNAMIQUEMENT basé sur le temps
                is_active = last_time is not None and last_time >= activity_threshold
                current_status = 'active' if is_active else 'archived'

                conversations_on_page_data.append({
                    'id': thread_id,
                    'title': f"Conversation {thread_id}",
                    'date': last_time.strftime('%d/%m/%Y') if last_time else 'N/A', # Utiliser last_time pour la date/heure WA
                    'time': last_time.strftime('%H:%M') if last_time else 'N/A',
                    'last_message': latest_msgs_dict.get(thread_id, "No messages"),
                    'status': current_status # <-- Statut dynamique basé sur le temps
                })

        # 6. Construire les données de pagination (inchangé)
        pagination_data = {
            'total_items': pagination.total, 'total_pages': pagination.pages,
            'current_page': pagination.page, 'per_page': pagination.per_page,
            'has_next': pagination.has_next, 'has_prev': pagination.has_prev,
            'next_page_num': pagination.next_num, 'prev_page_num': pagination.prev_num
        }

        # Renvoyer les données formatées
        return jsonify({'conversations': conversations_on_page_data, 'pagination': pagination_data})

    except Exception as e:
        app.logger.exception(f"Error fetching conversations for platform {platform}: {e}") # Utiliser logger.exception pour tracerback
        return jsonify({"error": "Failed to retrieve conversations"}), 500

# --- NOTE IMPORTANTE ---
# La route PUT /admin/conversations/<platform>/<int:conv_id>/status
# devient moins pertinente pour gérer l'état "actif/inactif" basé sur le temps.
# Elle pourrait être conservée pour une fonctionnalité d'archivage manuel explicite
# qui serait distincte de l'activité récente, ou être supprimée/modifiée.
# --- FIN NOTE ---


@app.route('/admin/data/<platform>/stats')
def admin_platform_stats(platform):
    """Get only stats for a platform without full data lists, calculated efficiently."""
    today = datetime.today().date()
    data = {} # Initialisation du dictionnaire

    try:
        if platform == 'web':
            active_users_count = db.session.query(func.count(User.id)).scalar() or 0
            today_users_count = db.session.query(func.count(User.id))\
                .filter(User.created_at >= today_date, User.created_at < tomorrow_date).scalar() or 0
            today_conversations_count = db.session.query(func.count(Conversation.id))\
                .filter(Conversation.created_at >= today_date, Conversation.created_at < tomorrow_date).scalar() or 0

            # Calcul du taux de satisfaction (requêtes count() originales conservées)
            total_feedbacks = db.session.query(func.count(MessageFeedback.id)).scalar() or 0
            positive_feedbacks = db.session.query(func.count(MessageFeedback.id))\
                .filter(MessageFeedback.feedback_type == 'positive').scalar() or 0
            satisfaction_rate = round((positive_feedbacks / total_feedbacks) * 100) if total_feedbacks > 0 else 0

            data = {
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': satisfaction_rate
            }

        elif platform == 'telegram':
            active_users_count = db.session.query(func.count(TelegramUser.telegram_id)).scalar() or 0
            today_users_count = db.session.query(func.count(TelegramUser.telegram_id))\
                .filter(TelegramUser.created_at >= today_date, TelegramUser.created_at < tomorrow_date).scalar() or 0
            today_conversations_count = db.session.query(func.count(TelegramConversation.id))\
                .filter(TelegramConversation.created_at >= today_date, TelegramConversation.created_at < tomorrow_date).scalar() or 0

            data = {
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': 0 # Pas de feedback géré ici apparemment
            }

        elif platform == 'whatsapp':
            active_users_count = db.session.query(func.count(func.distinct(WhatsAppMessage.from_number))).scalar() or 0
            today_users_count = db.session.query(func.count(func.distinct(WhatsAppMessage.from_number)))\
            .filter(WhatsAppMessage.timestamp >= today_date, WhatsAppMessage.timestamp < tomorrow_date).scalar() or 0

            # Compte des conversations (threads) dont le premier message est d'aujourd'hui
            subquery = db.session.query(
                WhatsAppMessage.thread_id,
                func.min(WhatsAppMessage.timestamp).label('first_message_time')
            ).group_by(WhatsAppMessage.thread_id).subquery()

            today_conversations_count = db.session.query(func.count(subquery.c.thread_id))\
            .filter(subquery.c.first_message_time >= today_date, subquery.c.first_message_time < tomorrow_date)\
            .scalar() or 0

            data = {
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': 0 # Pas de feedback géré ici apparemment
            }
        else:
            # Gérer le cas où la plateforme n'est pas reconnue
             return jsonify({"error": "Platform not supported"}), 404

        return jsonify(data)

    except Exception as e:
        # Loggez l'erreur pour le débogage
        app.logger.error(f"Error fetching stats for platform {platform}: {e}")
        # Renvoyez une réponse d'erreur générique
        return jsonify({"error": "Failed to retrieve statistics"}), 500


@login_manager.unauthorized_handler
def unauthorized():
    """Redirect unauthorized users to Login page."""
    flash('Please log in to access this page.')
    return redirect(url_for('register'))


@app.route('/admin/users/<user_id>', methods=['DELETE'])
def delete_user(user_id):
    """Delete a user and their associated data."""
    try:
        logger.info(f"Attempting to delete user with ID: {user_id}")

        # Find the user based on the platform data
        user = None

        # Try to find in web users
        user = User.query.filter_by(phone_number=user_id).first()
        if user:
            logger.info(
                f"Found web user with ID {user.id}, phone: {user.phone_number}"
            )

            try:
                # Importer le module text pour les requêtes SQL
                from sqlalchemy import text

                # Utiliser du SQL pur avec une connexion directe pour éviter
                # les problèmes avec le modèle ORM et gérer les transactions correctement
                with db.engine.begin() as connection:
                    # 1. Récupérer l'ID de l'utilisateur pour les requêtes suivantes
                    user_id_to_delete = user.id

                    # 2. Supprimer les associations dans user_subscription
                    logger.info(
                        f"Deleting subscription relationships for user {user_id_to_delete}"
                    )
                    connection.execute(
                        text(
                            "DELETE FROM subscription WHERE user_id = :user_id"
                        ), {"user_id": user_id_to_delete})

                    # 3. Supprimer les messages liés aux conversations de l'utilisateur
                    logger.info(
                        f"Deleting messages for user {user_id_to_delete}")
                    connection.execute(
                        text("""DELETE FROM message 
                                WHERE conversation_id IN (
                                    SELECT id FROM conversation WHERE user_id = :user_id
                                )"""), {"user_id": user_id_to_delete})

                    # 4. Supprimer les conversations de l'utilisateur
                    logger.info(
                        f"Deleting conversations for user {user_id_to_delete}")
                    connection.execute(
                        text(
                            "DELETE FROM conversation WHERE user_id = :user_id"
                        ), {"user_id": user_id_to_delete})

                    # 5. Supprimer l'utilisateur lui-même
                    # Note: le mot-clé "user" est réservé dans SQL, donc on le met entre guillemets
                    logger.info(f"Deleting user with ID {user_id_to_delete}")
                    connection.execute(
                        text("DELETE FROM \"user\" WHERE id = :user_id"),
                        {"user_id": user_id_to_delete})

                # Si on arrive ici, c'est que la transaction a été validée avec succès
                logger.info(f"Web user {user_id} deleted successfully")
                return jsonify({
                    'success': True,
                    'message': 'User deleted successfully'
                })

            except Exception as e:
                logger.error(f"Error deleting web user: {str(e)}")
                return jsonify({
                    'success': False,
                    'message': f'Error deleting user: {str(e)}'
                }), 500

        # Try to find in Telegram users
        user = TelegramUser.query.filter_by(telegram_id=user_id).first()
        if user:
            try:
                with db_retry_session() as session:
                    # Delete all messages first
                    for conv in user.conversations:
                        TelegramMessage.query.filter_by(
                            conversation_id=conv.id).delete()
                    session.flush()

                    # Delete all conversations
                    TelegramConversation.query.filter_by(
                        telegram_user_id=user.telegram_id).delete()
                    session.flush()

                    # Finally delete the user
                    session.delete(user)
                    session.commit()
                    return jsonify({
                        'success':
                        True,
                        'message':
                        'Telegram user deleted successfully'
                    })
            except Exception as telegram_error:
                logger.error(
                    f"Error deleting Telegram user: {str(telegram_error)}")
                session.rollback()
                return jsonify({
                    'success':
                    False,
                    'message':
                    f'Error deleting Telegram user: {str(telegram_error)}'
                }), 500

        # Check WhatsApp users (using the phone number as ID)
        messages = WhatsAppMessage.query.filter_by(from_number=user_id).all()
        if messages:
            try:
                with db_retry_session() as session:
                    # On récupère d'abord tous les thread_id associés à ce numéro
                    thread_ids = db.session.query(WhatsAppMessage.thread_id)\
                        .filter(WhatsAppMessage.from_number == user_id)\
                        .distinct().all()

                    # Pour chaque thread_id, on supprime tous les messages associés
                    for thread_id in thread_ids:
                        thread_id = thread_id[
                            0]  # Extraction de la valeur depuis le tuple
                        logger.info(
                            f"Deleting all messages for WhatsApp thread {thread_id}"
                        )
                        WhatsAppMessage.query.filter_by(
                            thread_id=thread_id).delete()

                    session.commit()
                    return jsonify({
                        'success':
                        True,
                        'message':
                        'WhatsApp user and all associated conversations deleted successfully'
                    })
            except Exception as whatsapp_error:
                logger.error(
                    f"Error deleting WhatsApp messages: {str(whatsapp_error)}")
                session.rollback()
                return jsonify({
                    'success':
                    False,
                    'message':
                    f'Error deleting WhatsApp messages: {str(whatsapp_error)}'
                }), 500

        return jsonify({'success': False, 'message': 'User not found'}), 404

    except Exception as e:
        logger.error(f"Error in delete_user function for {user_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Server error: {str(e)}'
        }), 500


@app.route('/admin/conversations/<int:conversation_id>/messages')
def get_conversation_messages(conversation_id):
    """Get messages for a specific Web or Telegram conversation by its DATABASE ID"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        messages_data = []
        platform_type = None

        # 1. Check regular Web conversations
        web_conv = Conversation.query.get(conversation_id)
        if web_conv:
            platform_type = 'web'
            messages = Message.query.filter_by(conversation_id=web_conv.id)\
                .order_by(Message.created_at).all()
            messages_data = [{
                'role': msg.role,
                'content': msg.content,
                'image_url': msg.image_url,
                'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
            } for msg in messages]
            logger.info(f"Messages trouvés pour la conversation Web ID: {conversation_id}")

        # 2. If not found, check Telegram conversations
        else:
            tg_conv = TelegramConversation.query.get(conversation_id)
            if tg_conv:
                platform_type = 'telegram'
                messages = TelegramMessage.query.filter_by(conversation_id=tg_conv.id)\
                    .order_by(TelegramMessage.created_at).all()
                messages_data = [{
                    'role': getattr(msg, 'role', 'unknown'),
                    'content': getattr(msg, 'content', ''),
                    'image_url': getattr(msg, 'image_url', None),
                    'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                } for msg in messages]
                logger.info(f"Messages trouvés pour la conversation Telegram ID: {conversation_id}")

        # 3. Return messages or 404 if not found in Web or Telegram
        if platform_type:
            return jsonify({'messages': messages_data, 'platform': platform_type})
        else:
            logger.warning(f"Conversation (Web ou Telegram) avec ID {conversation_id} non trouvée via /admin/conversations/<id>/messages.")
            return jsonify({'error': 'Conversation not found by ID'}), 404

    except Exception as e:
        logger.exception(f"Error fetching Web/Telegram conversation messages by ID {conversation_id}: {e}")
        return jsonify({'error': 'Internal server error'}), 500

# --- NOUVELLE ROUTE POUR ENVOYER DES MESSAGES ADMIN ---
@app.route('/admin/web/conversations/<int:conversation_id>/send', methods=['POST'])
@login_required # Utilisez votre décorateur pour vérifier la connexion (admin check ci-dessous)
def send_admin_web_message(conversation_id):
    """Envoie un message admin à une conversation Web spécifique."""
    try:
        # Vérification Admin
        if not session.get('is_admin'):
            logger.warning("Tentative d'accès non autorisé à l'envoi de message admin Web.")
            return jsonify({'error': 'Unauthorized access'}), 403

        # Récupération du contenu
        data = request.json
        message_content = data.get('message')
        if not message_content or message_content.strip() == '':
            logger.warning("Tentative d'envoi de message admin Web vide.")
            return jsonify({'error': 'Message content is required'}), 400

        # Trouver la conversation Web
        web_conv = Conversation.query.get(conversation_id)
        if not web_conv:
            logger.warning(f"Conversation Web ID {conversation_id} non trouvée.")
            return jsonify({'error': 'Web Conversation not found'}), 404

        # Sauvegarder le message admin dans la DB Web
        new_message = Message(
            conversation_id=web_conv.id,
            role='admin',
            content=message_content,
            created_at=datetime.utcnow()
        )
        db.session.add(new_message)
        db.session.commit()
        logger.info(f"Message admin sauvegardé pour conversation Web ID: {conversation_id}, Message ID: {new_message.id}")

        # TODO (Optionnel): Émettre un événement SocketIO ici si l'interface Web doit être mise à jour en temps réel

        # Préparer la réponse pour le frontend
        message_data_for_frontend = {
            'id': new_message.id, # ID du message sauvegardé
            'role': 'admin',
            'content': message_content,
            'created_at': new_message.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
        return jsonify({
            'success': True,
            'message': 'Web admin message saved',
            'message_data': message_data_for_frontend
        })

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Erreur lors de l'envoi/sauvegarde message admin Web pour conversation {conversation_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

# --- NOUVELLE ROUTE POUR SUPPRIMER PAR ID (WEB/TELEGRAM) ---
@app.route('/admin/conversations/<int:conversation_id>', methods=['DELETE'])
def delete_conversation_by_id(conversation_id):
    """Delete a Web or Telegram conversation by its DATABASE ID"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        conversation_deleted = False
        deleted_platform = None

        # 1. Essayer de supprimer une conversation Web
        web_conv = Conversation.query.get(conversation_id)
        if web_conv:
            logger.info(f"Tentative de suppression de la conversation Web ID: {conversation_id}")
            # Supprimer d'abord les messages associés (cascade peut aussi gérer ça selon config DB)
            Message.query.filter_by(conversation_id=web_conv.id).delete()
            # Supprimer ensuite la conversation
            db.session.delete(web_conv)
            db.session.commit()
            conversation_deleted = True
            deleted_platform = 'web'
            logger.info(f"Conversation Web ID: {conversation_id} supprimée avec succès.")

        # 2. Si non trouvée/supprimée, essayer de supprimer une conversation Telegram
        if not conversation_deleted:
            tg_conv = TelegramConversation.query.get(conversation_id)
            if tg_conv:
                logger.info(f"Tentative de suppression de la conversation Telegram ID: {conversation_id}")
                # Supprimer d'abord les messages associés
                TelegramMessage.query.filter_by(conversation_id=tg_conv.id).delete()
                # Supprimer ensuite la conversation
                db.session.delete(tg_conv)
                db.session.commit()
                conversation_deleted = True
                deleted_platform = 'telegram'
                logger.info(f"Conversation Telegram ID: {conversation_id} supprimée avec succès.")

        # 3. Renvoyer le résultat
        if conversation_deleted:
            return jsonify({'success': True, 'message': f'Conversation ({deleted_platform}) deleted successfully'})
        else:
            logger.warning(f"Échec de la suppression : Conversation (Web ou Telegram) avec ID {conversation_id} non trouvée.")
            return jsonify({'success': False, 'message': 'Conversation not found by ID'}), 404

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting conversation by ID {conversation_id}: {e}")
        return jsonify({'success': False, 'message': 'Error deleting conversation', 'error': str(e)}), 500


@app.route('/admin/whatsapp/thread/<path:thread_id>/messages')
def get_whatsapp_thread_messages(thread_id):
    """Get messages for a specific WhatsApp thread"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        # Log pour le débogage
        logger.debug(f"Fetching WhatsApp messages for thread: {thread_id}")

        # Récupérer les messages WhatsApp pour ce thread
        whatsapp_messages = WhatsAppMessage.query.filter_by(thread_id=thread_id)\
            .order_by(WhatsAppMessage.timestamp).all()

        if whatsapp_messages:
            return jsonify({
                'messages': [{
                    'role':
                    'user' if msg.direction == 'inbound' else 'assistant',
                    'content':
                    msg.content,
                    'created_at':
                    msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                } for msg in whatsapp_messages]
            })

        return jsonify({'error':
                        'No WhatsApp messages found for this thread'}), 404

    except Exception as e:
        logger.error(f"Error fetching WhatsApp thread messages: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/admin/whatsapp/thread/<path:thread_id>', methods=['DELETE'])
def delete_whatsapp_thread(thread_id):
    """Delete all messages associated with a WhatsApp thread_id"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        logger.info(f"Tentative de suppression de la conversation WhatsApp thread: {thread_id}")

        # Compter les messages avant suppression (optionnel, pour vérifier)
        message_count = WhatsAppMessage.query.filter_by(thread_id=thread_id).count()

        if message_count > 0:
            # Supprimer tous les messages de ce thread
            WhatsAppMessage.query.filter_by(thread_id=thread_id).delete()
            db.session.commit()
            logger.info(f"Conversation WhatsApp thread {thread_id} ({message_count} messages) supprimée avec succès.")
            return jsonify({'success': True, 'message': 'WhatsApp conversation deleted successfully'})
        else:
            logger.warning(f"Échec de la suppression : Aucune conversation WhatsApp trouvée pour le thread {thread_id}.")
            # Renvoyer 404 même si le thread n'existait pas, car l'objectif (sa non-existence) est atteint.
            # Ou renvoyer un message spécifique si vous préférez.
            return jsonify({'success': False, 'message': 'WhatsApp conversation (thread) not found'}), 404

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting WhatsApp thread {thread_id}: {e}")
        return jsonify({'success': False, 'message': 'Error deleting WhatsApp conversation', 'error': str(e)}), 500


@app.route('/admin/subscriptions', methods=['GET'])
def get_subscriptions():
    """Get all subscriptions data"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        subscriptions = Subscription.query.all()

        return jsonify({
            'subscriptions': [{
                'id':
                sub.id,
                'user_id':
                sub.user_id,
                'user_name':
                f"{sub.user.first_name} {sub.user.last_name}",
                'type':
                sub.subscription_type,
                'start_date':
                sub.start_date.strftime('%Y-%m-%d'),
                'expiry_date':
                sub.expiry_date.strftime('%Y-%m-%d'),
                'status':
                sub.status,
                'last_payment_date':
                sub.last_payment_date.strftime('%Y-%m-%d')
                if sub.last_payment_date else None
            } for sub in subscriptions]
        })

    except Exception as e:
        logger.error(f"Error fetching subscriptions: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/admin/subscriptions', methods=['POST'])
def create_subscription():
    """Create a new subscription"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        data = request.get_json()

        # Validate required fields
        required_fields = [
            'user_id', 'subscription_type', 'expiry_date', 'status'
        ]
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        # Create new subscription
        subscription = Subscription(
            user_id=data['user_id'],
            subscription_type=data['subscription_type'],
            start_date=datetime.now(),
            expiry_date=datetime.strptime(data['expiry_date'], '%Y-%m-%d'),
            status=data['status'],
            last_payment_date=datetime.now())

        db.session.add(subscription)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Subscription created successfully',
            'subscription_id': subscription.id
        })

    except Exception as e:
        logger.error(f"Error creating subscription: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/admin/subscriptions/<int:subscription_id>', methods=['PUT'])
def update_subscription(subscription_id):
    """Update an existing subscription"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        subscription = Subscription.query.get(subscription_id)
        if not subscription:
            return jsonify({'error': 'Subscription not found'}), 404

        data = request.get_json()

        # Update fields if provided
        if 'subscription_type' in data:
            subscription.subscription_type = data['subscription_type']
        if 'expiry_date' in data:
            subscription.expiry_date = datetime.strptime(
                data['expiry_date'], '%Y-%m-%d')
        if 'status' in data:
            subscription.status = data['status']

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Subscription updated successfully'
        })

    except Exception as e:
        logger.error(f"Error updating subscription: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/admin/subscriptions/<int:subscription_id>', methods=['DELETE'])
def delete_subscription(subscription_id):
    """Delete a subscription"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        subscription = Subscription.query.get(subscription_id)
        if not subscription:
            return jsonify({'error': 'Subscription not found'}), 404

        db.session.delete(subscription)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Subscription deleted successfully'
        })

    except Exception as e:
        logger.error(f"Error deleting subscription: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    # Schedule the cleanup task
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=cleanup_uploads, trigger="interval", hours=1)
    scheduler.start()
    app.run(host='0.0.0.0', port=8080)

    # Start the Socket.IO server
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)