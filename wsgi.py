import sys
import os

# Ajout d'une variable d'environnement pour indiquer qu'on est en mode déploiement
os.environ['DEPLOYMENT_MODE'] = 'true'

# Import eventlet et monkey_patch uniquement pour le mode de développement
if not os.environ.get('GUNICORN_DEPLOYMENT'):
    # Le mode développement utilise eventlet
    try:
        import eventlet
        eventlet.monkey_patch()
        print("Eventlet successfully loaded and monkey patched.")
    except ImportError:
        print("Eventlet not available, falling back to threading mode.")

# Main Flask application
from app import app, socketio

# Préparation de l'application pour Gunicorn
# Si nous sommes en mode Gunicorn standard (sans eventlet)
if os.environ.get('GUNICORN_DEPLOYMENT') == 'standard':
    # Désactive le mode async pour socket.io quand on utilise Gunicorn standard
    application = app
    print("Running in standard Gunicorn mode (without eventlet)")
else:
    # En développement ou avec worker Gunicorn eventlet
    application = socketio.wsgi_app
    print("Running with SocketIO + eventlet mode")

if __name__ == "__main__":
    # En mode développement, utiliser socketio.run
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)