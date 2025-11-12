from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, Tuple
from models import User, Plan, Subscription, UserUsage, db
from sqlalchemy import func
import json
import logging

logger = logging.getLogger(__name__)

class SubscriptionManager:
    """Gestionnaire principal des abonnements et limites pour utilisateurs web"""

    @staticmethod
    def get_user_current_plan(user_id: int) -> Dict[str, Any]:
        """
        Récupère le plan actuel de l'utilisateur web

        Args:
            user_id: ID de l'utilisateur

        Returns:
            Dict avec les informations du plan actuel
        """
        try:
            # Chercher l'abonnement actif le plus récent
            active_subscription = Subscription.query.filter_by(
                user_id=user_id,
                status='active'
            ).filter(
                Subscription.expiry_date > datetime.utcnow()
            ).order_by(Subscription.expiry_date.desc()).first()

            if active_subscription and active_subscription.plan:
                plan = active_subscription.plan
                return {
                    'plan_id': plan.id,
                    'name': plan.name,
                    'display_name': plan.display_name,
                    'price': plan.price,
                    'daily_message_limit': plan.daily_message_limit,
                    'features': json.loads(plan.features) if plan.features else {},
                    'subscription_id': active_subscription.id,
                    'expiry_date': active_subscription.expiry_date,
                    'is_premium': plan.price > 0
                }
            else:
                # Plan gratuit par défaut
                free_plan = Plan.query.filter_by(name='gratuit', is_active=True).first()
                if not free_plan:
                    raise Exception("Plan gratuit non trouvé dans la base de données")

                return {
                    'plan_id': free_plan.id,
                    'name': free_plan.name,
                    'display_name': free_plan.display_name,
                    'price': free_plan.price,
                    'daily_message_limit': free_plan.daily_message_limit,
                    'features': json.loads(free_plan.features) if free_plan.features else {},
                    'subscription_id': None,
                    'expiry_date': None,
                    'is_premium': False
                }

        except Exception as e:
            logger.error(f"Erreur lors de la récupération du plan utilisateur {user_id}: {e}")
            # Retourner un plan par défaut sécurisé
            return {
                'plan_id': None,
                'name': 'limited',
                'display_name': 'Plan Limité',
                'price': 0,
                'daily_message_limit': 10,
                'features': {'messages_per_day': 10, 'basic_ai': True},
                'subscription_id': None,
                'expiry_date': None,
                'is_premium': False
            }

    @staticmethod
    def get_user_daily_usage(user_id: int, target_date: date = None) -> int:
        """
        Récupère l'usage quotidien actuel de l'utilisateur

        Args:
            user_id: ID de l'utilisateur
            target_date: Date cible (défaut: aujourd'hui)

        Returns:
            Nombre de messages envoyés aujourd'hui
        """
        if target_date is None:
            target_date = date.today()

        try:
            usage = UserUsage.query.filter_by(
                user_id=user_id,
                date=target_date
            ).first()

            return usage.message_count if usage else 0

        except Exception as e:
            logger.error(f"Erreur lors de la récupération de l'usage utilisateur {user_id}: {e}")
            return 0

    @staticmethod
    def get_user_warning_count(user_id: int, target_date: date = None) -> int:
        """
        Récupère le nombre de messages d'avertissement envoyés aujourd'hui

        Args:
            user_id: ID de l'utilisateur
            target_date: Date cible (défaut: aujourd'hui)

        Returns:
            Nombre de messages d'avertissement envoyés
        """
        if target_date is None:
            target_date = date.today()

        try:
            usage = UserUsage.query.filter_by(
                user_id=user_id,
                date=target_date
            ).first()

            return usage.warning_messages_sent if usage else 0

        except Exception as e:
            logger.error(f"Erreur lors de la récupération du compteur de warnings pour l'utilisateur {user_id}: {e}")
            return 0

    @staticmethod
    def get_user_total_days_used(user_id: int) -> int:
        """
        Compte le nombre de jours distincts où l'utilisateur a envoyé des messages

        Args:
            user_id: ID de l'utilisateur

        Returns:
            Nombre de jours d'utilisation (7 jours = période de grâce terminée)
        """
        try:
            # Compter le nombre d'enregistrements UserUsage pour cet utilisateur
            # Chaque enregistrement = 1 jour où il a envoyé au moins 1 message
            days_count = UserUsage.query.filter_by(user_id=user_id).count()

            logger.debug(f"Utilisateur {user_id} a utilisé le service pendant {days_count} jours")
            return days_count

        except Exception as e:
            logger.error(f"Erreur lors du comptage des jours d'utilisation pour l'utilisateur {user_id}: {e}")
            return 0

    @staticmethod
    def increment_warning_count(user_id: int) -> bool:
        """
        Incrémente le compteur de messages d'avertissement

        Args:
            user_id: ID de l'utilisateur

        Returns:
            True si succès, False sinon
        """
        try:
            today = date.today()

            # Chercher l'enregistrement d'usage du jour
            usage = UserUsage.query.filter_by(
                user_id=user_id,
                date=today
            ).first()

            if usage:
                usage.warning_messages_sent += 1
                usage.updated_at = datetime.utcnow()
            else:
                # Créer un nouvel enregistrement
                usage = UserUsage(
                    user_id=user_id,
                    date=today,
                    message_count=0,
                    warning_messages_sent=1
                )
                db.session.add(usage)

            db.session.commit()
            logger.debug(f"Warning count incrémenté pour utilisateur {user_id}: {usage.warning_messages_sent} warnings")
            return True

        except Exception as e:
            logger.error(f"Erreur lors de l'incrémentation du warning count pour l'utilisateur {user_id}: {e}")
            db.session.rollback()
            return False

    @staticmethod
    def can_send_message(user_id: int) -> Tuple[str, str, int, Dict[str, Any]]:
        """
        Vérifie si l'utilisateur peut envoyer un message

        Args:
            user_id: ID de l'utilisateur

        Returns:
            Tuple (statut, message_erreur, warning_count, infos_plan)
            - statut: "allowed", "warning", ou "blocked"
            - message_erreur: Message d'erreur si applicable
            - warning_count: Nombre de warnings déjà envoyés aujourd'hui
            - infos_plan: Informations sur le plan de l'utilisateur
        """
        try:
            # Récupérer le plan actuel
            current_plan = SubscriptionManager.get_user_current_plan(user_id)

            # Si pas de limite (plan Pro), autoriser
            if current_plan['daily_message_limit'] is None:
                return "allowed", "", 0, current_plan

            # 🆕 PÉRIODE DE GRÂCE : Vérifier si l'utilisateur a moins de 7 jours d'utilisation
            total_days_used = SubscriptionManager.get_user_total_days_used(user_id)
            if total_days_used < 7:
                logger.info(f"[PÉRIODE DE GRÂCE] Utilisateur {user_id} en période de grâce ({total_days_used}/7 jours)")
                return "allowed", "", 0, current_plan

            # Récupérer l'usage du jour
            today_usage = SubscriptionManager.get_user_daily_usage(user_id)

            # Vérifier si la limite est atteinte
            if today_usage >= current_plan['daily_message_limit']:
                # Récupérer le nombre de warnings déjà envoyés
                warning_count = SubscriptionManager.get_user_warning_count(user_id)

                # Si moins de 6 warnings envoyés, passer en mode "warning"
                if warning_count < 6:
                    return "warning", "", warning_count, current_plan

                # Si 6 warnings ou plus, bloquer vraiment
                if current_plan['is_premium']:
                    error_msg = f"Limite quotidienne atteinte ({current_plan['daily_message_limit']} messages). Votre abonnement {current_plan['display_name']} sera renouvelé demain."
                else:
                    error_msg = f"Limite quotidienne atteinte ({current_plan['daily_message_limit']} messages). Passez au plan Premium pour continuer !"

                return "blocked", error_msg, warning_count, current_plan

            return "allowed", "", 0, current_plan

        except Exception as e:
            logger.error(f"Erreur lors de la vérification des limites pour l'utilisateur {user_id}: {e}")
            # En cas d'erreur, autoriser mais avec un avertissement
            return "allowed", "Vérification des limites temporairement indisponible", 0, {}

    @staticmethod
    def increment_user_usage(user_id: int) -> bool:
        """
        Incrémente l'usage quotidien de l'utilisateur

        Args:
            user_id: ID de l'utilisateur

        Returns:
            True si succès, False sinon
        """
        try:
            today = date.today()

            # Chercher l'enregistrement d'usage du jour
            usage = UserUsage.query.filter_by(
                user_id=user_id,
                date=today
            ).first()

            if usage:
                # Incrémenter le compteur existant
                usage.message_count += 1
                usage.updated_at = datetime.utcnow()
            else:
                # Créer un nouvel enregistrement
                usage = UserUsage(
                    user_id=user_id,
                    date=today,
                    message_count=1
                )
                db.session.add(usage)

            db.session.commit()
            logger.debug(f"Usage incrémenté pour utilisateur {user_id}: {usage.message_count} messages")
            return True

        except Exception as e:
            logger.error(f"Erreur lors de l'incrémentation de l'usage pour l'utilisateur {user_id}: {e}")
            db.session.rollback()
            return False

    @staticmethod
    def create_subscription(user_id: int, plan_id: int, transaction_id: int = None) -> Optional[Subscription]:
        """
        Crée un nouvel abonnement pour l'utilisateur

        Args:
            user_id: ID de l'utilisateur
            plan_id: ID du plan
            transaction_id: ID de la transaction de paiement (optionnel)

        Returns:
            L'abonnement créé ou None si erreur
        """
        try:
            # Récupérer le plan
            plan = Plan.query.get(plan_id)
            if not plan:
                logger.error(f"Plan {plan_id} non trouvé")
                return None

            # Désactiver les anciens abonnements
            old_subscriptions = Subscription.query.filter_by(
                user_id=user_id,
                status='active'
            ).all()

            for old_sub in old_subscriptions:
                old_sub.status = 'cancelled'

            # Créer le nouvel abonnement
            start_date = datetime.utcnow()
            expiry_date = start_date + timedelta(days=plan.duration_days)

            subscription = Subscription(
                user_id=user_id,
                plan_id=plan_id,
                transaction_id=transaction_id,
                subscription_type=plan.name,
                start_date=start_date,
                expiry_date=expiry_date,
                status='active',
                last_payment_date=start_date if plan.price > 0 else None,
                auto_renewal=False
            )

            db.session.add(subscription)
            db.session.commit()

            logger.info(f"Abonnement créé pour utilisateur {user_id}: Plan {plan.display_name} jusqu'au {expiry_date}")
            return subscription

        except Exception as e:
            logger.error(f"Erreur lors de la création de l'abonnement: {e}")
            db.session.rollback()
            return None

    @staticmethod
    def get_available_plans() -> list:
        """
        Récupère tous les plans disponibles

        Returns:
            Liste des plans actifs
        """
        try:
            plans = Plan.query.filter_by(is_active=True).order_by(Plan.price).all()

            return [{
                'id': plan.id,
                'name': plan.name,
                'display_name': plan.display_name,
                'price': plan.price,
                'duration_days': plan.duration_days,
                'daily_message_limit': plan.daily_message_limit,
                'features': json.loads(plan.features) if plan.features else {},
                'is_free': plan.price == 0
            } for plan in plans]

        except Exception as e:
            logger.error(f"Erreur lors de la récupération des plans: {e}")
            return []


