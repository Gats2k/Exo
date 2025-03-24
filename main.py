import os
import sys
import threading
import logging

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Déterminer le mode d'exécution (développement local ou déploiement)
is_deployment = os.environ.get('DEPLOYMENT_MODE') == 'true'
socketio_mode = os.environ.get('SOCKETIO_MODE', 'eventlet')

# Initialiser eventlet seulement si nous utilisons ce mode
# et si nous ne sommes pas en mode déploiement standard
if socketio_mode == 'eventlet' and not is_deployment:
    try:
        import eventlet
        eventlet.monkey_patch()
        logger.info("Eventlet initialized and monkey patched.")
    except ImportError:
        logger.warning("Eventlet not available, falling back to threading mode.")
        os.environ['SOCKETIO_MODE'] = 'threading'

# Import the Flask app and socketio
from app import app, socketio
from telegram_bot import run_telegram_bot

def start_telegram_bot():
    try:
        logger.info("Starting Telegram bot thread...")
        run_telegram_bot()
    except Exception as e:
        logger.error(f"Error in Telegram bot thread: {str(e)}", exc_info=True)

if __name__ == "__main__":
    # Start Telegram bot in a separate thread
    telegram_thread = threading.Thread(target=start_telegram_bot)
    telegram_thread.daemon = True  # This ensures the thread will exit when the main program exits
    telegram_thread.start()

    # Log the configuration
    logger.info(f"Starting server with SocketIO mode: {socketio_mode}")
    logger.info(f"Deployment mode: {'Yes' if is_deployment else 'No'}")

    # Run the Flask-SocketIO application
    logger.info("Starting Flask-SocketIO server on port 5000...")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False, log_output=True)