import eventlet
eventlet.monkey_patch()
import logging
import os
import sys
import time

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("telegram_bot.log")
    ]
)
logger = logging.getLogger(__name__)

os.environ['RUN_TELEGRAM_BOT'] = 'true'

def start_bot():
    try:
        from telegram_bot import run_telegram_bot
        logger.info("Successfully imported run_telegram_bot")
        run_telegram_bot()
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        return False
    return True

def main():
    logger.info("=== TELEGRAM BOT SERVICE STARTING ===")
    logger.info(f"Current working directory: {os.getcwd()}")

    # Initial delay for other services to start
    time.sleep(10)

    while True:
        if start_bot():
            break
        logger.info("Retrying bot start in 30 seconds...")
        time.sleep(30)

if __name__ == "__main__":
    main()
