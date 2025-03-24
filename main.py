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

    # Run the Flask-SocketIO application
    logger.info("Starting Flask-SocketIO server on port 5000...")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False, log_output=True)