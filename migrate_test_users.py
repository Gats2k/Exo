"""
Script de migration TEST pour créer les User records des utilisateurs test.
À exécuter UNE SEULE FOIS avant de lancer le système de mémoire.

UTILISATEURS TEST :
- Telegram : 7525032647
- WhatsApp : 22578962583
"""

import logging
from app import app, db
from models import User, TelegramUser
from models import WhatsAppMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_test_telegram_user():
    """Crée un User pour l'utilisateur Telegram test."""
    telegram_id = 7525032647
    user_phone_id = f"telegram_{telegram_id}"

    with app.app_context():
        # Vérifier si le User existe déjà
        existing_user = User.query.filter_by(phone_number=user_phone_id).first()

        if existing_user:
            logger.info(f"✅ User déjà existant pour Telegram {telegram_id} (user_id: {existing_user.id})")
            return existing_user

        # Récupérer les infos du TelegramUser
        tg_user = TelegramUser.query.get(telegram_id)

        if not tg_user:
            logger.warning(f"⚠️  Aucun TelegramUser trouvé avec l'ID {telegram_id}")
            logger.info("Création d'un User avec des valeurs par défaut...")
            first_name = "Utilisateur"
            last_name = f"TG Test"
        else:
            first_name = tg_user.first_name or "Utilisateur"
            last_name = tg_user.last_name or f"TG {telegram_id}"

        # Créer le User
        new_user = User(
            phone_number=user_phone_id,
            first_name=first_name,
            last_name=last_name,
            age=0,
            study_level="Non défini",
            grade_goals="average"
        )
        db.session.add(new_user)
        db.session.commit()

        logger.info(f"✅ MIGRATION Telegram TEST: User créé (ID: {new_user.id}) pour telegram_id {telegram_id}")
        return new_user


def migrate_test_whatsapp_user():
    """Crée un User pour l'utilisateur WhatsApp test."""
    whatsapp_number = "22578962583"
    user_phone_id = f"whatsapp_{whatsapp_number}"

    with app.app_context():
        # Vérifier si le User existe déjà
        existing_user = User.query.filter_by(phone_number=user_phone_id).first()

        if existing_user:
            logger.info(f"✅ User déjà existant pour WhatsApp {whatsapp_number} (user_id: {existing_user.id})")
            return existing_user

        # Vérifier que ce numéro a bien des messages WhatsApp
        has_messages = WhatsAppMessage.query.filter_by(from_number=whatsapp_number).first()

        if not has_messages:
            logger.warning(f"⚠️  Aucun message WhatsApp trouvé pour le numéro {whatsapp_number}")
            logger.info("Le User sera quand même créé pour les tests futurs...")

        # Créer le User
        new_user = User(
            phone_number=user_phone_id,
            first_name="Utilisateur",
            last_name=f"WA {whatsapp_number[-4:]}",
            age=0,
            study_level="Non défini",
            grade_goals="average"
        )
        db.session.add(new_user)
        db.session.commit()

        logger.info(f"✅ MIGRATION WhatsApp TEST: User créé (ID: {new_user.id}) pour numéro {whatsapp_number}")
        return new_user


def run_test_migration():
    """Exécute la migration pour les deux utilisateurs test."""
    logger.info("="*60)
    logger.info("🔄 DÉMARRAGE MIGRATION TEST")
    logger.info("="*60)

    try:
        # Migration Telegram
        logger.info("\n--- TELEGRAM ---")
        telegram_user = migrate_test_telegram_user()

        # Migration WhatsApp
        logger.info("\n--- WHATSAPP ---")
        whatsapp_user = migrate_test_whatsapp_user()

        logger.info("\n" + "="*60)
        logger.info("✅ MIGRATION TEST TERMINÉE AVEC SUCCÈS")
        logger.info("="*60)
        logger.info(f"Telegram user_id: {telegram_user.id if telegram_user else 'N/A'}")
        logger.info(f"WhatsApp user_id: {whatsapp_user.id if whatsapp_user else 'N/A'}")
        logger.info("\nVous pouvez maintenant tester le système de mémoire avec ces utilisateurs.")

    except Exception as e:
        logger.error(f"❌ ERREUR LORS DE LA MIGRATION: {e}", exc_info=True)
        logger.error("La migration a échoué. Vérifiez les logs ci-dessus.")


if __name__ == '__main__':
    run_test_migration()