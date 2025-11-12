import logging
import time
import random
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from database import db
from models import (
    User, TelegramUser, WhatsAppMessage, 
    TelegramConversation, ReminderLog
)
from ai_utils import generate_reminder_message
from utils import db_retry_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================
# FONCTIONS DE VÉRIFICATION DES CONDITIONS
# ============================================

def should_send_night_reminder_whatsapp(phone_number: str, thread_id: str) -> Tuple[bool, Dict]:
    """
    Vérifie si on doit envoyer le rappel nuit WhatsApp (22h30)

    Returns:
        Tuple[bool, Dict]: (eligibilité, contexte avec infos de debug)
    """
    now = datetime.now()

    # Chercher le dernier message inbound
    last_message = WhatsAppMessage.query.filter_by(
        from_number=phone_number,
        direction='inbound'
    ).order_by(WhatsAppMessage.timestamp.desc()).first()

    if not last_message:
        return False, {'reason': 'Aucun message trouvé'}

    hours_since_last = (now - last_message.timestamp).total_seconds() / 3600

    # CONDITION 1 : Fenêtre WhatsApp 24h
    if hours_since_last >= 24:
        return False, {
            'reason': 'Hors fenêtre 24h',
            'hours_since': hours_since_last,
            'last_message_time': last_message.timestamp
        }

    # CONDITION 2 : Actif aujourd'hui (depuis 5h ce matin)
    morning_start = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if last_message.timestamp < morning_start:
        return False, {
            'reason': 'Pas actif aujourd\'hui',
            'hours_since': hours_since_last,
            'last_message_time': last_message.timestamp,
            'morning_start': morning_start
        }

    # CONDITION 3 : Pas en conversation active (< 30min)
    if hours_since_last < 0.5:
        return False, {
            'reason': 'En conversation active',
            'hours_since': hours_since_last,
            'last_message_time': last_message.timestamp
        }

    # ✅ TOUTES CONDITIONS REMPLIES
    return True, {
        'hours_since': hours_since_last,
        'last_message_time': last_message.timestamp,
        'eligible': True
    }


def should_send_night_reminder_telegram(telegram_id: int) -> Tuple[bool, Dict]:
    """
    Vérifie si on doit envoyer le rappel nuit Telegram (22h30)

    Returns:
        Tuple[bool, Dict]: (eligibilité, contexte avec infos de debug)
    """
    now = datetime.now()

    telegram_user = TelegramUser.query.get(telegram_id)

    if not telegram_user or not telegram_user.last_active:
        return False, {'reason': 'Utilisateur non trouvé ou jamais actif'}

    hours_since_last = (now - telegram_user.last_active).total_seconds() / 3600

    # CONDITION 1 : Fenêtre 24h (protection naturelle)
    if hours_since_last >= 24:
        return False, {
            'reason': 'Hors fenêtre 24h',
            'hours_since': hours_since_last,
            'last_active': telegram_user.last_active
        }

    # CONDITION 2 : Actif aujourd'hui (depuis 5h ce matin)
    morning_start = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if telegram_user.last_active < morning_start:
        return False, {
            'reason': 'Pas actif aujourd\'hui',
            'hours_since': hours_since_last,
            'last_active': telegram_user.last_active,
            'morning_start': morning_start
        }

    # CONDITION 3 : Pas en conversation active (< 30min)
    if hours_since_last < 0.5:
        return False, {
            'reason': 'En conversation active',
            'hours_since': hours_since_last,
            'last_active': telegram_user.last_active
        }

    # ✅ TOUTES CONDITIONS REMPLIES
    return True, {
        'hours_since': hours_since_last,
        'last_active': telegram_user.last_active,
        'eligible': True
    }


# ============================================
# COLLECTE DES UTILISATEURS ÉLIGIBLES
# ============================================

def get_eligible_whatsapp_users() -> List[Dict]:
    """
    Récupère tous les utilisateurs WhatsApp éligibles pour le rappel nuit

    Returns:
        List[Dict]: Liste de dicts avec {phone_number, thread_id, context}
    """
    eligible = []

    # Récupérer tous les threads WhatsApp uniques des dernières 24h
    cutoff_time = datetime.now() - timedelta(hours=24)

    recent_messages = WhatsAppMessage.query.filter(
        WhatsAppMessage.direction == 'inbound',
        WhatsAppMessage.timestamp >= cutoff_time,
        WhatsAppMessage.thread_id.isnot(None)
    ).order_by(WhatsAppMessage.timestamp.desc()).all()

    # Grouper par from_number pour éviter doublons
    users_seen = set()

    for msg in recent_messages:
        if msg.from_number in users_seen:
            continue

        # Vérifier les conditions
        is_eligible, context = should_send_night_reminder_whatsapp(
            msg.from_number,
            msg.thread_id
        )

        if is_eligible:
            eligible.append({
                'phone_number': msg.from_number,
                'thread_id': msg.thread_id,
                'context': context
            })
            users_seen.add(msg.from_number)

    logger.info(f"[WHATSAPP] {len(eligible)} utilisateurs éligibles sur {len(users_seen)} vérifiés")
    return eligible


