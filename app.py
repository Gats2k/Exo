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
            role = "user" if msg['role'] == 'user' else "model"
            contents.append({
                "parts": [{"text": msg['content']}],
                "role": role
            })
    
    # Add system message as a special prefix to the first user message if it exists
    if system_content and len(contents) > 0 and contents[0]['role'] == 'user':
        contents[0]['parts'][0]['text'] = f"[System: {system_content}]\n\n" + contents[0]['parts'][0]['text']
        
    # Prepare the API request
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": contents}
    
    # Make the API request
    response = requests.post(api_url, headers=headers, json=data)
    
    if response.status_code != 200:
        logger.error(f"Gemini API error: {response.status_code} - {response.text}")
        raise Exception(f"Error from Gemini API: {response.status_code}")
    
    # Parse the response
    response_json = response.json()
    
    # Extract the generated text from the response
    if 'candidates' in response_json and len(response_json['candidates']) > 0:
        candidate = response_json['candidates'][0]
        if 'content' in candidate and 'parts' in candidate['content'] and len(candidate['content']['parts']) > 0:
            return candidate['content']['parts'][0]['text']
    
    raise Exception("Failed to get a valid response from Gemini API")

# Initialize LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Import models after db initialization to avoid circular imports
from models import Conversation, Message, User, TelegramUser, TelegramConversation, TelegramMessage, Subscription
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
def db_retry_session(max_retries=3, retry_delay=1):
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
            if conversation:
                return conversation

        # Create new thread and conversation
        client = get_ai_client()
        if CURRENT_MODEL == 'openai':
            # Only create thread for OpenAI
            thread = client.beta.threads.create()
            thread_id = thread.id
        else:
            # For other models, generate a UUID as thread_id
            thread_id = str(uuid.uuid4())

        conversation = Conversation(thread_id=thread_id)
        session.add(conversation)
        session.commit()
        return conversation

