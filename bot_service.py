import eventlet
eventlet.monkey_patch()
import logging
import os
import sys
import time

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("telegram_bot.log")
    ]
)
logger = logging.getLogger(__name__)

# Force les variables d'environnement
os.environ['RUN_TELEGRAM_BOT'] = 'true'

logger.info("=== TELEGRAM BOT SERVICE STARTING ===")
logger.info(f"Current working directory: {os.getcwd()}")
logger.info(f"Python version: {sys.version}")
logger.info(f"Environment variables: TELEGRAM_BOT_TOKEN exists: {'yes' if 'TELEGRAM_BOT_TOKEN' in os.environ else 'NO'}")

# Attendre que la base de données soit prête
logger.info("Waiting 15 seconds for main application to initialize...")
time.sleep(15)

try:
    # Import la fonction après avoir défini la variable d'environnement
    from telegram_bot import run_telegram_bot
    logger.info("Successfully imported run_telegram_bot")

    # Lancer le bot
    logger.info("Launching Telegram bot...")
    run_telegram_bot()
except Exception as e:
    import traceback
    logger.error(f"CRITICAL ERROR: {str(e)}")
    logger.error(f"Traceback: {traceback.format_exc()}")

    # Garder le service en vie même en cas d'erreur
    logger.info("Entering error recovery loop...")
    while True:
        time.sleep(60)
        logger.info("Bot service still running in error state, attempting to restart...")
        try:
            from telegram_bot import run_telegram_bot
            run_telegram_bot()
        except Exception as e2:
            logger.error(f"Restart failed: {str(e2)}")