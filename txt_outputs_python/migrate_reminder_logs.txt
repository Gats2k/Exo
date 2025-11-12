"""
Script sécurisé pour importer les messages de rappel depuis ReminderLog 
vers WhatsAppMessage et TelegramMessage
Version avec dry-run et protections renforcées
"""

from app import app
from database import db
from models import (
    ReminderLog, WhatsAppMessage, TelegramMessage, 
    TelegramConversation
)
from datetime import datetime
import sys

def check_database_integrity():
    """Vérifie l'intégrité de la base avant migration"""
    with app.app_context():
        try:
            # Vérifier que les tables existent
            ReminderLog.query.first()
            WhatsAppMessage.query.first()
            TelegramMessage.query.first()
            TelegramConversation.query.first()
            return True
        except Exception as e:
            print(f"❌ ERREUR: Tables de base de données non accessibles: {str(e)}")
            return False

def migrate_reminder_logs(dry_run=True):
    """
    Importe tous les rappels envoyés depuis ReminderLog 
    vers les tables de messages pour affichage admin

    Args:
        dry_run: Si True, simule sans écrire en base (mode test)
    """
    with app.app_context():
        print("\n" + "="*70)
        if dry_run:
            print("🧪 MODE TEST (DRY-RUN) - Aucune modification en base")
        else:
            print("⚠️  MODE RÉEL - Les modifications seront appliquées")
        print("🔄 MIGRATION DES RAPPELS VERS HISTORIQUE CONVERSATIONS")
        print("="*70 + "\n")

        # Récupérer tous les rappels envoyés avec succès
        reminder_logs = ReminderLog.query.filter_by(status='sent').order_by(ReminderLog.sent_at.asc()).all()

        if not reminder_logs:
            print("ℹ️  Aucun rappel à migrer dans ReminderLog\n")
            return

        print(f"📊 {len(reminder_logs)} rappels trouvés dans ReminderLog")

        # Compter par plateforme
        whatsapp_count = sum(1 for log in reminder_logs if log.platform == 'whatsapp')
        telegram_count = sum(1 for log in reminder_logs if log.platform == 'telegram')

        print(f"   - WhatsApp: {whatsapp_count}")
        print(f"   - Telegram: {telegram_count}\n")

        if dry_run:
            print("🔍 Analyse des rappels...\n")

        stats = {
            'whatsapp_migrated': 0,
            'whatsapp_skipped': 0,
            'whatsapp_errors': 0,
            'telegram_migrated': 0,
            'telegram_skipped': 0,
            'telegram_errors': 0
        }

        for i, log in enumerate(reminder_logs, 1):
            try:
                print(f"[{i}/{len(reminder_logs)}] ", end="")

                if log.platform == 'whatsapp':
                    # === MIGRATION WHATSAPP ===

                    # 1. NOUVEAU : Vérifier si l'utilisateur a déjà répondu APRÈS le rappel
                    user_response_after = WhatsAppMessage.query.filter(
                        WhatsAppMessage.from_number == log.user_identifier,
                        WhatsAppMessage.direction == 'inbound',
                        WhatsAppMessage.timestamp > log.sent_at
                    ).first()

                    if user_response_after:
                        stats['whatsapp_skipped'] += 1
                        print(f"⏭️  WhatsApp {log.user_identifier} - utilisateur a déjà répondu ({user_response_after.timestamp.strftime('%H:%M')})")
                        continue

                    # 2. Vérifier si déjà migré via message_id unique
                    message_id = f"reminder_{int(log.sent_at.timestamp())}_{log.user_identifier}"
                    existing_by_id = WhatsAppMessage.query.filter_by(
                        message_id=message_id
                    ).first()

                    if existing_by_id:
                        stats['whatsapp_skipped'] += 1
                        print(f"⏭️  WhatsApp {log.user_identifier} - déjà migré (ID existe)")
                        continue

                    # 3. Double vérification par contenu + timestamp (sécurité)
                    existing_by_content = WhatsAppMessage.query.filter_by(
                        to_number=log.user_identifier,
                        content=log.message_content,
                        timestamp=log.sent_at
                    ).first()

                    if existing_by_content:
                        stats['whatsapp_skipped'] += 1
                        print(f"⏭️  WhatsApp {log.user_identifier} - déjà migré (contenu existe)")
                        continue

                    # 4. Trouver le thread_id depuis les messages existants
                    last_message = WhatsAppMessage.query.filter_by(
                        from_number=log.user_identifier
                    ).order_by(WhatsAppMessage.timestamp.desc()).first()

                    thread_id = last_message.thread_id if last_message else f"thread_{log.user_identifier}"

                    # 5. Créer le message WhatsApp (si pas dry-run)
                    if not dry_run:
                        whatsapp_msg = WhatsAppMessage(
                            message_id=message_id,
                            from_number=None,  # Message système
                            to_number=log.user_identifier,
                            content=log.message_content,
                            direction='outbound',
                            status='sent',
                            thread_id=thread_id,
                            timestamp=log.sent_at
                        )
                        db.session.add(whatsapp_msg)

                    stats['whatsapp_migrated'] += 1
                    mode_text = "(simulé)" if dry_run else ""
                    print(f"✅ WhatsApp {log.user_identifier} - migré {mode_text}")

                elif log.platform == 'telegram':
                    # === MIGRATION TELEGRAM ===

                    # 1. Convertir user_identifier en int
                    try:
                        telegram_id = int(log.user_identifier)
                    except ValueError:
                        stats['telegram_errors'] += 1
                        print(f"❌ Telegram {log.user_identifier} - ID invalide")
                        continue

                    # 2. Trouver la conversation Telegram
                    conversation = TelegramConversation.query.filter_by(
                        telegram_user_id=telegram_id
                    ).order_by(TelegramConversation.updated_at.desc()).first()

                    if not conversation:
                        stats['telegram_skipped'] += 1
                        print(f"⚠️  Telegram {telegram_id} - conversation non trouvée")
                        continue

                    # 3. NOUVEAU : Vérifier si l'utilisateur a déjà répondu APRÈS le rappel
                    user_response_after = TelegramMessage.query.filter(
                        TelegramMessage.conversation_id == conversation.id,
                        TelegramMessage.role == 'user',
                        TelegramMessage.created_at > log.sent_at
                    ).first()

                    if user_response_after:
                        stats['telegram_skipped'] += 1
                        print(f"⏭️  Telegram {telegram_id} - utilisateur a déjà répondu ({user_response_after.created_at.strftime('%H:%M')})")
                        continue

                    # 4. Vérifier si déjà migré
                    existing = TelegramMessage.query.filter_by(
                        conversation_id=conversation.id,
                        content=log.message_content,
                        created_at=log.sent_at
                    ).first()

                    if existing:
                        stats['telegram_skipped'] += 1
                        print(f"⏭️  Telegram {telegram_id} - déjà migré")
                        continue

                    # 5. Créer le message Telegram (si pas dry-run)
                    if not dry_run:
                        telegram_msg = TelegramMessage(
                            conversation_id=conversation.id,
                            role='assistant',
                            content=log.message_content,
                            image_url=None,
                            created_at=log.sent_at
                        )
                        db.session.add(telegram_msg)

                    stats['telegram_migrated'] += 1
                    mode_text = "(simulé)" if dry_run else ""
                    print(f"✅ Telegram {telegram_id} - migré {mode_text}")

                else:
                    print(f"⚠️  Plateforme inconnue: {log.platform}")

            except Exception as e:
                if log.platform == 'whatsapp':
                    stats['whatsapp_errors'] += 1
                else:
                    stats['telegram_errors'] += 1
                print(f"❌ Erreur {log.platform}/{log.user_identifier}: {str(e)}")
                continue

        # Commit final (seulement si pas dry-run)
        if not dry_run:
            try:
                db.session.commit()
                print("\n✅ Toutes les modifications ont été enregistrées en base\n")
            except Exception as e:
                db.session.rollback()
                print(f"\n❌ ERREUR CRITIQUE lors du commit: {str(e)}")
                print("🔄 Rollback effectué - Aucune modification n'a été appliquée\n")
                return False
        else:
            db.session.rollback()  # Annuler les ajouts simulés
            print("\n🧪 Mode test - Aucune modification appliquée\n")

        # Afficher les résultats
        print("="*70)
        print("📊 RÉSULTATS DE LA MIGRATION")
        print("="*70)
        print(f"WhatsApp:")
        print(f"  ✅ Migrés: {stats['whatsapp_migrated']}")
        print(f"  ⏭️  Skippés: {stats['whatsapp_skipped']}")
        print(f"  ❌ Erreurs: {stats['whatsapp_errors']}")
        print(f"\nTelegram:")
        print(f"  ✅ Migrés: {stats['telegram_migrated']}")
        print(f"  ⏭️  Skippés: {stats['telegram_skipped']}")
        print(f"  ❌ Erreurs: {stats['telegram_errors']}")

        total_migrated = stats['whatsapp_migrated'] + stats['telegram_migrated']
        total_skipped = stats['whatsapp_skipped'] + stats['telegram_skipped']
        total_errors = stats['whatsapp_errors'] + stats['telegram_errors']

        print(f"\n{'='*70}")
        print(f"TOTAL: {total_migrated} migrés | {total_skipped} skippés | {total_errors} erreurs")
        print("="*70 + "\n")

        if dry_run:
            print("ℹ️  Pour appliquer ces modifications, relance avec: python migrate_reminder_logs.py --real\n")
        else:
            print("✅ Migration terminée avec succès !\n")

        return True

if __name__ == '__main__':
    # Vérifier l'intégrité de la base
    if not check_database_integrity():
        sys.exit(1)

    # Déterminer le mode (dry-run par défaut)
    if '--real' in sys.argv:
        print("\n⚠️  ATTENTION: Tu vas modifier la base de données en mode RÉEL")
        confirm = input("Taper 'OUI' pour confirmer: ")
        if confirm.upper() == 'OUI':
            migrate_reminder_logs(dry_run=False)
        else:
            print("❌ Migration annulée\n")
    else:
        # Mode test par défaut
        migrate_reminder_logs(dry_run=True)