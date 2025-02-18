import eventlet
eventlet.monkey_patch()

from app import app, socketio
from telegram_bot import run_telegram_bot
import threading

def start_telegram_bot():
    run_telegram_bot()

if __name__ == "__main__":
    # Start Telegram bot in a separate thread
    telegram_thread = threading.Thread(target=start_telegram_bot)
    telegram_thread.daemon = True  # This ensures the thread will exit when the main program exits
    telegram_thread.start()

    # Run the Flask-SocketIO application
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False, log_output=True)