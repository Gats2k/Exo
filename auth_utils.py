import uuid
import logging
from models import User, TelegramUser
from database import db

logger = logging.getLogger(__name__)


def phone_number_exists(phone_number):
    """
    Vérifie si un numéro de téléphone existe déjà dans la base de données
    en cherchant parmi tous les types d'utilisateurs (web, WhatsApp, Telegram)
    """
    # Import local pour éviter l'importation circulaire
    from whatsapp_bot import WhatsAppMessage

    # Normaliser le numéro de téléphone en supprimant le '+' du début si présent
    normalized_number = phone_number.replace('+', '')

    # Vérifier dans les utilisateurs web
    web_user = User.query.filter_by(phone_number=phone_number).first()
    if web_user:
        return True

    # Vérifier dans les utilisateurs web avec préfixe WhatsApp
    whatsapp_user = User.query.filter_by(
        phone_number=f"whatsapp_{normalized_number}").first()
    if whatsapp_user:
        return True

    # Vérifier dans les messages WhatsApp
    whatsapp_message = WhatsAppMessage.query.filter_by(
        from_number=normalized_number).first()
    if whatsapp_message:
        return True

    # Vérifier dans les utilisateurs Telegram avec un numéro de téléphone
    telegram_user = TelegramUser.query.filter(
        TelegramUser.phone_number != "---",
        TelegramUser.phone_number == phone_number).first()
    if telegram_user:
        return True

    return False


def get_or_create_web_user_for_telegram(telegram_user):
    """
    Crée ou récupère un User associé à un TelegramUser pour l'authentification Flask-Login

    Args:
        telegram_user (TelegramUser): L'utilisateur Telegram source

    Returns:
        User: L'utilisateur web associé (créé ou existant)
    """
    # Vérifier si un User existe déjà pour cet ID Telegram
    user = User.query.filter_by(
        phone_number=f"telegram_{telegram_user.telegram_id}").first()

    if not user:
        # Créer un nouvel utilisateur Web lié à ce TelegramUser
        user = User(
            first_name=telegram_user.first_name
            if telegram_user.first_name != "---" else "Telegram",
            last_name=telegram_user.last_name
            if telegram_user.last_name != "---" else "User",
            age=18,  # Valeur par défaut
            phone_number=
            f"telegram_{telegram_user.telegram_id}",  # Format spécial pour identifier les utilisateurs Telegram
            study_level=telegram_user.study_level
            if telegram_user.study_level != "---" else "Non spécifié",
            grade_goals="average"  # Valeur par défaut
        )
        # Définir un mot de passe aléatoire (ne sera pas utilisé car l'authentification se fait par ID Telegram)
        user.set_password(str(uuid.uuid4()))

        db.session.add(user)
        db.session.commit()

        # Associer le vrai numéro de téléphone au TelegramUser pour les requêtes futures
        logger.info(
            f"Nouvel utilisateur Telegram créé avec ID {telegram_user.telegram_id} et numéro {telegram_user.phone_number}"
        )

    return user