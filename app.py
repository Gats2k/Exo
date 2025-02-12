import os
from flask import Flask, render_template
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
# create the app
app = Flask(__name__)
# setup a secret key, required by sessions
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or "a secret key"
# configure the database, relative to the app instance folder
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
# initialize the app with the extension, flask-sqlalchemy >= 3.0.x
db.init_app(app)

# Initialize SocketIO
socketio = SocketIO(app)

with app.app_context():
    # Make sure to import the models here or their tables won't be created
    import models  # noqa: F401
    from assistant import AssistantChat

    db.create_all()

# Initialize OpenAI assistant
assistant = AssistantChat()

@app.route('/')
def chat():
    # Get chat history from database
    history = models.ChatMessage.query.order_by(models.ChatMessage.created_at.desc()).limit(10).all()
    return render_template('chat.html', history=history, credits=42)

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('message')
async def handle_message(data):
    try:
        # Save user message to database
        user_message = models.ChatMessage(
            content=data['message'],
            role='user',
            thread_id=data.get('thread_id', 'default')
        )
        db.session.add(user_message)
        db.session.commit()

        # Get assistant's response
        response = await assistant.send_message(data['message'])

        # Save assistant's response to database
        assistant_message = models.ChatMessage(
            content=response,
            role='assistant',
            thread_id=user_message.thread_id
        )
        db.session.add(assistant_message)
        db.session.commit()

        # Emit the response back to the client
        socketio.emit('response', {
            'message': response,
            'thread_id': user_message.thread_id
        })
    except Exception as e:
        print(f"Error handling message: {e}")
        socketio.emit('error', {'message': str(e)})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Add use_reloader and log_output parameters
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, 
                use_reloader=True, log_output=True)