def get_eligible_telegram_users() -> List[Dict]:
    """
    Récupère tous les utilisateurs Telegram éligibles pour le rappel nuit

    Returns:
        List[Dict]: Liste de dicts avec {telegram_id, thread_id, context}
    """
    eligible = []

    # Récupérer tous les utilisateurs Telegram actifs dans les dernières 24h
    cutoff_time = datetime.now() - timedelta(hours=24)

    active_users = TelegramUser.query.filter(
        TelegramUser.last_active >= cutoff_time
    ).all()

    for user in active_users:
        # Vérifier les conditions
        is_eligible, context = should_send_night_reminder_telegram(user.telegram_id)

        if is_eligible:
            # Récupérer le thread_id de la conversation la plus récente
            conversation = TelegramConversation.query.filter_by(
                telegram_user_id=user.telegram_id
            ).order_by(TelegramConversation.updated_at.desc()).first()

            if conversation:
                eligible.append({
                    'telegram_id': user.telegram_id,
                    'thread_id': conversation.thread_id,
                    'context': context
                })

    logger.info(f"[TELEGRAM] {len(eligible)} utilisateurs éligibles sur {len(active_users)} vérifiés")
    return eligible


# ============================================
# ENVOI DES RAPPELS
# ============================================

def send_reminder_to_whatsapp_user(user_data: Dict, scheduled_for: datetime) -> bool:
    """
    Envoie un rappel à un utilisateur WhatsApp
    """
    phone_number = user_data['phone_number']
    thread_id = user_data['thread_id']
    hours_since = user_data['context'].get('hours_since', 0)

    try:
        # Générer le message
        message = generate_reminder_message(
            user_identifier=phone_number,
            platform='whatsapp',
            thread_id=thread_id,
            reminder_type='night'
        )

        # Envoyer via WhatsApp
        from whatsapp_bot import send_reminder_whatsapp
        success = send_reminder_whatsapp(phone_number, message)

        # Si envoi réussi, sauvegarder dans WhatsAppMessage pour affichage admin
        if success:
            from models import WhatsAppMessage
            whatsapp_msg = WhatsAppMessage(
                message_id=f"reminder_{int(datetime.now().timestamp())}_{phone_number}",
                from_number=None,  # Message système
                to_number=phone_number,
                content=message,
                direction='outbound',
                status='sent',
                thread_id=thread_id,
                timestamp=datetime.now()
            )
            db.session.add(whatsapp_msg)

        # Logger dans ReminderLog
        log = ReminderLog(
            user_identifier=phone_number,
            platform='whatsapp',
            reminder_type='night',
            sent_at=datetime.now(),
            scheduled_for=scheduled_for,
            message_content=message,
            user_last_active=user_data['context'].get('last_message_time'),
            hours_since_active=hours_since,
            status='sent' if success else 'failed',
            error_message=None if success else 'Échec envoi WhatsApp API'
        )
        db.session.add(log)
        db.session.commit()

        return success

    except Exception as e:
        logger.error(f"[WHATSAPP] Erreur envoi rappel à {phone_number}: {str(e)}")

        # Logger l'échec
        try:
            log = ReminderLog(
                user_identifier=phone_number,
                platform='whatsapp',
                reminder_type='night',
                sent_at=datetime.now(),
                scheduled_for=scheduled_for,
                message_content=None,
                user_last_active=user_data['context'].get('last_message_time'),
                hours_since_active=hours_since,
                status='failed',
                error_message=str(e)
            )
            db.session.add(log)
            db.session.commit()
        except Exception as log_error:
            logger.error(f"Erreur logging: {str(log_error)}")

        return False


def send_reminder_to_telegram_user(user_data: Dict, scheduled_for: datetime) -> bool:
    """
    Envoie un rappel à un utilisateur Telegram
    """
    telegram_id = user_data['telegram_id']
    thread_id = user_data['thread_id']
    hours_since = user_data['context'].get('hours_since', 0)

    try:
        # Générer le message
        message = generate_reminder_message(
            user_identifier=str(telegram_id),
            platform='telegram',
            thread_id=thread_id,
            reminder_type='night'
        )

        # Envoyer via Telegram (fonction async)
        from telegram_bot import send_reminder_telegram
        import asyncio

        # Créer une nouvelle boucle ou utiliser l'existante
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        success = loop.run_until_complete(send_reminder_telegram(telegram_id, message))

        # Si envoi réussi, sauvegarder dans TelegramMessage pour affichage admin
        if success:
            from models import TelegramMessage, TelegramConversation

            # Trouver la conversation
            conversation = TelegramConversation.query.filter_by(
                thread_id=thread_id
            ).first()

            if conversation:
                telegram_msg = TelegramMessage(
                    conversation_id=conversation.id,
                    role='assistant',
                    content=message,
                    image_url=None,
                    created_at=datetime.now()
                )
                db.session.add(telegram_msg)

        # Logger dans ReminderLog
        log = ReminderLog(
            user_identifier=str(telegram_id),
            platform='telegram',
            reminder_type='night',
            sent_at=datetime.now(),
            scheduled_for=scheduled_for,
            message_content=message,
            user_last_active=user_data['context'].get('last_active'),
            hours_since_active=hours_since,
            status='sent' if success else 'failed',
            error_message=None if success else 'Échec envoi Telegram API'
        )
        db.session.add(log)
        db.session.commit()

        return success

    except Exception as e:
        logger.error(f"[TELEGRAM] Erreur envoi rappel à {telegram_id}: {str(e)}")

        # Logger l'échec
        try:
            log = ReminderLog(
                user_identifier=str(telegram_id),
                platform='telegram',
                reminder_type='night',
                sent_at=datetime.now(),
                scheduled_for=scheduled_for,
                message_content=None,
                user_last_active=user_data['context'].get('last_active'),
                hours_since_active=hours_since,
                status='failed',
                error_message=str(e)
            )
            db.session.add(log)
            db.session.commit()
        except Exception as log_error:
            logger.error(f"Erreur logging: {str(log_error)}")

        return False


