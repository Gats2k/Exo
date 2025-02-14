import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from openai import OpenAI
import os
from dotenv import load_dotenv
import time
import base64
import io
import logging
import requests

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Initialize OpenAI client with API key from environment
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
# Get assistant ID from environment or create a new one
ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')

def create_assistant():
    """Create a new assistant with vision capabilities if needed"""
    assistant = client.beta.assistants.create(
        name="Vision Assistant",
        instructions="You are a helpful assistant capable of understanding images and text. Help students with their exercises and questions.",
        model="gpt-4-vision-preview",
        tools=[{"type": "code_interpreter"}]
    )
    return assistant.id

if not ASSISTANT_ID:
    ASSISTANT_ID = create_assistant()

@app.route('/')
def chat():
    history = []
    return render_template('chat.html', history=history, credits=42)

def process_image(base64_string):
    try:
        logger.debug("Starting image processing")
        if ',' in base64_string:
            base64_string = base64_string.split(',')[1]

        image_bytes = base64.b64decode(base64_string)

        # Create file object with proper MIME type and filename
        file = client.files.create(
            file=("image.jpg", io.BytesIO(image_bytes), "image/jpeg"),  # Add name and MIME type
            purpose='assistants'
        )

        logger.debug(f"Created file with ID: {file.id}")
        return file.id  # Return just the file ID
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        raise

@socketio.on('send_message')
def handle_message(data):
    try:
        logger.debug("Received message data: %s", data)
        thread = client.beta.threads.create()

        # Initialize the lists
        file_ids = []
        message_content = []

        # Process image first if present
        if data.get('image'):
            try:
                file_id = process_image(data['image'])
                file_ids.append(file_id)  # Add to file IDs list
                logger.debug(f"Added file_id to list: {file_id}")
            except Exception as img_error:
                logger.error("Image processing error: %s", str(img_error))
                emit('receive_message', {
                    'message': 'Error processing image.'
                })
                return

        # Add message text if present
        if data.get('message'):
            message_content.append({
                "type": "text",
                "text": data['message']
            })

        # Create message with text and files attached
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=message_content,
            file_ids=file_ids  # Attach the files here
        )

        # Create a run using the existing assistant
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        )

        # Wait for response with timeout
        timeout = 30  # 30 seconds timeout
        start_time = time.time()

        while True:
            if time.time() - start_time > timeout:
                emit('receive_message', {'message': 'Request timed out. Please try again.'})
                return

            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )

            if run_status.status == 'completed':
                break
            elif run_status.status == 'failed':
                emit('receive_message', {'message': 'Sorry, there was an error processing your request.'})
                return
            elif run_status.status == 'requires_action':
                emit('receive_message', {'message': 'The assistant needs additional information.'})
                return

            eventlet.sleep(1)

        # Retrieve the answer
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        assistant_message = messages.data[0].content[0].text.value
        logger.debug("Assistant response: %s", assistant_message)

        emit('receive_message', {'message': assistant_message})

    except Exception as e:
        error_message = str(e)
        logger.error("Error in handle_message: %s", error_message)

        if "image" in error_message.lower():
            emit('receive_message', {
                'message': 'Error processing image. Please ensure the image is in a supported format (JPG or PNG) and try again.'
            })
        elif "rate limit" in error_message.lower():
            emit('receive_message', {
                'message': 'Too many requests. Please wait a moment and try again.'
            })
        else:
            emit('receive_message', {
                'message': f'An error occurred: {str(e)}'
            })

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)