import eventlet
eventlet.monkey_patch()

from app import app, socketio
from telegram_bot import run_telegram_bot
import threading
import logging

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

logger.info("Main application starting - Telegram bot will be managed by separate process")

if __name__ == "__main__":
    # Run the Flask-SocketIO application
    logger.info("Starting Flask-SocketIO server on port 5000...")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False, log_output=True)