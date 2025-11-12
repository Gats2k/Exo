import logging
from datetime import datetime

# Importer les éléments nécessaires de ton application
from app import app, db
from models import TelegramUser, TelegramConversation, WhatsAppMessage
from reminder_system import (
    # Fonctions de vérification
    should_send_night_reminder_telegram,
    should_send_night_reminder_whatsapp,
    # Fonctions d'envoi
    send_reminder_to_telegram_user,
    send_reminder_to_whatsapp_user
)

# --- CONFIGURATION DU TEST ---
# Mettre à True pour lancer le test correspondant
TEST_TELEGRAM = True
TEST_WHATSAPP = True

# IDs et numéros à tester
TARGET_TELEGRAM_ID = 7525032647
TARGET_WHATSAPP_NUMBER = "22541903958" # Doit être sans le '+'
# -----------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TEST_REMINDER")


def run_test_for_telegram_user(user_id: int):
    """
    Exécute le processus de rappel pour un seul utilisateur Telegram.
    """
    logger.info(f"\n--- Début du test de rappel pour TELEGRAM ID: {user_id} ---")

    with app.app_context():
        # 1. Vérifier si l'utilisateur est éligible
        is_eligible, context = should_send_night_reminder_telegram(user_id)

        if not is_eligible:
            logger.warning(f"❌ TEST ÉCHOUÉ (LOGIQUE OK) : L'utilisateur {user_id} n'est PAS éligible.")
            logger.warning(f"   Raison : {context.get('reason', 'Inconnue')}")
            logger.warning(f"   Détails : {context}")
            logger.info("--- Fin du test Telegram ---")
            return

        logger.info(f"✅ UTILISATEUR ÉLIGIBLE (Telegram) : L'utilisateur {user_id} remplit les conditions.")
        logger.info(f"   Détails : {context}")

        # 2. Récupérer le thread_id de sa dernière conversation
        conversation = TelegramConversation.query.filter_by(
            telegram_user_id=user_id
        ).order_by(TelegramConversation.updated_at.desc()).first()

        if not conversation or not conversation.thread_id:
            logger.error(f"❌ ERREUR CRITIQUE : Impossible de trouver une conversation ou un thread_id pour l'utilisateur {user_id}.")
            logger.info("--- Fin du test Telegram ---")
            return

        logger.info(f"   Thread ID trouvé : {conversation.thread_id}")

        # 3. Préparer les données pour la fonction d'envoi
        user_data = {
            'telegram_id': user_id,
            'thread_id': conversation.thread_id,
            'context': context
        }
        scheduled_for = datetime.now()

        # 4. Envoyer le rappel
        logger.info(">>> Tentative d'envoi du message de rappel (Telegram)...")
        success = send_reminder_to_telegram_user(user_data, scheduled_for)

        if success:
            logger.info(f"🎉 SUCCÈS : Le message de rappel (Telegram) a été envoyé à l'utilisateur {user_id}.")
        else:
            logger.error(f"🔥 ÉCHEC : La fonction d'envoi (Telegram) a retourné 'False' pour l'utilisateur {user_id}.")

    logger.info("--- Fin du test Telegram ---")


def run_test_for_whatsapp_user(phone_number: str):
    """
    Exécute le processus de rappel pour un seul utilisateur WhatsApp.
    """
    logger.info(f"\n--- Début du test de rappel pour WHATSAPP N°: {phone_number} ---")

    with app.app_context():
        # 1. Trouver le dernier message pour obtenir le thread_id
        last_message = WhatsAppMessage.query.filter_by(
            from_number=phone_number,
            direction='inbound'
        ).order_by(WhatsAppMessage.timestamp.desc()).first()

        if not last_message or not last_message.thread_id:
            logger.error(f"❌ ERREUR CRITIQUE : Aucun message entrant ou thread_id trouvé pour le numéro {phone_number}.")
            logger.info("--- Fin du test WhatsApp ---")
            return

        thread_id = last_message.thread_id
        logger.info(f"   Thread ID trouvé : {thread_id}")

        # 2. Vérifier si l'utilisateur est éligible
        is_eligible, context = should_send_night_reminder_whatsapp(phone_number, thread_id)

        if not is_eligible:
            logger.warning(f"❌ TEST ÉCHOUÉ (LOGIQUE OK) : L'utilisateur {phone_number} n'est PAS éligible.")
            logger.warning(f"   Raison : {context.get('reason', 'Inconnue')}")
            logger.warning(f"   Détails : {context}")
            logger.info("--- Fin du test WhatsApp ---")
            return

        logger.info(f"✅ UTILISATEUR ÉLIGIBLE (WhatsApp) : L'utilisateur {phone_number} remplit les conditions.")
        logger.info(f"   Détails : {context}")

        # 3. Préparer les données pour la fonction d'envoi
        user_data = {
            'phone_number': phone_number,
            'thread_id': thread_id,
            'context': context
        }
        scheduled_for = datetime.now()

        # 4. Envoyer le rappel
        logger.info(">>> Tentative d'envoi du message de rappel (WhatsApp)...")
        success = send_reminder_to_whatsapp_user(user_data, scheduled_for)

        if success:
            logger.info(f"🎉 SUCCÈS : Le message de rappel (WhatsApp) a été envoyé à l'utilisateur {phone_number}.")
        else:
            logger.error(f"🔥 ÉCHEC : La fonction d'envoi (WhatsApp) a retourné 'False' pour l'utilisateur {phone_number}.")

    logger.info("--- Fin du test WhatsApp ---")


if __name__ == "__main__":
    if TEST_TELEGRAM:
        run_test_for_telegram_user(TARGET_TELEGRAM_ID)

    if TEST_WHATSAPP:
        run_test_for_whatsapp_user(TARGET_WHATSAPP_NUMBER)