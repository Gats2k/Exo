import logging
from app import app, db
from models import User, TelegramUser
from whatsapp_bot import WhatsAppMessage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_all_whatsapp_users():
    """Crée un User pour tous les utilisateurs WhatsApp qui n'en ont pas."""
    logger.info("="*60)
    logger.info("📱 MIGRATION WHATSAPP - DÉBUT")
    logger.info("="*60)

    with app.app_context():
        # Récupérer tous les numéros uniques
        wa_numbers = db.session.query(WhatsAppMessage.from_number).distinct().all()
        total = len(wa_numbers)
        created = 0
        skipped = 0
        errors = 0

        logger.info(f"Total de numéros WhatsApp uniques trouvés : {total}")

        for idx, (number,) in enumerate(wa_numbers, 1):
            try:
                user_phone_id = f"whatsapp_{number}"

                # Vérifier si le User existe déjà
                existing_user = User.query.filter_by(phone_number=user_phone_id).first()

                if existing_user:
                    skipped += 1
                    if idx % 100 == 0:
                        logger.info(f"  Progression : {idx}/{total} ({skipped} déjà existants)")
                    continue

                # Créer le User
                new_user = User(
                    phone_number=user_phone_id,
                    first_name="Utilisateur",
                    last_name=f"WA {number[-4:]}",
                    age=0,
                    study_level="Non défini",
                    grade_goals="average"
                )
                db.session.add(new_user)

                # Commit par batch de 50 pour sécurité
                if (idx - skipped) % 50 == 0:
                    db.session.commit()
                    logger.info(f"  ✅ Batch commit : {idx}/{total} traités ({created + (idx - skipped - errors)} créés)")

                created += 1

            except Exception as e:
                logger.error(f"  ❌ Erreur pour le numéro {number}: {e}")
                db.session.rollback()
                errors += 1

        # Commit final
        try:
            db.session.commit()
            logger.info(f"\n✅ MIGRATION WHATSAPP TERMINÉE")
            logger.info(f"  Total traité : {total}")
            logger.info(f"  Créés : {created}")
            logger.info(f"  Déjà existants : {skipped}")
            logger.info(f"  Erreurs : {errors}")
        except Exception as e:
            logger.error(f"❌ Erreur lors du commit final WhatsApp: {e}")
            db.session.rollback()


def migrate_all_telegram_users():
    """Crée un User pour tous les utilisateurs Telegram qui n'en ont pas."""
    logger.info("\n" + "="*60)
    logger.info("📱 MIGRATION TELEGRAM - DÉBUT")
    logger.info("="*60)

    with app.app_context():
        # Récupérer tous les TelegramUser
        tg_users = TelegramUser.query.all()
        total = len(tg_users)
        created = 0
        skipped = 0
        errors = 0

        logger.info(f"Total d'utilisateurs Telegram trouvés : {total}")

        for idx, tg_user in enumerate(tg_users, 1):
            try:
                user_phone_id = f"telegram_{tg_user.telegram_id}"

                # Vérifier si le User existe déjà
                existing_user = User.query.filter_by(phone_number=user_phone_id).first()

                if existing_user:
                    skipped += 1
                    if idx % 50 == 0:
                        logger.info(f"  Progression : {idx}/{total} ({skipped} déjà existants)")
                    continue

                # Créer le User
                new_user = User(
                    phone_number=user_phone_id,
                    first_name=tg_user.first_name or "Utilisateur",
                    last_name=tg_user.last_name or f"TG {tg_user.telegram_id}",
                    age=0,
                    study_level="Non défini",
                    grade_goals="average"
                )
                db.session.add(new_user)

                # Commit par batch de 50 pour sécurité
                if (idx - skipped) % 50 == 0:
                    db.session.commit()
                    logger.info(f"  ✅ Batch commit : {idx}/{total} traités ({created + (idx - skipped - errors)} créés)")

                created += 1

            except Exception as e:
                logger.error(f"  ❌ Erreur pour telegram_id {tg_user.telegram_id}: {e}")
                db.session.rollback()
                errors += 1

        # Commit final
        try:
            db.session.commit()
            logger.info(f"\n✅ MIGRATION TELEGRAM TERMINÉE")
            logger.info(f"  Total traité : {total}")
            logger.info(f"  Créés : {created}")
            logger.info(f"  Déjà existants : {skipped}")
            logger.info(f"  Erreurs : {errors}")
        except Exception as e:
            logger.error(f"❌ Erreur lors du commit final Telegram: {e}")
            db.session.rollback()


def run_full_migration():
    """Exécute la migration complète pour toutes les plateformes."""
    logger.info("\n" + "🚀"*30)
    logger.info("MIGRATION COMPLÈTE - DÉMARRAGE")
    logger.info("🚀"*30 + "\n")

    import time
    start_time = time.time()

    try:
        # Migration WhatsApp
        migrate_all_whatsapp_users()

        # Migration Telegram
        migrate_all_telegram_users()

        # Résumé final
        elapsed_time = time.time() - start_time
        logger.info("\n" + "="*60)
        logger.info("✅ MIGRATION COMPLÈTE TERMINÉE AVEC SUCCÈS")
        logger.info("="*60)
        logger.info(f"Temps d'exécution : {elapsed_time:.2f} secondes")
        logger.info("\nTous les utilisateurs existants ont maintenant un user_id.")
        logger.info("Le système de mémoire peut maintenant fonctionner pour tous.")

    except Exception as e:
        logger.error(f"\n❌ ERREUR CRITIQUE LORS DE LA MIGRATION: {e}", exc_info=True)
        logger.error("La migration a échoué. Vérifiez les logs ci-dessus.")


if __name__ == '__main__':
    # Confirmation de sécurité
    print("\n⚠️  ATTENTION : Vous allez migrer ~1092 utilisateurs.")
    print("Cette opération va créer des User records pour tous les utilisateurs WhatsApp et Telegram.")
    print("\nAppuyez sur ENTRÉE pour continuer ou CTRL+C pour annuler...")
    input()

    run_full_migration()