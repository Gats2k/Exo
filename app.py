# Must be at the very start of the file, before any other imports
import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from openai import OpenAI
import os
from dotenv import load_dotenv
import time
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Initialize OpenAI client with API key from environment
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
# Get assistant ID from environment
ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
RUN_STATUS_CHECK_INTERVAL = 1  # seconds
MAX_RUN_TIME = 60  # seconds

@app.route('/')
def chat():
    history = []
    return render_template('chat.html', history=history, credits=42)

def wait_for_run_completion(thread_id, run_id):
    """Wait for the assistant's run to complete with timeout."""
    start_time = time.time()
    while True:
        try:
            if time.time() - start_time > MAX_RUN_TIME:
                logger.error("Run timed out after %s seconds", MAX_RUN_TIME)
                return False

            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run_id
            )

            logger.debug("Run status: %s", run_status.status)

            if run_status.status == 'completed':
                return True
            elif run_status.status in ['failed', 'cancelled', 'expired']:
                logger.error("Run failed with status: %s", run_status.status)
                return False

            time.sleep(RUN_STATUS_CHECK_INTERVAL)
        except Exception as e:
            logger.error("Error checking run status: %s", str(e))
            return False

@socketio.on('connect')
def handle_connect():
    logger.info("Client connected")
    emit('connect_response', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    logger.info("Client disconnected")

@socketio.on('send_message')
def handle_message(data):
    for attempt in range(MAX_RETRIES):
        try:
            logger.info("Processing message attempt %d", attempt + 1)

            # Create thread for conversation
            thread = client.beta.threads.create()
            logger.debug("Created thread: %s", thread.id)

            # Create message content based on whether there's an image or text or both
            message_content = []

            # Add image if present
            if 'image' in data and data['image']:
                # Remove the data:image/jpeg;base64, prefix
                base64_image = data['image'].split(',')[1]
                message_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                })
                logger.debug("Added image to message content")

            # Add text if present
            if 'message' in data and data['message'].strip():
                message_content.append({
                    "type": "text",
                    "text": data['message']
                })
                logger.debug("Added text to message content")

            if not message_content:
                emit('receive_message', {'message': 'No message or image provided.'})
                return

            # Add message to thread
            message = client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=message_content
            )
            logger.debug("Created message in thread")

            # Create a run using the existing assistant
            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=ASSISTANT_ID
            )
            logger.debug("Created run: %s", run.id)

            # Wait for response
            if wait_for_run_completion(thread.id, run.id):
                # Retrieve the answer
                messages = client.beta.threads.messages.list(thread_id=thread.id)

                if not messages.data:
                    logger.error("No messages found in thread")
                    raise Exception("No response received from assistant")

                assistant_message = messages.data[0].content[0].text.value
                logger.info("Successfully received assistant response")
                emit('receive_message', {'message': assistant_message})
                return

            logger.warning("Run did not complete successfully, retrying...")
            time.sleep(RETRY_DELAY)

        except Exception as e:
            logger.error("Error in handle_message: %s", str(e))
            if attempt == MAX_RETRIES - 1:
                emit('receive_message', {'message': f'Error: Unable to get a response after {MAX_RETRIES} attempts. Please try again.'})
                return
            time.sleep(RETRY_DELAY)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)