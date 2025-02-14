import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from openai import OpenAI
import os
from dotenv import load_dotenv
import time
import base64

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

@socketio.on('send_message')
def handle_message(data):
    try:
        # Create thread for conversation
        thread = client.beta.threads.create()

        # Create message content based on whether there's an image or text or both
        if 'image' in data and data['image']:
            # Remove the data:image/jpeg;base64, prefix
            base64_image = data['image'].split(',')[1]

            # Create a temporary file for the image
            image_file = client.files.create(
                file=base64.b64decode(base64_image),
                purpose="assistants"
            )

            # Create message with both image and text
            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=[
                    {
                        "type": "text",
                        "text": data.get('message', 'Please analyze this image.')
                    }
                ],
                file_ids=[image_file.id]
            )
        else:
            # Text-only message
            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=data.get('message', '')
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

        emit('receive_message', {'message': assistant_message})

    except Exception as e:
        error_message = str(e)
        if "file" in error_message.lower():
            emit('receive_message', {'message': 'Error processing image. Please try a different image or format.'})
        elif "rate limit" in error_message.lower():
            emit('receive_message', {'message': 'Too many requests. Please wait a moment and try again.'})
        else:
            emit('receive_message', {'message': f'An error occurred: {str(e)}'})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)