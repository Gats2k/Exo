import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, jsonify, url_for, session, redirect, flash
from flask_socketio import SocketIO, emit
from openai import OpenAI
import os
from dotenv import load_dotenv
import uuid
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

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

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

# Initialize database
from database import db
db.init_app(app)

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize SocketIO
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')

# Initialize LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Import models after db initialization to avoid circular imports
from models import Conversation, Message, User

# Create tables within application context
with app.app_context():
    db.create_all()

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

def get_or_create_conversation(thread_id=None):
    with db_retry_session() as session:
        if thread_id:
            conversation = Conversation.query.filter_by(thread_id=thread_id).first()
            if conversation:
                return conversation

        # Create new thread and conversation
        thread = client.beta.threads.create()
        conversation = Conversation(thread_id=thread.id)
        session.add(conversation)
        session.commit()
        return conversation

@app.route('/')
def index():
    # Redirect to register page by default
    return redirect(url_for('register'))

@app.route('/chat')
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

@socketio.on('send_message')
def handle_message(data):
    try:
        # Get current conversation or create a new one if this is the first message
        thread_id = session.get('thread_id')
        conversation = None
        if thread_id:
            conversation = Conversation.query.filter_by(thread_id=thread_id).first()

        if not conversation:
            # Create new conversation for first message
            conversation = get_or_create_conversation()
            session['thread_id'] = conversation.thread_id

        # Handle image if present
        if 'image' in data and data['image']:
            try:
                # Save the base64 image
                filename = save_base64_image(data['image'])
                # Create a public URL for the image
                image_url = request.url_root.rstrip('/') + url_for('static', filename=f'uploads/{filename}')

                # Store user message with image
                user_message = Message(
                    conversation_id=conversation.id,
                    role='user',
                    content=data.get('message', ''),
                    image_url=image_url
                )
                db.session.add(user_message)

                # Create message for OpenAI with image
                openai_message_content = []

                # Add image content
                openai_message_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": image_url
                    }
                })

                # Add text content if present
                if data.get('message'):
                    openai_message_content.append({
                        "type": "text",
                        "text": data['message']
                    })

                # Send message to OpenAI with image URL
                client.beta.threads.messages.create(
                    thread_id=conversation.thread_id,
                    role="user",
                    content=openai_message_content
                )
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

            # Send message to OpenAI
            client.beta.threads.messages.create(
                thread_id=conversation.thread_id,
                role="user",
                content=data.get('message', '')
            )

        # Create and run assistant
        run = client.beta.threads.runs.create(
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

            run_status = client.beta.threads.runs.retrieve(
                thread_id=conversation.thread_id,
                run_id=run.id
            )

            if run_status.status == 'completed':
                break
            elif run_status.status == 'failed':
                emit('receive_message', {'message': 'Sorry, there was an error.'})
                return

            eventlet.sleep(1)

        # Retrieve and store assistant's response
        messages = client.beta.threads.messages.list(thread_id=conversation.thread_id)
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
            first_user_message = Message.query.filter_by(
                conversation_id=conversation.id,
                role='user'
            ).order_by(Message.created_at).first()

            if first_user_message:
                # Use the first 30 characters of the message as the title
                title = first_user_message.content[:30] + "..." if len(first_user_message.content) > 30 else first_user_message.content
                conversation.title = title
                db.session.commit()

                # Emit the new conversation to all clients for real-time history update
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

        # Check for admin credentials
        if User.is_admin_credentials(phone_number, password):
            return redirect(url_for('admin_dashboard'))

        user = User.query.filter_by(phone_number=phone_number).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('chat'))

        flash('Numéro de téléphone ou mot de passe incorrect.', 'error')
        return redirect(url_for('login'))

    return render_template('login.html')

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

@app.route('/admin')
def admin_dashboard():
    today = datetime.today().date()
    users = User.query.all()
    conversations = Conversation.query.all()

    # Count today's conversations
    today_conversations = sum(1 for conv in conversations if conv.created_at.date() == today)

    # Get actual number of users
    active_users = len(users)
    # Count users created today
    active_users_today = sum(1 for user in users if user.created_at.date() == today)
    # Initialize satisfaction rate to 0
    satisfaction_rate = 0

    return render_template('admin_dashboard.html', 
                         users=users, 
                         conversations=conversations,
                         active_users=active_users,
                         active_users_today=active_users_today,
                         today_conversations=today_conversations,
                         satisfaction_rate=satisfaction_rate)

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
            'satisfaction_rate': 0  # Initialize to 0 as requested
        }

    elif platform == 'telegram':
        # For telegram, we'll need to query telegram-specific data
        # This is where you'll integrate with your telegram bot's data
        data = {
            'active_users': 0,  # Replace with actual telegram users count
            'active_users_today': 0,  # Replace with new telegram users today
            'today_conversations': 0,  # Replace with telegram conversations today
            'satisfaction_rate': 0
        }

    return jsonify(data)


if __name__ == '__main__':
    # Configure scheduler for cleanup
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=cleanup_uploads, 
                     trigger="interval", 
                     hours=1,
                     id='cleanup_job')
    scheduler.start()

    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=True)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()