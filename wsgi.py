import eventlet
eventlet.monkey_patch()

from app import app, socketio

# Cette variable est utilisée par Gunicorn
application = socketio.wsgi_app

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)