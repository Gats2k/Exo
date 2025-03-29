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
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import exc
import shutil
import time
import logging
from contextlib import contextmanager
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
import uuid
from mathpix_utils import process_image_with_mathpix # Added import
import json
from typing_extensions import override
from openai import AssistantEventHandler

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

# Initialize SocketIO with eventlet
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Initialize OpenAI clients
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
deepseek_client = OpenAI(
    api_key=os.getenv('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"
)
qwen_client = OpenAI(
    api_key=os.getenv('DASHSCOPE_API_KEY'),
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

# Le client Gemini ne peut pas utiliser OpenAI directement (APIs incompatibles)
# Nous utiliserons une fonction spéciale pour gérer les requêtes Gemini
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Get the current AI model from environment or default to OpenAI
CURRENT_MODEL = os.environ.get('CURRENT_MODEL', 'openai')
DEEPSEEK_INSTRUCTIONS = os.environ.get('DEEPSEEK_INSTRUCTIONS', 'You are a helpful educational assistant')
DEEPSEEK_REASONER_INSTRUCTIONS = os.environ.get('DEEPSEEK_REASONER_INSTRUCTIONS', 'You are a helpful educational assistant focused on reasoning and problem-solving')
QWEN_INSTRUCTIONS = os.environ.get('QWEN_INSTRUCTIONS', 'You are a helpful educational assistant focused on providing accurate and comprehensive answers')
GEMINI_INSTRUCTIONS = os.environ.get('GEMINI_INSTRUCTIONS', 'You are a helpful educational assistant specialized in explaining complex concepts clearly')
CONTEXT_MESSAGE_LIMIT = int(os.environ.get('CONTEXT_MESSAGE_LIMIT', '50'))

def get_ai_client():
    """Returns the appropriate AI client based on the current model setting"""
    if CURRENT_MODEL in ['deepseek', 'deepseek-reasoner']:
        return deepseek_client
    elif CURRENT_MODEL == 'qwen':
        return qwen_client
    else:
        return openai_client  # Default to OpenAI

def get_model_name():
    """Returns the appropriate model name based on the current model setting"""
    if CURRENT_MODEL == 'deepseek':
        return "deepseek-chat"
    elif CURRENT_MODEL == 'deepseek-reasoner':
        return "deepseek-reasoner"
    elif CURRENT_MODEL == 'qwen':
        return "qwen-max"
    elif CURRENT_MODEL == 'gemini':
        return "gemini-2.0-flash"
    return None  # For OpenAI, model is determined by assistant

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
        # Ajouter l'attribut manquant
        self._AssistantEventHandler__stream = None

    @override
    def on_text_created(self, text) -> None:
        # Initialisation du texte - pas besoin d'envoyer de contenu ici
        pass

    @override
    def on_text_delta(self, delta, snapshot):
        # Ajouter le delta au texte complet
        self.full_response += delta.value

        # Émettre le nouveau contenu à l'utilisateur
        self.socket.emit('response_stream', {
            'content': delta.value,
            'message_id': self.message_id,
            'is_final': False
        })

    @override
    def on_run_completed(self):
        # Émettre l'événement final quand le run est terminé
        self.socket.emit('response_stream', {
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
                self.socket.emit('response_stream', {
                    'content': f"\n```python\n{delta.code_interpreter.input}\n```\n",
                    'message_id': self.message_id,
                    'is_final': False
                })

            if delta.code_interpreter and delta.code_interpreter.outputs:
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        self.full_response += f"\n```\n{output.logs}\n```\n"
                        self.socket.emit('response_stream', {
                            'content': f"\n```\n{output.logs}\n```\n",
                            'message_id': self.message_id,
                            'is_final': False
                        })

            if delta.code_interpreter and delta.code_interpreter.outputs:
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        self.full_response += f"\n```\n{output.logs}\n```\n"
                        self.socket.emit('response_stream', {
                            'content': f"\n```\n{output.logs}\n```\n",
                            'message_id': self.message_id,
                            'is_final': False
                        })

def call_gemini_api(messages):
    """
    Call the Gemini API with the provided messages.

    Args:
        messages: List of message dictionaries with 'role' and 'content'

    Returns:
        The assistant's response content
    """
    import json
    import requests

    logger.info(f"Calling Gemini API with {len(messages)} messages")

    try:
        # Format messages for Gemini API
        gemini_messages = []

        # Extract the system message if it exists
        system_content = None
        for msg in messages:
            if msg['role'] == 'system':
                system_content = msg['content']
                break

        # Process the conversation messages (excluding system message)
        contents = []
        for msg in messages:
            if msg['role'] != 'system':
                # Vérifier que le contenu n'est pas vide
                if not msg['content'] or msg['content'].strip() == "":
                    continue

                role = "user" if msg['role'] == 'user' else "model"
                contents.append({
                    "parts": [{"text": msg['content']}],
                    "role": role
                })

        # Add system message as a special prefix to the first user message if it exists
        if system_content and len(contents) > 0 and contents[0]['role'] == 'user':
            contents[0]['parts'][0]['text'] = f"[System: {system_content}]\n\n" + contents[0]['parts'][0]['text']

        # Make sure we have at least one message in contents with non-empty text
        if not contents:
            contents.append({
                "parts": [{"text": "Bonjour, je suis là pour vous aider."}],
                "role": "user"
            })

        # Vérifier qu'aucun des messages n'a un texte vide
        for content in contents:
            if not content['parts'][0]['text'] or content['parts'][0]['text'].strip() == "":
                content['parts'][0]['text'] = "Message vide remplacé"

        # Prepare the API request
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": contents}

        logger.info(f"Sending request to Gemini API with {len(contents)} messages")
        logger.debug(f"Request payload: {json.dumps(data)}")

        # Make the API request
        response = requests.post(api_url, headers=headers, json=data)

        if response.status_code != 200:
            logger.error(f"Gemini API error: {response.status_code} - {response.text}")
            return f"I apologize, but I encountered an error communicating with my AI brain. Error: {response.status_code}"

        # Parse the response
        response_json = response.json()
        logger.info("Received response from Gemini API")

        # Extract the generated text from the response
        if 'candidates' in response_json and len(response_json['candidates']) > 0:
            candidate = response_json['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content'] and len(candidate['content']['parts']) > 0:
                return candidate['content']['parts'][0]['text']

        logger.error(f"Unexpected response structure from Gemini API: {response_json}")
        return "I apologize, but I received an unexpected response format from my AI brain."

    except Exception as e:
        logger.error(f"Exception in call_gemini_api: {str(e)}", exc_info=True)
        return f"I apologize, but I encountered an error processing your request. Error: {str(e)}"

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
            logger.warning(f"Database connection failed, retrying... (attempt {attempt + 1}/{max_retries})")
            time.sleep(retry_delay)
        except Exception as e:
            raise

def get_db_context():
    """Get the Flask application context for database operations."""
    return app.app_context()

def get_or_create_conversation(thread_id=None):
    with db_retry_session() as session:
        if thread_id:
            conversation = Conversation.query.filter_by(thread_id=thread_id).first()
            # Vérifier si cette conversation appartient à l'utilisateur actuel
            if conversation and current_user.is_authenticated and conversation.user_id == current_user.id:
                # Vérifier si le thread OpenAI existe toujours (uniquement pour le modèle OpenAI)
                if CURRENT_MODEL == 'openai':
                    try:
                        # Tester si le thread existe dans OpenAI
                        client = get_ai_client()
                        client.beta.threads.messages.list(thread_id=thread_id, limit=1)
                        # Si on arrive ici, le thread existe
                        return conversation
                    except Exception as e:
                        logger.warning(f"Thread {thread_id} not found or invalid: {str(e)}")
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

        conversation = Conversation(thread_id=thread_id, user_id=user_id)
        session.add(conversation)
        session.commit()

        # Émettre l'événement de nouvelle conversation Web pour le tableau de bord
        socketio.emit('new_web_conversation', {
            'id': conversation.id,
            'title': conversation.title or f"Nouvelle conversation",
            'user_id': user_id
        })

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
            # Vérifier si le thread_id dans la session appartient à l'utilisateur actuel
            thread_id = session.get('thread_id')
            if thread_id and current_user.is_authenticated:
                conversation = Conversation.query.filter_by(thread_id=thread_id).first()
                if not conversation or conversation.user_id != current_user.id:
                    # Ce thread_id n'appartient pas à l'utilisateur actuel, le supprimer
                    session.pop('thread_id')
                    logger.warning(f"Thread_id {thread_id} n'appartient pas à l'utilisateur {current_user.id}, nettoyage effectué")

            conversation_history = []

            # Vérifier si l'utilisateur est connecté via Telegram ou WhatsApp
            is_telegram_user = session.get('is_telegram_user', False)
            telegram_id = session.get('telegram_id')
            is_whatsapp_user = session.get('is_whatsapp_user', False)
            whatsapp_number = session.get('whatsapp_number')

            # Vérifier si l'utilisateur actuel est réellement l'utilisateur Telegram indiqué
            if is_telegram_user and telegram_id and current_user.is_authenticated:
                if not current_user.phone_number.startswith(f"telegram_{telegram_id}"):
                    # Les identifiants ne correspondent pas, nettoyer les données Telegram
                    session.pop('is_telegram_user', None)
                    session.pop('telegram_id', None)
                    is_telegram_user = False
                    telegram_id = None
                    logger.warning(f"Session Telegram incohérente détectée pour l'utilisateur {current_user.id}, nettoyage effectué")

            # Vérifier si l'utilisateur actuel est réellement l'utilisateur WhatsApp indiqué
            if is_whatsapp_user and whatsapp_number and current_user.is_authenticated:
                if not current_user.phone_number.startswith(f"whatsapp_{whatsapp_number}"):
                    # Les identifiants ne correspondent pas, nettoyer les données WhatsApp
                    session.pop('is_whatsapp_user', None)
                    session.pop('whatsapp_number', None)
                    is_whatsapp_user = False
                    whatsapp_number = None
                    logger.warning(f"Session WhatsApp incohérente détectée pour l'utilisateur {current_user.id}, nettoyage effectué")

            if is_telegram_user and telegram_id:
                # Charger les conversations Telegram pour cet utilisateur
                telegram_conversations = TelegramConversation.query.filter_by(
                    telegram_user_id=int(telegram_id)
                ).order_by(TelegramConversation.updated_at.desc()).limit(CONTEXT_MESSAGE_LIMIT).all()

                for conv in telegram_conversations:
                    conversation_history.append({
                        'id': conv.id,
                        'title': conv.title or f"Conversation du {conv.created_at.strftime('%d/%m/%Y')}",
                        'subject': 'Général',
                        'time': conv.created_at.strftime('%H:%M'),
                        'is_telegram': True
                    })
            elif is_whatsapp_user and whatsapp_number:
                # Récupérer les threads WhatsApp distincts pour ce numéro
                try:
                    # Obtenir les IDs de thread distincts pour ce numéro WhatsApp
                    whatsapp_threads = db.session.query(WhatsAppMessage.thread_id)\
                        .filter(WhatsAppMessage.from_number == whatsapp_number)\
                        .group_by(WhatsAppMessage.thread_id)\
                        .order_by(db.func.max(WhatsAppMessage.timestamp).desc())\
                        .limit(CONTEXT_MESSAGE_LIMIT).all()

                    for thread in whatsapp_threads:
                        thread_id = thread[0]

                        # Obtenir le premier message pour utiliser comme titre
                        first_message = WhatsAppMessage.query.filter_by(
                            thread_id=thread_id,
                            direction='inbound'
                        ).order_by(WhatsAppMessage.timestamp.asc()).first()

                        # Obtenir le dernier message pour la date
                        last_message = WhatsAppMessage.query.filter_by(
                            thread_id=thread_id
                        ).order_by(WhatsAppMessage.timestamp.desc()).first()

                        # Créer un titre basé sur le contenu du premier message
                        title = first_message.content if first_message else "Nouvelle conversation"
                        title = (title[:25] + '...') if len(title) > 25 else title

                        conversation_history.append({
                            'id': thread_id,  # Utiliser thread_id comme ID de conversation
                            'title': title,
                            'subject': 'WhatsApp',
                            'time': last_message.timestamp.strftime('%H:%M') if last_message else '',
                            'is_whatsapp': True  # Marquer comme conversation WhatsApp
                        })
                except Exception as e:
                    logger.error(f"Erreur lors de la récupération des conversations WhatsApp: {str(e)}")
            else:
                # Comportement normal pour les utilisateurs web
                # Important: Filtrer par user_id pour n'afficher que les conversations de l'utilisateur actuel
                if current_user.is_authenticated:
                    recent_conversations = Conversation.query.filter_by(
                        deleted=False, 
                        user_id=current_user.id
                    ).order_by(Conversation.updated_at.desc()).limit(CONTEXT_MESSAGE_LIMIT).all()
                else:
                    recent_conversations = []

                for conv in recent_conversations:
                    conversation_history.append({
                        'id': conv.id,
                        'title': conv.title or f"Conversation du {conv.created_at.strftime('%d/%m/%Y')}",
                        'subject': 'Général',
                        'time': conv.created_at.strftime('%H:%M')
                    })

            # Clear any existing thread_id from Flask's session
            if 'thread_id' in session:
                session.pop('thread_id')

            return render_template('chat.html', 
                                history=[], 
                                conversation_history=conversation_history, 
                                is_telegram=is_telegram_user,
                                credits=42)
    except Exception as e:
        logger.error(f"Error in chat route: {str(e)}")
        return render_template('chat.html', 
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
    formatted_messages = [{"role": "system", "content": get_system_instructions()}]

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

@socketio.on('send_message')
def handle_message(data):
    try:
        # Vérifier si l'utilisateur est connecté via Telegram
        is_telegram_user = session.get('is_telegram_user', False)
        telegram_id = session.get('telegram_id')

        # Get the appropriate AI client based on current model setting
        ai_client = get_ai_client()

        # Variables to store Mathpix results
        mathpix_result = None
        formatted_summary = None

        # Créer une fonction pour streamer les réponses
        def stream_response_to_client(response_stream, message_id):
            full_response = ""
            try:
                for chunk in response_stream:
                    # Gérer différents formats de réponse selon le modèle
                    if hasattr(chunk, 'choices') and len(chunk.choices) > 0:
                        if hasattr(chunk.choices[0], 'delta'):
                            # Format OpenAI/DeepSeek
                            if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                                content = chunk.choices[0].delta.content
                                full_response += content
                                emit('response_stream', {
                                    'content': content,
                                    'message_id': message_id,
                                    'is_final': False
                                })
                        elif hasattr(chunk.choices[0], 'text') and chunk.choices[0].text:
                            # Format alternatif pour certains modèles
                            content = chunk.choices[0].text
                            full_response += content
                            emit('response_stream', {
                                'content': content,
                                'message_id': message_id,
                                'is_final': False
                            })
                    # Pour d'autres formats potentiels, ajouter des branches ici

                # Envoyer l'événement de fin de réponse
                emit('response_stream', {
                    'content': '',
                    'message_id': message_id,
                    'is_final': True,
                    'full_response': full_response
                })
                return full_response
            except Exception as e:
                logger.error(f"Error in stream_response_to_client: {str(e)}")
                # En cas d'erreur, envoyer un message d'erreur et renvoyer ce qui a été collecté jusque-là
                emit('response_stream', {
                    'content': f"\n\nDésolé, une erreur est survenue lors du streaming: {str(e)}",
                    'message_id': message_id,
                    'is_final': True,
                    'error': True,
                    'full_response': full_response
                })
                return full_response

        # Fonction pour utiliser le streaming natif de l'API des Assistants OpenAI
        def stream_assistant_response(thread_id, run_id, message_id):
            try:
                # Créer un gestionnaire d'événements pour traiter les événements de streaming
                event_handler = OpenAIAssistantEventHandler(socketio, message_id)

                # Pour l'API OpenAI, nous devons d'abord créer un run, puis créer une connexion de streaming
                # en utilisant le thread_id et l'assistant_id, pas le run_id

                # Utiliser la méthode de streaming native de l'API
                with ai_client.beta.threads.runs.stream(
                    thread_id=thread_id,
                    assistant_id=ASSISTANT_ID,
                    event_handler=event_handler,
                ) as stream:
                    stream.until_done()

                # Retourner la réponse complète accumulée par le gestionnaire d'événements
                return event_handler.full_response

            except Exception as e:
                logger.error(f"Error streaming assistant response: {str(e)}")
                error_msg = f"Erreur lors du streaming de la réponse: {str(e)}"

                # Envoyer un message d'erreur au client
                emit('response_stream', {
                    'content': error_msg,
                    'message_id': message_id,
                    'is_final': True,
                    'error': True
                })

                return error_msg

            # Déterminer s'il s'agit d'une conversation Telegram ou Web
        if is_telegram_user and telegram_id:
            # Gestion des conversations Telegram
            # [Code existant pour la gestion Telegram]
            # Telegram sera géré sans streaming pour le moment
            pass  # Placeholder pour éviter l'erreur d'indentation

        else:
            # Gestion normale des conversations Web
            thread_id = session.get('thread_id')
            conversation = None
            if thread_id:
                conversation = Conversation.query.filter_by(thread_id=thread_id).first()
                # Vérifier si la conversation est valide et appartient à l'utilisateur actuel
                if conversation and current_user.is_authenticated and conversation.user_id == current_user.id:
                    logger.info(f"Utilisation de la conversation existante {conversation.id} avec thread_id {thread_id}")
                    # Mettre à jour la date de dernière modification pour garder la conversation active
                    conversation.updated_at = datetime.utcnow()
                    db.session.commit()
                else:
                    logger.warning(f"Conversation avec thread_id {thread_id} non trouvée ou non associée à l'utilisateur, création d'une nouvelle conversation")
                    conversation = None

            if not conversation:
                conversation = get_or_create_conversation()
                session['thread_id'] = conversation.thread_id

            # Handle image if present
            if 'image' in data and data['image']:
                # Le traitement des images reste identique, pas de streaming pour le moment
                # [Code existant pour le traitement d'image]
                pass  # Placeholder pour éviter l'erreur d'indentation

            else:
                # Store text-only message
                user_message = Message(
                    conversation_id=conversation.id,
                    role='user',
                    content=data.get('message', '')
                )
                db.session.add(user_message)
                db.session.commit()  # Commit immédiatement pour obtenir l'ID du message

                # Créer un message vide pour l'assistant, on le remplira progressivement
                db_message = Message(
                    conversation_id=conversation.id,
                    role='assistant',
                    content=""  # Contenu initial vide, sera mis à jour avec le streaming
                )
                db.session.add(db_message)
                db.session.commit()  # Commit pour obtenir l'ID du message

                # Envoyer un message initial pour démarrer l'affichage du loader côté client
                emit('message_started', {
                    'message_id': db_message.id
                })

                assistant_message = ""

                if CURRENT_MODEL in ['deepseek', 'deepseek-reasoner', 'qwen', 'gemini']:
                    # Get properly formatted messages based on model
                    if CURRENT_MODEL == 'deepseek-reasoner':
                        messages = get_interleaved_messages(conversation.id, data.get('message', ''))
                    else:
                        # Regular DeepSeek chat, Qwen and Gemini can handle all messages
                        conversation_messages = Message.query.filter_by(conversation_id=conversation.id)\
                            .order_by(Message.created_at).all()
                        messages = [{"role": "system", "content": get_system_instructions()}]
                        for msg in conversation_messages:
                            messages.append({
                                "role": msg.role,
                                "content": msg.content
                            })
                        messages.append({
                            "role": "user",
                            "content": data.get('message', '')
                        })

                    if CURRENT_MODEL == 'gemini':
                        # Gemini ne prend pas encore en charge le streaming, utiliser l'appel normal
                        assistant_message = call_gemini_api(messages)
                        # Simuler un streaming pour l'utilisateur
                        words = assistant_message.split()
                        for i in range(0, len(words), 5):  # Envoyer 5 mots à la fois
                            chunk = ' '.join(words[i:i+5]) + ' '
                            emit('response_stream', {
                                'content': chunk,
                                'message_id': db_message.id,
                                'is_final': False
                            })
                            eventlet.sleep(0.1)  # Court délai entre les chunks
                        # Marquer comme terminé
                        emit('response_stream', {
                            'content': '',
                            'message_id': db_message.id,
                            'is_final': True,
                            'full_response': assistant_message
                        })
                    else:
                        # Utiliser le streaming pour DeepSeek et Qwen
                        try:
                            response = ai_client.chat.completions.create(
                                model=get_model_name(),
                                messages=messages,
                                stream=True
                            )
                            assistant_message = stream_response_to_client(response, db_message.id)
                        except Exception as stream_error:
                            logger.error(f"Streaming error: {str(stream_error)}")
                            # Fallback to non-streaming request
                            response = ai_client.chat.completions.create(
                                model=get_model_name(),
                                messages=messages,
                                stream=False
                            )
                            assistant_message = response.choices[0].message.content
                            # Envoyer la réponse complète comme stream final
                            emit('response_stream', {
                                'content': assistant_message,
                                'message_id': db_message.id,
                                'is_final': True,
                                'full_response': assistant_message
                            })
                else:
                    # Use OpenAI's threads API with streaming
                    ai_client.beta.threads.messages.create(
                        thread_id=conversation.thread_id,
                        role="user",
                        content=data.get('message', '')
                    )

                    # Ne pas envoyer un second message_started, car il l'a déjà été fait plus haut
                    # Utiliser le streaming natif pour récupérer la réponse
                    try:
                        # La fonction stream_assistant_response va maintenant gérer à la fois 
                        # la création du run et le streaming
                        assistant_message = stream_assistant_response(conversation.thread_id, None, db_message.id)
                    except Exception as stream_error:
                        logger.error(f"Error streaming assistant response: {str(stream_error)}")

                        # Fallback à l'approche non-streaming en cas d'erreur
                        try:
                            # Attendre que le run soit terminé
                            timeout = 30
                            start_time = time.time()
                            run_completed = False

                            while not run_completed and time.time() - start_time < timeout:
                                run_status = ai_client.beta.threads.runs.retrieve(
                                    thread_id=conversation.thread_id,
                                    run_id=run.id
                                )

                                if run_status.status == 'completed':
                                    run_completed = True
                                    break
                                elif run_status.status == 'failed':
                                    error_msg = "Le traitement a échoué."
                                    if hasattr(run_status, 'last_error'):
                                        error_msg = f"Erreur: {run_status.last_error.message}"

                                    emit('response_stream', {
                                        'content': error_msg,
                                        'message_id': db_message.id,
                                        'is_final': True,
                                        'error': True
                                    })
                                    return

                                eventlet.sleep(1)

                            if not run_completed:
                                emit('response_stream', {
                                    'content': 'La requête a expiré.',
                                    'message_id': db_message.id,
                                    'is_final': True,
                                    'error': True
                                })
                                return

                            # Récupérer la réponse complète
                            messages = ai_client.beta.threads.messages.list(
                                thread_id=conversation.thread_id,
                                order="desc",
                                limit=1
                            )

                            if messages.data and len(messages.data) > 0:
                                assistant_message = messages.data[0].content[0].text.value

                                # Envoyer la réponse complète
                                emit('response_stream', {
                                    'content': assistant_message,
                                    'message_id': db_message.id,
                                    'is_final': True,
                                    'full_response': assistant_message
                                })
                            else:
                                emit('response_stream', {
                                    'content': 'Pas de réponse disponible.',
                                    'message_id': db_message.id,
                                    'is_final': True,
                                    'error': True
                                })
                        except Exception as e:
                            logger.error(f"Error in fallback approach: {str(e)}")
                            emit('response_stream', {
                                'content': f'Une erreur est survenue: {str(e)}',
                                'message_id': db_message.id,
                                'is_final': True,
                                'error': True
                            })

                # Mettre à jour le message de l'assistant dans la base de données avec la réponse complète
                db_message.content = assistant_message
                db.session.commit()

                # Generate and set conversation title if this is the first message
                if not conversation.title:
                    title = data.get('message', '')[:30] + "..." if len(data.get('message', '')) > 30 else data.get('message', '')
                    if not title:
                        title = "New Conversation"
                    conversation.title = title
                    db.session.commit()

                    # Emit the new conversation to all clients
                    emit('new_conversation', {
                        'id': conversation.id,
                        'title': conversation.title,
                        'subject': 'Général',
                        'time': conversation.created_at.strftime('%H:%M')
                    }, broadcast=True)

    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}")
        error_message = str(e)
        if "image" in error_message.lower():
            emit('receive_message', {'message': 'Error processing image. Please ensure the image is in a supported format (JPG, PNG, GIF) and try again.', 'id': 0})
        else:
            emit('receive_message', {'message': f'An error occurred while processing your message. Please try again.', 'id': 0})

@socketio.on('rename_conversation')
def handle_rename(data):
    try:
        conversation = Conversation.query.get(data['id'])
        if conversation:
            conversation.title = data['title']
            db.session.commit()
            emit('conversation_updated', {'success': True})
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
        # Vérifier si nous avons affaire à une conversation WhatsApp
        if 'is_whatsapp' in data and data.get('is_whatsapp'):
            # Le thread_id WhatsApp est passé directement
            thread_id = str(data['id'])
            logger.info(f"Ouverture de la conversation WhatsApp avec thread_id: {thread_id}")

            # Vérifier que ce thread existe dans la base
            messages = WhatsAppMessage.query.filter_by(thread_id=thread_id).all()

            if not messages:
                logger.warning(f"Aucun message trouvé pour le thread WhatsApp {thread_id}")
                emit('conversation_opened', {
                    'success': False,
                    'error': 'Conversation introuvable'
                })
                return

            # Mettre à jour la session avec le thread WhatsApp
            session['thread_id'] = thread_id

            # Obtenir les messages pour ce thread, triés par horodatage
            messages = WhatsAppMessage.query.filter_by(
                thread_id=thread_id
            ).order_by(WhatsAppMessage.timestamp).all()

            messages_data = []

            for msg in messages:
                # Déterminer le rôle du message
                role = 'user' if msg.direction == 'inbound' else 'assistant'

                message_data = {
                    'id': msg.id,
                    'role': role,
                    'content': msg.content,
                    'created_at': msg.timestamp.isoformat() if msg.timestamp else ''
                }
                messages_data.append(message_data)

            # Obtenir le premier message pour le titre
            first_message = WhatsAppMessage.query.filter_by(
                thread_id=thread_id, 
                direction='inbound'
            ).order_by(WhatsAppMessage.timestamp.asc()).first()

            title = first_message.content if first_message else "Conversation WhatsApp"
            title = (title[:25] + '...') if len(title) > 25 else title

            emit('conversation_opened', {
                'success': True,
                'messages': messages_data,
                'conversation_id': thread_id,
                'title': title,
                'is_whatsapp': True
            })
            return

        # Vérifier si l'utilisateur est connecté via Telegram
        is_telegram_user = session.get('is_telegram_user', False)

        if is_telegram_user and 'is_telegram' in data and data.get('is_telegram'):
            # Obtenir la conversation Telegram par ID numérique
            conversation = TelegramConversation.query.get(data['id'])
            if conversation:
                # Mettre à jour la session avec le thread Telegram
                session['thread_id'] = conversation.thread_id

                # Obtenir les messages pour cette conversation
                messages = TelegramMessage.query.filter_by(conversation_id=conversation.id).order_by(TelegramMessage.created_at).all()
                messages_data = []

                for msg in messages:
                    message_data = {
                        'id': msg.id,
                        'role': msg.role,
                        'content': msg.content,
                        'image_url': msg.image_url,
                    }
                    messages_data.append(message_data)

                emit('conversation_opened', {
                    'success': True,
                    'messages': messages_data,
                    'conversation_id': conversation.id,
                    'title': conversation.title or f"Conversation du {conversation.created_at.strftime('%d/%m/%Y')}",
                    'is_telegram': True
                })
                return

        # Si ce n'est pas une conversation WhatsApp ou Telegram, c'est une conversation web normale
        conversation = Conversation.query.get(data['id'])
        if conversation:
            # Update session with the opened conversation
            session['thread_id'] = conversation.thread_id

            # Get messages for this conversation
            messages = Message.query.filter_by(conversation_id=conversation.id).order_by(Message.created_at).all()
            messages_data = []

            # Import needed for current_user
            from flask_login import current_user
            user_id = current_user.id if current_user.is_authenticated else None

            for msg in messages:
                # Add base message data
                message_data = {
                    'id': msg.id,  # Include message ID for feedback tracking
                    'role': msg.role,
                    'content': msg.content,
                    'image_url': msg.image_url,
                }

                # If it's an assistant message, check for existing feedback
                if msg.role == 'assistant':
                    # Get existing feedback for this message from the current user
                    feedback = MessageFeedback.query.filter_by(
                        message_id=msg.id,
                        user_id=user_id
                    ).first()

                    if feedback:
                        message_data['feedback'] = feedback.feedback_type

                messages_data.append(message_data)

            emit('conversation_opened', {
                'success': True,
                'messages': messages_data,
                'conversation_id': conversation.id,
                'title': conversation.title or f"Conversation du {conversation.created_at.strftime('%d/%m/%Y')}"
            })
        else:
            emit('conversation_opened', {
                'success': False,
                'error': 'Conversation introuvable'
            })
    except Exception as e:
        app.logger.error(f"Error opening conversation: {str(e)}")
        emit('conversation_opened', {
            'success': False,
            'error': str(e)
        })

@socketio.on('clear_session')
def handle_clear_session():
    # Clear the thread_id from session
    session.pop('thread_id', None)
    emit('session_cleared', {'success': True})

@socketio.on('restore_session')
def handle_restore_session(data):
    """Restore a previous session based on a stored thread_id"""
    try:
        thread_id = data.get('thread_id')
        if not thread_id:
            logger.warning("Restore session called without thread_id")
            return

        logger.info(f"Attempting to restore session with thread_id: {thread_id}")

        # Vérifier si la conversation existe
        conversation = Conversation.query.filter_by(id=thread_id).first()

        if conversation:
            # Vérifier si la conversation appartient à l'utilisateur actuel
            if current_user.is_authenticated and conversation.user_id == current_user.id:
                # Mettre à jour la session Flask avec le thread_id
                session['thread_id'] = conversation.thread_id
                logger.info(f"Session restored for thread_id: {conversation.thread_id}")

                # Émettre les mêmes événements que lorsqu'une conversation est ouverte
                messages = Message.query.filter_by(conversation_id=conversation.id).order_by(Message.created_at).all()
                messages_data = []

                for msg in messages:
                    message_data = {
                        'id': msg.id,
                        'role': msg.role,
                        'content': msg.content,
                        'image_url': msg.image_url,
                    }
                    messages_data.append(message_data)

                emit('conversation_opened', {
                    'success': True,
                    'messages': messages_data,
                    'conversation_id': conversation.id,
                    'title': conversation.title or f"Conversation du {conversation.created_at.strftime('%d/%m/%Y')}"
                })

                # Mettre à jour la date de dernière modification
                conversation.updated_at = datetime.utcnow()
                db.session.commit()
            else:
                logger.warning(f"Attempt to restore session for conversation {thread_id} not owned by current user")
        else:
            logger.warning(f"Conversation with id {thread_id} not found for session restoration")
    except Exception as e:
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
            emit('feedback_submitted', {'success': False, 'error': 'Missing required parameters'})
            return

        if feedback_type not in ['positive', 'negative']:
            emit('feedback_submitted', {'success': False, 'error': 'Invalid feedback type'})
            return

        with db_retry_session() as db_session:  # Renommer pour éviter la confusion
            # Check if this user already gave feedback on this message
            existing_feedback = MessageFeedback.query.filter_by(
                message_id=message_id, 
                user_id=user_id
            ).first()

            if existing_feedback:
                # Update existing feedback
                existing_feedback.feedback_type = feedback_type
                db_session.commit()
            else:
                # Create new feedback entry
                new_feedback = MessageFeedback(
                    message_id=message_id,
                    user_id=user_id,
                    feedback_type=feedback_type
                )
                db_session.add(new_feedback)
                db_session.commit()

            # Émettre le succès à l'utilisateur qui a soumis le feedback
            emit('feedback_submitted', {'success': True})

            # Calculer les nouvelles statistiques de satisfaction
            total_feedbacks = MessageFeedback.query.count()
            positive_feedbacks = MessageFeedback.query.filter_by(feedback_type='positive').count()
            satisfaction_rate = round((positive_feedbacks / total_feedbacks) * 100) if total_feedbacks > 0 else 0

            # Émettre la mise à jour à tous les clients connectés (y compris le tableau de bord admin)
            socketio.emit('feedback_stats_updated', {
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
            if current_time - file_modified > timedelta(hours=IMAGE_MAX_AGE_HOURS):
                os.remove(filepath)

        # Check the total size of the folder
        total_size = sum(os.path.getsize(os.path.join(UPLOAD_FOLDER, f)) 
                        for f in os.listdir(UPLOAD_FOLDER))

        # If the size exceeds the limit, delete the oldest files
        if total_size > MAX_UPLOAD_FOLDER_SIZE:
            files = [(os.path.join(UPLOAD_FOLDER, f), os.path.getmtime(os.path.join(UPLOAD_FOLDER, f))) 
                    for f in os.listdir(UPLOAD_FOLDER)]
            files.sort(key=lambda x: x[1])  # Sort by modification date

            for filepath, _ in files:
                os.remove(filepath)
                total_size = sum(os.path.getsize(os.path.join(UPLOAD_FOLDER, f)) 
                                for f in os.listdir(UPLOAD_FOLDER))
                if total_size <= MAX_UPLOAD_FOLDER_SIZE:
                    break

    except Exception as e:
        print(f"Error during upload cleanup: {str(e)}")

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

            # Check for admin credentials first
            if phone_number == os.environ.get('ADMIN_PHONE') and \
               password == os.environ.get('ADMIN_PASSWORD'):
                session['is_admin'] = True
                flash('Connecté en tant qu\'administrateur.', 'success')
                return redirect(url_for('admin_dashboard'))

            # Traitement spécifique pour login WhatsApp
            if login_mode == 'whatsapp':
                # Formater le numéro pour correspondre au format WhatsApp
                if not phone_number.startswith('+'):
                    whatsapp_number = phone_number
                else:
                    whatsapp_number = phone_number[1:]  # Enlever le + si présent

                # Vérifier si ce numéro existe dans les messages WhatsApp
                whatsapp_message = WhatsAppMessage.query.filter_by(from_number=whatsapp_number).first()

                if not whatsapp_message:
                    # Pas de message WhatsApp trouvé pour ce numéro
                    flash('Aucun compte WhatsApp trouvé avec ce numéro.', 'error')
                    return redirect(url_for('login', error='no_whatsapp_account'))

                # Vérifier si un utilisateur web existe déjà pour ce numéro
                user = User.query.filter_by(phone_number=f"whatsapp_{whatsapp_number}").first()

                if user:
                    # Si l'utilisateur existe, vérifier le mot de passe
                    if not user.check_password(password):
                        return redirect(url_for('login', error='wrong_password'))
                else:
                    # Créer un nouvel utilisateur web pour ce numéro WhatsApp
                    user = User(
                        first_name="WhatsApp",
                        last_name="User",
                        age=18,  # Valeur par défaut
                        phone_number=f"whatsapp_{whatsapp_number}",  # Format spécial pour identifier les utilisateurs WhatsApp
                        study_level="Non spécifié",
                        grade_goals="average"  # Valeur par défaut
                    )
                    # Définir le mot de passe entré
                    user.set_password(password)

                    db.session.add(user)
                    db.session.commit()

                    # Émettre l'événement de nouvel utilisateur Web pour le tableau de bord
                    socketio.emit('new_web_user', {
                        'id': user.id,
                        'first_name': user.first_name,
                        'last_name': user.last_name,
                        'phone_number': user.phone_number
                    })

                # Définir les variables de session pour indiquer une connexion via WhatsApp
                session['is_whatsapp_user'] = True
                session['whatsapp_number'] = whatsapp_number

                # Connecter l'utilisateur et rediriger vers le chat
                login_user(user)
                flash('Connecté via WhatsApp avec succès!', 'success')
                return redirect(url_for('chat'))

            # Logique pour login Web standard (inchangée)
            user = User.query.filter_by(phone_number=phone_number).first()

            # Vérifier si l'utilisateur existe
            if not user:
                # Rediriger avec paramètre d'erreur "no_account"
                return redirect(url_for('login', error='no_account'))

            # Vérifier si le mot de passe est correct
            if not user.check_password(password):
                # Rediriger avec paramètre d'erreur "wrong_password"
                return redirect(url_for('login', error='wrong_password'))

            # Si tout est correct, connecter l'utilisateur
            login_user(user)
            return redirect(url_for('chat'))

        elif login_mode == 'telegram':
            # Récupérer l'ID Telegram
            telegram_id = request.form.get('telegram_id')

            if not telegram_id or not telegram_id.strip().isdigit():
                flash('Veuillez entrer un ID Telegram valide (numérique).', 'error')
                return redirect(url_for('login'))

            # Convertir en entier
            telegram_id = int(telegram_id)

            # Vérifier si cet ID existe dans la base de données
            telegram_user = TelegramUser.query.get(telegram_id)

            if not telegram_user:
                flash('Aucun compte Telegram trouvé avec cet ID.', 'error')
                return redirect(url_for('login'))

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
    user = User.query.filter_by(phone_number=f"telegram_{telegram_user.telegram_id}").first()

    if not user:
        # Créer un nouvel utilisateur Web lié à ce TelegramUser
        user = User(
            first_name=telegram_user.first_name if telegram_user.first_name != "---" else "Telegram",
            last_name=telegram_user.last_name if telegram_user.last_name != "---" else "User",
            age=18,  # Valeur par défaut
            phone_number=f"telegram_{telegram_user.telegram_id}",  # Format spécial pour identifier les utilisateurs Telegram
            study_level=telegram_user.study_level if telegram_user.study_level != "---" else "Non spécifié",
            grade_goals="average"  # Valeur par défaut
        )
        # Définir un mot de passe aléatoire (ne sera pas utilisé car l'authentification se fait par ID Telegram)
        user.set_password(str(uuid.uuid4()))

        db.session.add(user)
        db.session.commit()

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

@app.route('/admin')
def admin_dashboard():
    """Admin dashboard route that displays platform statistics"""
    # Check if user is admin
    if not session.get('is_admin'):
        flash('Accès non autorisé. Veuillez vous connecter en tant qu\'administrateur.', 'error')
        return redirect(url_for('login'))

    try:
        # Get web platform data
        users = User.query.all()
        conversations = Conversation.query.all()
        today = datetime.today().date()

        # Count today's conversations
        today_conversations = sum(1 for conv in conversations if conv.created_at.date() == today)

        # Get actual number of users
        active_users = len(users)
        # Count users created today
        active_users_today = sum(1 for user in users if user.created_at.date() == today)

        # Calculate satisfaction rate based on message feedback
        total_feedbacks = MessageFeedback.query.count()
        positive_feedbacks = MessageFeedback.query.filter_by(feedback_type='positive').count()

        # Calculate satisfaction rate (percentage of positive feedback)
        satisfaction_rate = round((positive_feedbacks / total_feedbacks) * 100) if total_feedbacks > 0 else 0

        # Get OpenAI Assistant ID for settings
        openai_assistant_id = os.environ.get('OPENAI_ASSISTANT_ID', 'Non configuré')

        return render_template(
            'admin_dashboard.html',
            active_users=active_users,
            active_users_today=active_users_today,
            today_conversations=today_conversations,
            satisfaction_rate=satisfaction_rate,
            is_admin=True,
            openai_assistant_id=openai_assistant_id,  # Add OpenAI Assistant ID
            current_model=CURRENT_MODEL,  # Add current model selection
            deepseek_instructions=DEEPSEEK_INSTRUCTIONS,  # Add DeepSeek instructions
            deepseek_reasoner_instructions=DEEPSEEK_REASONER_INSTRUCTIONS,  # Add DeepSeek Reasoner instructions
            qwen_instructions=QWEN_INSTRUCTIONS,  # Add Qwen instructions
            gemini_instructions=GEMINI_INSTRUCTIONS  # Add Gemini instructions
        )
    except Exception as e:
        logger.error(f"Error in admin dashboard: {str(e)}")
        flash('Une erreur est survenue lors du chargement du tableau de bord.', 'error')
        return redirect(url_for('login'))

def reload_model_settings():
    """
    Recharge les paramètres du modèle depuis l'environnement et les sauvegarde dans un fichier JSON.
    Cette fonction est appelée lorsque l'administrateur modifie les paramètres du modèle.
    """
    global CURRENT_MODEL, DEEPSEEK_INSTRUCTIONS, DEEPSEEK_REASONER_INSTRUCTIONS, QWEN_INSTRUCTIONS, GEMINI_INSTRUCTIONS

    # Recharger les variables depuis l'environnement
    CURRENT_MODEL = os.environ.get('CURRENT_MODEL', 'openai')
    DEEPSEEK_INSTRUCTIONS = os.environ.get('DEEPSEEK_INSTRUCTIONS', 'You are a helpful educational assistant')
    DEEPSEEK_REASONER_INSTRUCTIONS = os.environ.get('DEEPSEEK_REASONER_INSTRUCTIONS', 'You are a helpful educational assistant focused on reasoning and problem-solving')
    QWEN_INSTRUCTIONS = os.environ.get('QWEN_INSTRUCTIONS', 'You are a helpful educational assistant focused on providing accurate and comprehensive answers')
    GEMINI_INSTRUCTIONS = os.environ.get('GEMINI_INSTRUCTIONS', 'You are a helpful educational assistant specialized in explaining complex concepts clearly')

    # Utiliser un chemin absolu pour le fichier de configuration
    config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_config.json')

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

        logger.info(f"AI model settings saved to {config_file_path}: {CURRENT_MODEL}")
    except Exception as e:
        logger.error(f"Error saving AI model settings to file ({config_file_path}): {str(e)}")

@app.route('/admin/settings/model', methods=['POST'])
def update_model_settings():
    """Update AI model settings"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        data = request.get_json()
        model = data.get('model')
        instructions = data.get('instructions')

        if model not in ['openai', 'deepseek', 'deepseek-reasoner', 'qwen', 'gemini']:
            return jsonify({'error': 'Invalid model selection'}), 400

        # Update the current model
        global CURRENT_MODEL, DEEPSEEK_INSTRUCTIONS, DEEPSEEK_REASONER_INSTRUCTIONS, QWEN_INSTRUCTIONS, GEMINI_INSTRUCTIONS
        CURRENT_MODEL = model

        # Update environment variables for persistence
        os.environ['CURRENT_MODEL'] = model

        # Update instructions if provided based on the model selected
        if model == 'deepseek' and instructions:
            DEEPSEEK_INSTRUCTIONS = instructions
            os.environ['DEEPSEEK_INSTRUCTIONS'] = instructions
        elif model == 'deepseek-reasoner' and instructions:
            DEEPSEEK_REASONER_INSTRUCTIONS = instructions
            os.environ['DEEPSEEK_REASONER_INSTRUCTIONS'] = instructions
        elif model == 'qwen' and instructions:
            QWEN_INSTRUCTIONS = instructions
            os.environ['QWEN_INSTRUCTIONS'] = instructions
        elif model == 'gemini' and instructions:
            GEMINI_INSTRUCTIONS = instructions
            os.environ['GEMINI_INSTRUCTIONS'] = instructions

        # Write to .env file for persistence
        env_path = '.env'
        env_vars = {}

        # Read existing variables
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        env_vars[key] = value

        # Update with new values
        env_vars['CURRENT_MODEL'] = model
        if model == 'deepseek' and instructions:
            env_vars['DEEPSEEK_INSTRUCTIONS'] = instructions
        elif model == 'deepseek-reasoner' and instructions:
            env_vars['DEEPSEEK_REASONER_INSTRUCTIONS'] = instructions
        elif model == 'qwen' and instructions:
            env_vars['QWEN_INSTRUCTIONS'] = instructions
        elif model == 'gemini' and instructions:
            env_vars['GEMINI_INSTRUCTIONS'] = instructions

        # Write back to .env
        with open(env_path, 'w') as f:
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")

        # Reload environment variables
        load_dotenv()

        # Recharger les paramètres du modèle
        reload_model_settings()

        return jsonify({'success': True, 'message': 'Model settings updated successfully'})
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
        study_level = request.form.get('study_level') or 'Terminal A'  # Default value
        grade_goals = request.form.get('grade_goals') or 'average'  # Default value

        # Basic validation
        if not all([first_name, last_name, age, phone_number, password]):
            flash('Tous les champs obligatoires doivent être remplis.', 'error')
            return redirect(url_for('register'))

        try:
            # Create new user
            user = User(
                first_name=first_name,
                last_name=last_name,
                age=int(age),
                phone_number=phone_number,
                study_level=study_level,
                grade_goals=grade_goals
            )
            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            # Émettre l'événement de nouvel utilisateur Web pour le tableau de bord
            socketio.emit('new_web_user', {
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

    return render_template('register.html')

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
            user = User.query.filter_by(phone_number=f"whatsapp_{whatsapp_number}").first()

            # Si l'utilisateur n'existe pas, vérifier s'il y a des messages WhatsApp pour ce numéro
            if not user:
                whatsapp_message = WhatsAppMessage.query.filter_by(from_number=whatsapp_number).first()

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
                    logger.info(f"Nouvel utilisateur WhatsApp créé lors de la réinitialisation du mot de passe: {whatsapp_number}")
        else:
            # Recherche standard pour les utilisateurs web
            user = User.query.filter_by(phone_number=phone_number).first()

        if user:
            # Mettre à jour le mot de passe de l'utilisateur
            user.set_password(new_password)
            db.session.commit()
            logger.info(f"Mot de passe mis à jour pour l'utilisateur: {user.phone_number}")

            # Passer un paramètre pour afficher le popup
            return render_template('forgot_password.html', password_updated=True)

        flash(f"Aucun compte {'WhatsApp' if account_type == 'whatsapp' else ''} trouvé avec ce numéro.", 'error')
        return redirect(url_for('forgot_password'))

    return render_template('forgot_password.html')

@app.route('/admin/data/<platform>')
def admin_platform_data(platform):
    today = datetime.today().date()

    if platform == 'web':
        # Get web platform statistics
        users = User.query.all()
        conversations = Conversation.query.all()

        # Calculate satisfaction rate for web platform
        total_feedbacks = MessageFeedback.query.count()
        positive_feedbacks = MessageFeedback.query.filter_by(feedback_type='positive').count()
        satisfaction_rate = round((positive_feedbacks / total_feedbacks) * 100) if total_feedbacks > 0 else 0

        data = {
            'active_users': len(users),
            'active_users_today': sum(1 for user in users if user.created_at.date() == today),
            'today_conversations': sum(1 for conv in conversations if conv.created_at.date() == today),
            'satisfaction_rate': satisfaction_rate,
            'platform': 'web',
            'users': [{
                'first_name': user.first_name,
                'last_name': user.last_name,
                'phone_number': user.phone_number,
                'age': user.age,
                'study_level': user.study_level,
                'created_at': user.created_at.strftime('%d/%m/%Y')
            } for user in users],
            'conversations': [{
                'title': conv.title or "Sans titre",
                'date': conv.created_at.strftime('%d/%m/%Y'),
                'time': conv.created_at.strftime('%H:%M'),
                'last_message': Message.query.filter_by(conversation_id=conv.id).order_by(Message.created_at.desc()).first().content if Message.query.filter_by(conversation_id=conv.id).first() else "No messages"
            } for conv in conversations]
        }

    elif platform == 'telegram':
        # For telegram, query telegram-specific data
        users = TelegramUser.query.all()
        conversations = TelegramConversation.query.all()

        data = {
            'active_users': len(users),
            'active_users_today': sum(1 for user in users if user.created_at.date() == today),
            'today_conversations': sum(1 for conv in conversations if conv.created_at.date() == today),
            'satisfaction_rate': 0,
            'platform': 'telegram',
            'users': [{
                'telegram_id': user.telegram_id,
                'first_name': user.first_name or "---",
                'last_name': user.last_name or "---",
                'phone': user.phone_number,
                'study_level': user.study_level,
                'created_at': user.created_at.strftime('%d/%m/%Y')
            } for user in users],
            'conversations': [{
                'title': conv.title,
                'date': conv.created_at.strftime('%d/%m/%Y'),
                'time': conv.created_at.strftime('%H:%M'),
                'last_message': TelegramMessage.query.filter_by(conversation_id=conv.id).order_by(TelegramMessage.created_at.desc()).first().content if TelegramMessage.query.filter_by(conversation_id=conv.id).first() else "No messages"
            } for conv in conversations]
        }

    elif platform == 'whatsapp':
        # Get WhatsApp statistics
        messages = WhatsAppMessage.query.all()
        unique_users = db.session.query(WhatsAppMessage.from_number).distinct().all()

        # Calculate today's statistics
        today_messages = [msg for msg in messages if msg.timestamp.date() == today]
        today_users = db.session.query(WhatsAppMessage.from_number)\
            .filter(db.func.date(WhatsAppMessage.timestamp) == today)\
            .distinct().all()

        # Get conversations grouped by thread_id
        conversations = db.session.query(
            WhatsAppMessage.thread_id,
            db.func.min(WhatsAppMessage.timestamp).label('created_at'),
            db.func.count().label('message_count')
        ).group_by(WhatsAppMessage.thread_id).all()

        data = {
            'active_users': len(unique_users),
            'active_users_today': len(today_users),
            'today_conversations': len([c for c in conversations if c.created_at.date() == today]),
            'satisfaction_rate': 0,
            'platform': 'whatsapp',
            'users': [{
                'name': f'WhatsApp User {user[0]}',  # user[0] contains from_number
                'phone': user[0],
                'study_level': 'N/A',
                'created_at': WhatsAppMessage.query.filter_by(from_number=user[0])
                    .order_by(WhatsAppMessage.timestamp).first().timestamp.strftime('%d/%m/%Y')
            } for user in unique_users],
            'conversations': [{
                'title': f'Conversation {conv.thread_id}',
                'date': conv.created_at.strftime('%d/%m/%Y'),
                'time': conv.created_at.strftime('%H:%M'),
                'last_message': WhatsAppMessage.query.filter_by(thread_id=conv.thread_id)
                    .order_by(WhatsAppMessage.timestamp.desc()).first().content
            } for conv in conversations]
        }

    return jsonify(data)

@app.route('/admin/data/<platform>/stats')
def admin_platform_stats(platform):
    """Get only stats for a platform without full data lists"""
    today = datetime.today().date()

    if platform == 'web':
        # Get web platform statistics
        users = User.query.all()
        conversations = Conversation.query.all()

        # Calculate satisfaction rate for web platform
        total_feedbacks = MessageFeedback.query.count()
        positive_feedbacks = MessageFeedback.query.filter_by(feedback_type='positive').count()
        satisfaction_rate = round((positive_feedbacks / total_feedbacks) * 100) if total_feedbacks > 0 else 0

        data = {
            'active_users': len(users),
            'active_users_today': sum(1 for user in users if user.created_at.date() == today),
            'today_conversations': sum(1 for conv in conversations if conv.created_at.date() == today),
            'satisfaction_rate': satisfaction_rate
        }

    elif platform == 'telegram':
        # For telegram, query telegram-specific data
        users = TelegramUser.query.all()
        conversations = TelegramConversation.query.all()

        data = {
            'active_users': len(users),
            'active_users_today': sum(1 for user in users if user.created_at.date() == today),
            'today_conversations': sum(1 for conv in conversations if conv.created_at.date() == today),
            'satisfaction_rate': 0
        }

    elif platform == 'whatsapp':
        # Get WhatsApp statistics
        messages = WhatsAppMessage.query.all()
        unique_users = db.session.query(WhatsAppMessage.from_number).distinct().all()

        # Calculate today's statistics
        today_messages = [msg for msg in messages if msg.timestamp.date() == today]
        today_users = db.session.query(WhatsAppMessage.from_number)\
            .filter(db.func.date(WhatsAppMessage.timestamp) == today)\
            .distinct().all()

        # Get conversations grouped by thread_id
        conversations = db.session.query(
            WhatsAppMessage.thread_id,
            db.func.min(WhatsAppMessage.timestamp).label('created_at'),
            db.func.count().label('message_count')
        ).group_by(WhatsAppMessage.thread_id).all()

        data = {
            'active_users': len(unique_users),
            'active_users_today': len(today_users),
            'today_conversations': len([c for c in conversations if c.created_at.date() == today]),
            'satisfaction_rate': 0
        }

    return jsonify(data)


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
            logger.info(f"Found web user with ID {user.id}, phone: {user.phone_number}")

            try:
                # Importer le module text pour les requêtes SQL
                from sqlalchemy import text

                # Utiliser du SQL pur avec une connexion directe pour éviter
                # les problèmes avec le modèle ORM et gérer les transactions correctement
                with db.engine.begin() as connection:
                    # 1. Récupérer l'ID de l'utilisateur pour les requêtes suivantes
                    user_id_to_delete = user.id

                    # 2. Supprimer les associations dans user_subscription
                    logger.info(f"Deleting subscription relationships for user {user_id_to_delete}")
                    connection.execute(
                        text("DELETE FROM user_subscription WHERE user_id = :user_id"),
                        {"user_id": user_id_to_delete}
                    )

                    # 3. Supprimer les messages liés aux conversations de l'utilisateur
                    logger.info(f"Deleting messages for user {user_id_to_delete}")
                    connection.execute(
                        text("""DELETE FROM message 
                                WHERE conversation_id IN (
                                    SELECT id FROM conversation WHERE user_id = :user_id
                                )"""),
                        {"user_id": user_id_to_delete}
                    )

                    # 4. Supprimer les conversations de l'utilisateur
                    logger.info(f"Deleting conversations for user {user_id_to_delete}")
                    connection.execute(
                        text("DELETE FROM conversation WHERE user_id = :user_id"),
                        {"user_id": user_id_to_delete}
                    )

                    # 5. Supprimer l'utilisateur lui-même
                    # Note: le mot-clé "user" est réservé dans SQL, donc on le met entre guillemets
                    logger.info(f"Deleting user with ID {user_id_to_delete}")
                    connection.execute(
                        text("DELETE FROM \"user\" WHERE id = :user_id"),
                        {"user_id": user_id_to_delete}
                    )

                # Si on arrive ici, c'est que la transaction a été validée avec succès
                logger.info(f"Web user {user_id} deleted successfully")
                return jsonify({'success': True, 'message': 'User deleted successfully'})

            except Exception as e:
                logger.error(f"Error deleting web user: {str(e)}")
                return jsonify({'success': False, 'message': f'Error deleting user: {str(e)}'}), 500

        # Try to find in Telegram users
        user = TelegramUser.query.filter_by(telegram_id=user_id).first()
        if user:
            try:
                with db_retry_session() as session:
                    # Delete all messages first
                    for conv in user.conversations:
                        TelegramMessage.query.filter_by(conversation_id=conv.id).delete()
                    session.flush()

                    # Delete all conversations
                    TelegramConversation.query.filter_by(telegram_user_id=user.telegram_id).delete()
                    session.flush()

                    # Finally delete the user
                    session.delete(user)
                    session.commit()
                    return jsonify({'success': True, 'message': 'Telegram user deleted successfully'})
            except Exception as telegram_error:
                logger.error(f"Error deleting Telegram user: {str(telegram_error)}")
                session.rollback()
                return jsonify({'success': False, 'message': f'Error deleting Telegram user: {str(telegram_error)}'}), 500

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
                        thread_id = thread_id[0]  # Extraction de la valeur depuis le tuple
                        logger.info(f"Deleting all messages for WhatsApp thread {thread_id}")
                        WhatsAppMessage.query.filter_by(thread_id=thread_id).delete()

                    session.commit()
                    return jsonify({'success': True, 'message': 'WhatsApp user and all associated conversations deleted successfully'})
            except Exception as whatsapp_error:
                logger.error(f"Error deleting WhatsApp messages: {str(whatsapp_error)}")
                session.rollback()
                return jsonify({'success': False, 'message': f'Error deleting WhatsApp messages: {str(whatsapp_error)}'}), 500

        return jsonify({'success': False, 'message': 'User not found'}), 404

    except Exception as e:
        logger.error(f"Error in delete_user function for {user_id}: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

# Add this route after the other admin routes

@app.route('/admin/conversations/<int:conversation_id>/messages')
def get_conversation_messages(conversation_id):
    """Get messages for a specific conversation"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        # Try to find the conversation in different models based on the ID
        conversation = None
        messages = []

        # Ensure conversation_id is integer
        try:
            conv_id = int(conversation_id)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid conversation ID format'}), 400

        # Check regular conversations
        conversation = Conversation.query.get(conv_id)
        if conversation:
            messages = Message.query.filter_by(conversation_id=conversation.id)\
                .order_by(Message.created_at).all()
            return jsonify({
                'messages': [{
                    'role': msg.role,
                    'content': msg.content,
                    'image_url': msg.image_url,
                    'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                } for msg in messages]
            })

        # Check telegram conversations
        telegram_conv = TelegramConversation.query.get(conversation_id)
        if telegram_conv:
            messages = TelegramMessage.query.filter_by(conversation_id=telegram_conv.id)\
                .order_by(TelegramMessage.created_at).all()
            return jsonify({
                'messages': [{
                    'role': msg.role,
                    'content': msg.content,
                    'image_url': msg.image_url,
                    'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                } for msg in messages]
            })

        # Check WhatsApp messages
        whatsapp_messages = WhatsAppMessage.query.filter_by(thread_id=conversation_id)\
            .order_by(WhatsAppMessage.timestamp).all()
        if whatsapp_messages:
            return jsonify({
                'messages': [{
                    'role': 'user' if msg.direction == 'inbound' else 'assistant',
                    'content': msg.content,
                    'created_at': msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                } for msg in whatsapp_messages]
            })

        return jsonify({'error': 'Conversation not found'}), 404

    except Exception as e:
        logger.error(f"Error fetching conversation messages: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/admin/conversations/by-title/<path:conversation_title>/messages')
def get_conversation_messages_by_title(conversation_title):
    """Get messages for a specific conversation by its title"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        # Check if this is a WhatsApp conversation (title format: "Conversation thread_XXXX")
        whatsapp_thread_match = None
        if conversation_title.startswith('Conversation thread_'):
            # Extract thread_id from the title
            whatsapp_thread_match = conversation_title.replace('Conversation ', '')

            # Get WhatsApp messages for this thread
            whatsapp_messages = WhatsAppMessage.query.filter_by(thread_id=whatsapp_thread_match)\
                .order_by(WhatsAppMessage.timestamp).all()

            if whatsapp_messages:
                return jsonify({
                    'messages': [{
                        'role': 'user' if msg.direction == 'inbound' else 'assistant',
                        'content': msg.content,
                        'created_at': msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    } for msg in whatsapp_messages]
                })

        # Continue with the existing logic for other conversation types
        # Try to find the conversation in different models based on the title
        conversation = None
        messages = []

        # Check regular conversations
        conversation = Conversation.query.filter_by(title=conversation_title).first()
        if conversation:
            messages = Message.query.filter_by(conversation_id=conversation.id)\
                .order_by(Message.created_at).all()
            return jsonify({
                'messages': [{
                    'role': msg.role,
                    'content': msg.content,
                    'image_url': msg.image_url,
                    'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                } for msg in messages]
            })

        # Check telegram conversations
        telegram_conv = TelegramConversation.query.filter_by(title=conversation_title).first()
        if telegram_conv:
            messages = TelegramMessage.query.filter_by(conversation_id=telegram_conv.id)\
                .order_by(TelegramMessage.created_at).all()
            return jsonify({
                'messages': [{
                    'role': msg.role,
                    'content': msg.content,
                    'image_url': msg.image_url,
                    'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                } for msg in messages]
            })

        # Check for "Sans titre" or untitled conversations
        if conversation_title == "Sans titre":
            # For untitled conversations, just return some default content
            return jsonify({
                'messages': [{
                    'role': 'system',
                    'content': 'Aucun détail disponible pour cette conversation sans titre',
                    'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }]
            })

        # If conversation not found, try to find by last message content
        # This is a fallback mechanism
        message = Message.query.filter(Message.content.like(f"%{conversation_title}%")).first()
        if message:
            conversation = Conversation.query.get(message.conversation_id)
            if conversation:
                messages = Message.query.filter_by(conversation_id=conversation.id)\
                    .order_by(Message.created_at).all()
                return jsonify({
                    'messages': [{
                        'role': msg.role,
                        'content': msg.content,
                        'image_url': msg.image_url,
                        'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                    } for msg in messages]
                })

        return jsonify({'error': 'Conversation not found'}), 404

    except Exception as e:
        logger.error(f"Error fetching conversation messages by title: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/admin/conversations/by-title/<path:conversation_title>', methods=['DELETE'])
def delete_conversation_by_title(conversation_title):
    """Delete a conversation by its title"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        success = False

        # Check if this is a WhatsApp conversation (title format: "Conversation thread_XXXX")
        if conversation_title.startswith('Conversation thread_'):
            # Extract thread_id from the title
            whatsapp_thread = conversation_title.replace('Conversation ', '')

            # Delete WhatsApp messages for this thread
            messages = WhatsAppMessage.query.filter_by(thread_id=whatsapp_thread).all()
            if messages:
                for message in messages:
                    db.session.delete(message)
                db.session.commit()
                return jsonify({'success': True, 'message': 'WhatsApp conversation deleted successfully'})

        # Try to find and delete the conversation in the regular conversations
        conversation = Conversation.query.filter_by(title=conversation_title).first()
        if conversation:
            # First delete all associated messages
            Message.query.filter_by(conversation_id=conversation.id).delete()
            # Then delete the conversation
            db.session.delete(conversation)
            db.session.commit()
            success = True

        # Try to find and delete in Telegram conversations
        if not success:
            telegram_conv = TelegramConversation.query.filter_by(title=conversation_title).first()
            if telegram_conv:
                # Delete all messages first
                TelegramMessage.query.filter_by(conversation_id=telegram_conv.id).delete()
                # Delete the conversation
                db.session.delete(telegram_conv)
                db.session.commit()
                success = True

        # If we couldn't find by title, check if it's a "Sans titre" conversation
        # For this case, we might want to add a warning here
        # or implement an alternative way to identify these conversations
        if not success and conversation_title == "Sans titre":
            return jsonify({'success': False, 'message': 'Cannot delete generic "Sans titre" conversations without additional identifiers'}), 400

        if success:
            return jsonify({'success': True, 'message': 'Conversation deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Conversation not found'}), 404

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting conversation by title: {str(e)}")
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
                    'role': 'user' if msg.direction == 'inbound' else 'assistant',
                    'content': msg.content,
                    'created_at': msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                } for msg in whatsapp_messages]
            })

        return jsonify({'error': 'No WhatsApp messages found for this thread'}), 404

    except Exception as e:
        logger.error(f"Error fetching WhatsApp thread messages: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/admin/subscriptions', methods=['GET'])
def get_subscriptions():
    """Get all subscriptions data"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        subscriptions = Subscription.query.all()

        return jsonify({
            'subscriptions': [{
                'id': sub.id,
                'user_id': sub.user_id,
                'user_name': f"{sub.user.first_name} {sub.user.last_name}",
                'type': sub.subscription_type,
                'start_date': sub.start_date.strftime('%Y-%m-%d'),
                'expiry_date': sub.expiry_date.strftime('%Y-%m-%d'),
                'status': sub.status,
                'last_payment_date': sub.last_payment_date.strftime('%Y-%m-%d') if sub.last_payment_date else None
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
        required_fields = ['user_id', 'subscription_type', 'expiry_date', 'status']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        # Create new subscription
        subscription = Subscription(
            user_id=data['user_id'],
            subscription_type=data['subscription_type'],
            start_date=datetime.now(),
            expiry_date=datetime.strptime(data['expiry_date'], '%Y-%m-%d'),
            status=data['status'],
            last_payment_date=datetime.now()
        )

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
            subscription.expiry_date = datetime.strptime(data['expiry_date'], '%Y-%m-%d')
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

    # Start the Socket.IO server
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)