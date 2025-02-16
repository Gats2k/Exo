import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, jsonify, url_for, session
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
import shutil
import time
from database import db
from models import Conversation, Message

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

# Initialize database
db.init_app(app)

# Create tables within application context
with app.app_context():
    # Import models and create tables
    db.create_all()

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize SocketIO
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')

def create_assistant():
    assistant = client.beta.assistants.create(
        name="Vision Assistant",
        instructions="You are a helpful assistant capable of understanding images and text.",
        model="gpt-4-vision-preview",
        tools=[{"type": "code_interpreter"}]
    )
    return assistant.id

def get_or_create_conversation(thread_id=None):
    if thread_id:
        conversation = Conversation.query.filter_by(thread_id=thread_id).first()
        if conversation:
            return conversation

    # Create new thread and conversation
    thread = client.beta.threads.create()
    conversation = Conversation(thread_id=thread.id)
    db.session.add(conversation)
    db.session.commit()
    return conversation

@app.route('/')
def chat():
    # Always start with a new conversation
    session.pop('thread_id', None)
    conversation = get_or_create_conversation()
    session['thread_id'] = conversation.thread_id

    # Get recent conversations for sidebar
    recent_conversations = Conversation.query.order_by(Conversation.updated_at.desc()).limit(5).all()
    conversation_history = [
        {
            'id': conv.id,
            'title': conv.title or f"Conversation du {conv.created_at.strftime('%d/%m/%Y')}",
            'subject': 'Général',
            'time': conv.created_at.strftime('%H:%M')
        } for conv in recent_conversations
    ]

    return render_template('chat.html', history=[], conversation_history=conversation_history, credits=42)

@socketio.on('send_message')
def handle_message(data):
    try:
        # Get current conversation
        conversation = get_or_create_conversation(session.get('thread_id'))
        session['thread_id'] = conversation.thread_id

        # Create message content
        message_content = []

        # Handle image if present
        if 'image' in data and data['image']:
            # Save the base64 image
            filename = save_base64_image(data['image'])
            image_url = request.url_root.rstrip('/') + url_for('static', filename=f'uploads/{filename}')

            # Create file for assistant
            base64_image = data['image'].split(',')[1]
            image_file = client.files.create(
                file=base64_image,
                purpose="assistants"
            )

            # Store user message with image
            user_message = Message(
                conversation_id=conversation.id,
                role='user',
                content=data.get('message', ''),
                image_url=image_url
            )
            db.session.add(user_message)

            # Create message for OpenAI with file attachment
            client.beta.threads.messages.create(
                thread_id=conversation.thread_id,
                role="user",
                content=data.get('message', ''),
                file_ids=[image_file.id]
            )
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
        db.session.commit()

        # Send response to client
        emit('receive_message', {'message': assistant_message})

    except Exception as e:
        error_message = str(e)
        if "file" in error_message.lower():
            emit('receive_message', {'message': 'Error processing image. Please try a different image or format.'})
        else:
            emit('receive_message', {'message': f'Error: {error_message}'})

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