@app.route('/')
@login_required
def chat():
    try:
        with db_retry_session() as db_session:
            # Get recent non-deleted conversations for sidebar
            recent_conversations = Conversation.query.filter_by(deleted=False).order_by(Conversation.updated_at.desc()).limit(5).all()
            conversation_history = []

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
        # Get current conversation or create a new one
        thread_id = session.get('thread_id')
        conversation = None
        if thread_id:
            conversation = Conversation.query.filter_by(thread_id=thread_id).first()

        if not conversation:
            conversation = get_or_create_conversation()
            session['thread_id'] = conversation.thread_id

        # Get the appropriate AI client based on current model setting
        ai_client = get_ai_client()

        # Variables to store Mathpix results
        mathpix_result = None
        formatted_summary = None

        # Handle image if present
        if 'image' in data and data['image']:
            try:
                filename = save_base64_image(data['image'])
                image_url = request.url_root.rstrip('/') + url_for('static', filename=f'uploads/{filename}')

                # Process image with Mathpix
                mathpix_result = process_image_with_mathpix(data['image'])

                # Check if an error occurred
                if "error" in mathpix_result:
                    logger.error(f"Mathpix error: {mathpix_result['error']}")
                    formatted_summary = "Image content extraction failed. I will analyze the image visually."
                else:
                    formatted_summary = mathpix_result.get("formatted_summary", "")

                # Build user message with image extraction
                user_content = data.get('message', '')
                if formatted_summary:
                    user_store_content = f"{user_content}\n\n[Extracted Image Content]\n{formatted_summary}" if user_content else f"[Extracted Image Content]\n{formatted_summary}"
                else:
                    user_store_content = user_content

                # Store user message with image and extracted content
                user_message = Message(
                    conversation_id=conversation.id,
                    role='user',
                    content=user_store_content,
                    image_url=image_url
                )
                db.session.add(user_message)

                # Prepare message text for assistant
                message_for_assistant = data.get('message', '') + "\n\n" if data.get('message') else ""
                message_for_assistant += formatted_summary if formatted_summary else "Please analyze the image I uploaded."

                if CURRENT_MODEL in ['deepseek', 'deepseek-reasoner', 'qwen', 'gemini']:
                    # Get properly formatted messages based on model
                    if CURRENT_MODEL == 'deepseek-reasoner':
                        messages = get_interleaved_messages(conversation.id, message_for_assistant)
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
                            "content": message_for_assistant
                        })

                    if CURRENT_MODEL == 'gemini':
                        # Send to Gemini AI service
                        assistant_message = call_gemini_api(messages)
                    else:
                        # Send to AI service (DeepSeek or Qwen)
                        response = ai_client.chat.completions.create(
                            model=get_model_name(),
                            messages=messages,
                            stream=False
                        )
                        assistant_message = response.choices[0].message.content
                else:
                    # Use OpenAI's threads API
                    ai_client.beta.threads.messages.create(
                        thread_id=conversation.thread_id,
                        role="user",
                        content=message_for_assistant
                    )

                    # Create and run assistant
                    run = ai_client.beta.threads.runs.create(
                        thread_id=conversation.thread_id,
                        assistant_id=ASSISTANT_ID
                    )

                    # Wait for response with timeout
                    timeout = 30
                    start_time = time.time()

                    while True:
                        if time.time() - start_time > timeout:
                            emit('receive_message', {'message': 'Request timed out.'})
                            return

                        run_status = ai_client.beta.threads.runs.retrieve(
                            thread_id=conversation.thread_id,
                            run_id=run.id
                        )

                        if run_status.status == 'completed':
                            break
                        elif run_status.status == 'failed':
                            emit('receive_message', {'message': 'Sorry, there was an error.'})
                            return

                        eventlet.sleep(1)

                    # Retrieve OpenAI's response
                    messages = ai_client.beta.threads.messages.list(thread_id=conversation.thread_id)
                    assistant_message = messages.data[0].content[0].text.value

            except Exception as img_error:
                logger.error(f"Image processing error: {str(img_error)}")
                raise Exception("Failed to process image. Please make sure it's a valid image file.")
        else:
            # Store text-only message
            user_message = Message(
                conversation_id=conversation.id,
                role='user',
                content=data.get('message', '')
            )
            db.session.add(user_message)

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
                    # Send to Gemini AI service
                    assistant_message = call_gemini_api(messages)
                else:
                    # Send to AI service (DeepSeek or Qwen)
                    response = ai_client.chat.completions.create(
                        model=get_model_name(),
                        messages=messages,
                        stream=False
                    )
                    assistant_message = response.choices[0].message.content
            else:
                # Use OpenAI's threads API
                ai_client.beta.threads.messages.create(
                    thread_id=conversation.thread_id,
                    role="user",
                    content=data.get('message', '')
                )

                # Create and run assistant
                run = ai_client.beta.threads.runs.create(
                    thread_id=conversation.thread_id,
                    assistant_id=ASSISTANT_ID
                )

                # Wait for response with timeout
                timeout = 30
                start_time = time.time()

                while True:
                    if time.time() - start_time > timeout:
                        emit('receive_message', {'message': 'Request timed out.'})
                        return

                    run_status = ai_client.beta.threads.runs.retrieve(
                        thread_id=conversation.thread_id,
                        run_id=run.id
                    )

                    if run_status.status == 'completed':
                        break
                    elif run_status.status == 'failed':
                        emit('receive_message', {'message': 'Sorry, there was an error.'})
                        return

                    eventlet.sleep(1)

                # Retrieve OpenAI's response
                messages = ai_client.beta.threads.messages.list(thread_id=conversation.thread_id)
                assistant_message = messages.data[0].content[0].text.value

        # Store assistant response in database
        db_message = Message(
            conversation_id=conversation.id,
            role='assistant',
            content=assistant_message
        )
        db.session.add(db_message)

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

        db.session.commit()

        # Send response to client
        emit('receive_message', {'message': assistant_message})

    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}")
        error_message = str(e)
        if "image" in error_message.lower():
            emit('receive_message', {'message': 'Error processing image. Please ensure the image is in a supported format (JPG, PNG, GIF) and try again.'})
        else:
            emit('receive_message', {'message': f'An error occurred while processing your message. Please try again.'})

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


