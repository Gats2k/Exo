import eventlet
eventlet.monkey_patch()

from app import app, socketio
from telegram_bot import run_telegram_bot
import threading
import asyncio

def start_telegram_bot():
    """Start the Telegram bot in a separate event loop."""
    # Create a new event loop for the thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # Run the telegram bot
        loop.run_until_complete(run_telegram_bot())
    except Exception as e:
        print(f"Error in Telegram bot: {e}")
    finally:
        loop.close()

if __name__ == "__main__":
    # Configure eventlet to work with asyncio
    eventlet.spawn(start_telegram_bot)

    # Run the Flask-SocketIO application
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False)