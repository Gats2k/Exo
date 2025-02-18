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
    """Start the Telegram bot in a separate thread."""
    try:
        run_telegram_bot()
    except Exception as e:
        logger.error(f"Error in telegram bot thread: {e}", exc_info=True)

if __name__ == "__main__":
    # Start Telegram bot in a separate thread
    telegram_thread = threading.Thread(target=start_telegram_bot)
    telegram_thread.daemon = True  # This ensures the thread will exit when the main program exits
    telegram_thread.start()

    # Run the Flask-SocketIO application
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False)