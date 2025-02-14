import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Initialize OpenAI client with API key from environment
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
# Get assistant ID from environment
ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')

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

        # Add text if present
        if 'message' in data and data['message'].strip():
            message_content.append({
                "type": "text",
                "text": data['message']
            })

        # Add message to thread
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=message_content
        )

        # Create a run using the existing assistant
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        )

        # Wait for response
        while True:
            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            if run_status.status == 'completed':
                break
            elif run_status.status == 'failed':
                emit('receive_message', {'message': 'Sorry, there was an error.'})
                return

        # Retrieve the answer
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        assistant_message = messages.data[0].content[0].text.value

        emit('receive_message', {'message': assistant_message})
    except Exception as e:
        emit('receive_message', {'message': f'Error: {str(e)}'})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)