def send_reminders_gradually(
    whatsapp_users: List[Dict],
    telegram_users: List[Dict],
    scheduled_for: datetime
) -> Dict[str, int]:
    """
    Envoie les rappels de façon graduelle avec délais aléatoires

    Args:
        whatsapp_users: Liste des utilisateurs WhatsApp éligibles
        telegram_users: Liste des utilisateurs Telegram éligibles
        scheduled_for: Datetime de l'heure prévue (22h30)

    Returns:
        Dict avec statistiques d'envoi
    """
    # Mélanger pour éviter patterns
    all_users = [
        {'platform': 'whatsapp', 'data': u} for u in whatsapp_users
    ] + [
        {'platform': 'telegram', 'data': u} for u in telegram_users
    ]

    random.shuffle(all_users)

    stats = {
        'whatsapp_sent': 0,
        'whatsapp_failed': 0,
        'telegram_sent': 0,
        'telegram_failed': 0,
        'total': len(all_users)
    }

    logger.info(f"[ENVOI GRADUEL] Début envoi de {len(all_users)} rappels")

    for i, user_info in enumerate(all_users):
        platform = user_info['platform']
        user_data = user_info['data']

        # Envoyer selon la plateforme
        if platform == 'whatsapp':
            success = send_reminder_to_whatsapp_user(user_data, scheduled_for)
            if success:
                stats['whatsapp_sent'] += 1
            else:
                stats['whatsapp_failed'] += 1
        else:  # telegram
            success = send_reminder_to_telegram_user(user_data, scheduled_for)
            if success:
                stats['telegram_sent'] += 1
            else:
                stats['telegram_failed'] += 1

        # Pause tous les 50 messages
        if (i + 1) % 50 == 0 and i + 1 < len(all_users):
            logger.info(f"[PAUSE] {i+1} messages traités, pause 5 minutes...")
            time.sleep(300)  # 5 minutes

        # Attente aléatoire entre 15 et 45 secondes
        if i + 1 < len(all_users):
            wait_time = random.randint(15, 45)
            time.sleep(wait_time)

    logger.info(f"[TERMINÉ] WhatsApp: {stats['whatsapp_sent']} envoyés, {stats['whatsapp_failed']} échecs")
    logger.info(f"[TERMINÉ] Telegram: {stats['telegram_sent']} envoyés, {stats['telegram_failed']} échecs")

    return stats


# ============================================
# JOB PRINCIPAL
# ============================================

def run_night_reminder_job():
    """
    Job principal exécuté à 22h30 tous les jours
    """
    from app import app

    with app.app_context():
        logger.info("\n" + "="*60)
        logger.info(f"[JOB NUIT] Démarrage à {datetime.now()}")
        logger.info("="*60)

        scheduled_for = datetime.now()

        # Récupérer les utilisateurs éligibles
        whatsapp_eligible = get_eligible_whatsapp_users()
        telegram_eligible = get_eligible_telegram_users()

        total_eligible = len(whatsapp_eligible) + len(telegram_eligible)

        if total_eligible == 0:
            logger.info("[JOB NUIT] Aucun utilisateur éligible, job terminé")
            return

        logger.info(f"[JOB NUIT] {total_eligible} utilisateurs éligibles au total")
        logger.info(f"  - WhatsApp: {len(whatsapp_eligible)}")
        logger.info(f"  - Telegram: {len(telegram_eligible)}")

        # Envoi graduel
        stats = send_reminders_gradually(
            whatsapp_eligible,
            telegram_eligible,
            scheduled_for
        )

        logger.info("="*60)
        logger.info(f"[JOB NUIT] Résumé final:")
        logger.info(f"  WhatsApp: ✅ {stats['whatsapp_sent']} | ❌ {stats['whatsapp_failed']}")
        logger.info(f"  Telegram: ✅ {stats['telegram_sent']} | ❌ {stats['telegram_failed']}")
        logger.info(f"  TOTAL: {stats['total']} utilisateurs traités")
        logger.info("="*60 + "\n")