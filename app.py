import os
import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
import openai


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
app = Flask(__name__)

# Configure Flask app
app.config['SECRET_KEY'] = os.environ.get("FLASK_SECRET_KEY", "default_secret_key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Initialize SocketIO with eventlet
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')

# Initialize extensions
db.init_app(app)

# Initialize OpenAI client
openai_client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Store assistant ID globally
assistant_id = None

with app.app_context():
    import models
    db.create_all()
    # Create OpenAI assistant if it doesn't exist
    if not assistant_id:
        assistant = openai_client.beta.assistants.create(
            name="Simple Helper",
            instructions="You are a helpful assistant who provides clear and concise responses.",
            tools=[{"type": "code_interpreter"}],
            model="gpt-4-turbo-preview"
        )
        assistant_id = assistant.id

@app.route('/')
def chat():
    return render_template('chat.html')

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('message')
def handle_message(data):
    try:
        # Create or get thread
        thread = models.Thread.query.first()
        if not thread:
            # Create new OpenAI thread
            openai_thread = openai_client.beta.threads.create()
            thread = models.Thread(assistant_thread_id=openai_thread.id)
            db.session.add(thread)
            db.session.commit()

        # Save user message
        user_message = models.Message(
            content=data['message'],
            role='user',
            thread_id=thread.id
        )
        db.session.add(user_message)
        db.session.commit()

        # Send message to OpenAI
        openai_client.beta.threads.messages.create(
            thread.assistant_thread_id,
            role="user",
            content=data['message']
        )

        # Create run
        run = openai_client.beta.threads.runs.create(
            thread.assistant_thread_id,
            assistant_id=assistant_id
        )

        # Wait for completion
        while True:
            run_status = openai_client.beta.threads.runs.retrieve(
                thread.assistant_thread_id,
                run.id
            )
            if run_status.status == 'completed':
                break
            elif run_status.status == 'failed':
                raise Exception("OpenAI run failed")
            eventlet.sleep(1)

        # Get the assistant's response
        messages = openai_client.beta.threads.messages.list(
            thread.assistant_thread_id
        )
        assistant_response = messages.data[0].content[0].text.value

        # Save assistant message
        assistant_message = models.Message(
            content=assistant_response,
            role='assistant',
            thread_id=thread.id
        )
        db.session.add(assistant_message)
        db.session.commit()

        # Emit response back to client
        emit('message', {
            'role': 'assistant',
            'content': assistant_response,
            'timestamp': datetime.utcnow().isoformat()
        })

    except Exception as e:
        print(f"Error processing message: {str(e)}")
        emit('error', {'message': 'An error occurred processing your message'})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)