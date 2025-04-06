
import eventlet
eventlet.monkey_patch()

from flask import jsonify
from app import app, socketio
import logging
import threading
import os
import time

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'}), 200

# Fonction pour démarrer le bot Telegram dans un thread séparé
def start_telegram_bot():
    logger.info("Initializing Telegram bot thread...")
    # Attendre que l'application Flask soit complètement démarrée
    time.sleep(5)

    try:
        # S'assurer que le robot Telegram est activé
        os.environ['RUN_TELEGRAM_BOT'] = 'true'

        # Importer et exécuter le bot Telegram
        from telegram_bot import run_telegram_bot
        logger.info("Starting Telegram bot...")
        run_telegram_bot()
    except Exception as e:
        logger.error(f"Error starting Telegram bot: {str(e)}")

# Démarrer le bot Telegram dans un thread séparé
telegram_thread = threading.Thread(target=start_telegram_bot)
telegram_thread.daemon = True  # Le thread s'arrêtera quand le programme principal s'arrête
telegram_thread.start()

logger.info("Main application starting - Telegram bot thread initialized")

if __name__ == "__main__":
    # Run the Flask-SocketIO application
    logger.info("Starting Flask-SocketIO server on port 5000...")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False, log_output=True)