class MessageLimitChecker:
    """Classe utilitaire pour vérifier les limites avant l'envoi de messages"""

    @staticmethod
    def check_and_increment(user_id: int) -> Tuple[str, str, int]:
        """
        Vérifie les limites et incrémente l'usage si autorisé

        Args:
            user_id: ID de l'utilisateur

        Returns:
            Tuple (statut, message_erreur, warning_count)
            - statut: "allowed", "warning", ou "blocked"
            - message_erreur: Message d'erreur si bloqué
            - warning_count: Nombre de warnings envoyés
        """
        # Vérifier si l'utilisateur peut envoyer un message
        status, error_msg, warning_count, plan_info = SubscriptionManager.can_send_message(user_id)

        if status == "blocked":
            return "blocked", error_msg, warning_count

        if status == "warning":
            # Incrémenter le compteur de warnings
            SubscriptionManager.increment_warning_count(user_id)
            warning_count += 1

        # Incrémenter l'usage dans tous les cas (allowed et warning)
        if not SubscriptionManager.increment_user_usage(user_id):
            return "blocked", "Erreur lors de l'enregistrement de l'usage", warning_count

        return status, "", warning_count

    @staticmethod
    def get_user_limits_info(user_id: int) -> Dict[str, Any]:
        """
        Récupère les informations de limite pour l'utilisateur

        Args:
            user_id: ID de l'utilisateur

        Returns:
            Dictionnaire avec les informations de limite
        """
        current_plan = SubscriptionManager.get_user_current_plan(user_id)
        today_usage = SubscriptionManager.get_user_daily_usage(user_id)

        if current_plan['daily_message_limit'] is None:
            remaining = "Illimité"
            percentage_used = 0
        else:
            remaining = max(0, current_plan['daily_message_limit'] - today_usage)
            percentage_used = min(100, (today_usage / current_plan['daily_message_limit']) * 100)

        return {
            'plan_name': current_plan['display_name'],
            'daily_limit': current_plan['daily_message_limit'],
            'used_today': today_usage,
            'remaining': remaining,
            'percentage_used': percentage_used,
            'is_premium': current_plan['is_premium'],
            'expiry_date': current_plan['expiry_date']
        }