@socketio.on('open_conversation')
def handle_open_conversation(data):
    try:
        conversation = Conversation.query.get(data['id'])
        if conversation:
            # Update session with the opened conversation
            session['thread_id'] = conversation.thread_id

            # Get messages for this conversation
            messages = Message.query.filter_by(conversation_id=conversation.id).order_by(Message.created_at).all()
            messages_data = [
                {
                    'role': msg.role,
                    'content': msg.content,
                    'image_url': msg.image_url
                } for msg in messages
            ]

            emit('conversation_opened', {
                'success': True,
                'messages': messages_data,
                'conversation_id': conversation.id,
                'title': conversation.title or f"Conversation du {conversation.created_at.strftime('%d/%m/%Y')}"
            })
    except Exception as e:
        emit('conversation_opened', {
            'success': False,
            'error': str(e)
        })

@socketio.on('clear_session')
def handle_clear_session():
    # Clear the thread_id from session
    session.pop('thread_id', None)
    emit('session_cleared', {'success': True})

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
        phone_number = request.form.get('phone_number')
        password = request.form.get('password')

        # Check for admin credentials first
        if phone_number == os.environ.get('ADMIN_PHONE') and \
           password == os.environ.get('ADMIN_PASSWORD'):
            session['is_admin'] = True
            flash('Connecté en tant qu\'administrateur.', 'success')
            return redirect(url_for('admin_dashboard'))

        # Regular user login
        user = User.query.filter_by(phone_number=phone_number).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('chat'))

        flash('Numéro de téléphone ou mot de passe incorrect.', 'error')
        return redirect(url_for('login'))

    return render_template('login.html')

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
        # Initialize satisfaction rate to 0
        satisfaction_rate = 0

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

        return jsonify({'success': True, 'message': 'Model settings updated successfully'})
    except Exception as e:
        logger.error(f"Error updating model settings: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/admin/logout')
def admin_logout():
    """Logout route for admin"""
    session.pop('is_admin', None)
    flash('Vous avez été déconnecté.', 'success')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
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
        phone_number = request.form.get('phone_number')
        user = User.query.filter_by(phone_number=phone_number).first()

        if user:
            # Here we would typically send a reset link or code
            # For now, we'll just show a success message
            flash('Instructions de réinitialisation envoyées à votre numéro.', 'success')
            return redirect(url_for('login'))

        flash('Aucun compte trouvé avec ce numéro.', 'error')
        return redirect(url_for('forgot_password'))

    return render_template('forgot_password.html')

@app.route('/admin/data/<platform>')
def admin_platform_data(platform):
    today = datetime.today().date()

    if platform == 'web':
        # Get web platform statistics
        users = User.query.all()
        conversations = Conversation.query.all()

        data = {
            'active_users': len(users),
            'active_users_today': sum(1 for user in users if user.created_at.date() == today),
            'today_conversations': sum(1 for conv in conversations if conv.created_at.date() == today),
            'satisfaction_rate': 0,
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


@login_manager.unauthorized_handler
def unauthorized():
    """Redirect unauthorized users to Login page."""
    flash('Please log in to access this page.')
    return redirect(url_for('register'))


@app.route('/admin/users/<user_id>', methods=['DELETE'])
def delete_user(user_id):
    """Delete a user and their associated data."""
    try:
        with db_retry_session() as session:
            # Find the user based on the platform data
            user = None

            # Try to find in web users
            user = User.query.filter_by(phone_number=user_id).first()
            if user:
                session.delete(user)
                session.commit()
                return jsonify({'success': True, 'message': 'User deleted successfully'})

            # Try to find in Telegram users
            user = TelegramUser.query.filter_by(telegram_id=user_id).first()
            if user:
                # Delete all messages first
                for conv in user.conversations:
                    TelegramMessage.query.filter_by(conversation_id=conv.id).delete()

                # Delete all conversations
                TelegramConversation.query.filter_by(telegram_user_id=user.telegram_id).delete()

                # Finally delete the user
                session.delete(user)
                session.commit()
                return jsonify({'success': True, 'message': 'Telegram user deleted successfully'})

            # Check WhatsApp users (using the phone number as ID)
            messages = WhatsAppMessage.query.filter_by(from_number=user_id).all()
            if messages:
                for message in messages:
                    session.delete(message)
                session.commit()
                return jsonify({'success': True, 'message': 'WhatsApp user messages deleted successfully'})

            return jsonify({'success': False, 'message': 'User not found'}), 404

    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'Error deleting user'}), 500

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