import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User, Plan, Subscription, Transaction, UserUsage
from subscription_manager import SubscriptionManager, MessageLimitChecker
from datetime import datetime, date
import json

def test_subscription_manager():
    """Test du gestionnaire d'abonnements pour utilisateurs web"""
    print("🧪 TESTS DU GESTIONNAIRE D'ABONNEMENTS (UTILISATEURS WEB)")
    print("=" * 60)

    with app.app_context():
        # 1. Test de récupération des plans
        print("1. Test de récupération des plans...")
        plans = SubscriptionManager.get_available_plans()
        print(f"   ✅ {len(plans)} plan(s) disponible(s)")
        for plan in plans:
            print(f"      • {plan['display_name']}: {plan['price']} FCFA")

        # 2. Test avec un utilisateur web standard (pas Telegram/WhatsApp)
        web_user = User.query.filter(
            ~User.phone_number.like('telegram_%'),
            ~User.phone_number.like('whatsapp_%')
        ).first()

        if not web_user:
            print("   ❌ Aucun utilisateur web standard trouvé pour les tests")
            print("   💡 Créez un utilisateur web via /register pour tester")
            return False

        print(f"\n2. Test avec l'utilisateur web: {web_user.first_name} {web_user.last_name}")
        print(f"   📞 Téléphone: {web_user.phone_number}")

        # 3. Test de récupération du plan actuel
        current_plan = SubscriptionManager.get_user_current_plan(web_user.id)
        print(f"   ✅ Plan actuel: {current_plan['display_name']}")
        print(f"      • Limite quotidienne: {current_plan['daily_message_limit'] or 'Illimité'}")
        print(f"      • Premium: {current_plan['is_premium']}")

        # 4. Test de vérification des limites
        can_send, error_msg, plan_info = SubscriptionManager.can_send_message(web_user.id)
        print(f"   ✅ Peut envoyer message: {can_send}")
        if error_msg:
            print(f"      • Message d'erreur: {error_msg}")

        # 5. Test d'incrémentation d'usage
        print(f"\n3. Test d'incrémentation d'usage...")
        usage_before = SubscriptionManager.get_user_daily_usage(web_user.id)
        print(f"   • Usage avant: {usage_before}")

        success = SubscriptionManager.increment_user_usage(web_user.id)
        if success:
            usage_after = SubscriptionManager.get_user_daily_usage(web_user.id)
            print(f"   ✅ Usage après: {usage_after} (+{usage_after - usage_before})")
        else:
            print(f"   ❌ Échec de l'incrémentation")

        # 6. Test du MessageLimitChecker
        print(f"\n4. Test du vérificateur de limites...")
        limits_info = MessageLimitChecker.get_user_limits_info(web_user.id)
        print(f"   ✅ Informations de limite récupérées:")
        print(f"      • Plan: {limits_info['plan_name']}")
        print(f"      • Utilisé aujourd'hui: {limits_info['used_today']}")
        print(f"      • Restant: {limits_info['remaining']}")
        print(f"      • Pourcentage utilisé: {limits_info['percentage_used']:.1f}%")

        return True

def test_plan_creation():
    """Test de création d'abonnement pour utilisateur web"""
    print("\n🧪 TEST DE CRÉATION D'ABONNEMENT (UTILISATEUR WEB)")
    print("=" * 60)

    with app.app_context():
        web_user = User.query.filter(
            ~User.phone_number.like('telegram_%'),
            ~User.phone_number.like('whatsapp_%')
        ).first()

        if not web_user:
            print("❌ Aucun utilisateur web pour le test")
            return False

        # Récupérer le plan premium
        premium_plan = Plan.query.filter_by(name='premium').first()
        if not premium_plan:
            print("❌ Plan premium non trouvé")
            return False

        print(f"Test de création d'abonnement premium pour {web_user.first_name}")

        # Créer l'abonnement
        subscription = SubscriptionManager.create_subscription(
            user_id=web_user.id,
            plan_id=premium_plan.id
        )

        if subscription:
            print(f"✅ Abonnement créé avec succès:")
            print(f"   • ID: {subscription.id}")
            print(f"   • Plan: {subscription.plan.display_name}")
            print(f"   • Début: {subscription.start_date}")
            print(f"   • Fin: {subscription.expiry_date}")
            print(f"   • Statut: {subscription.status}")

            # Vérifier le nouveau plan de l'utilisateur
            new_plan = SubscriptionManager.get_user_current_plan(web_user.id)
            print(f"   • Nouveau plan utilisateur: {new_plan['display_name']}")

            return True
        else:
            print("❌ Échec de création d'abonnement")
            return False

def test_transaction_model():
    """Test du modèle Transaction"""
    print("\n🧪 TEST DU MODÈLE TRANSACTION")
    print("=" * 60)

    with app.app_context():
        web_user = User.query.filter(
            ~User.phone_number.like('telegram_%'),
            ~User.phone_number.like('whatsapp_%')
        ).first()

        plan = Plan.query.filter_by(name='premium').first()

        if not web_user or not plan:
            print("❌ Utilisateur web ou plan manquant")
            return False

        # Créer une transaction de test
        transaction = Transaction(
            user_id=web_user.id,
            plan_id=plan.id,
            amount=plan.price,
            phone_number="22507123456",
            operator="orange",
            service_id=26,
            status="pending",
            custom_data=json.dumps({"test": True, "user_type": "web"})
        )

        db.session.add(transaction)
        db.session.commit()

        print(f"✅ Transaction créée:")
        print(f"   • ID: {transaction.id}")
        print(f"   • Utilisateur: {transaction.user.first_name} {transaction.user.last_name}")
        print(f"   • Plan: {transaction.plan.display_name}")
        print(f"   • Montant: {transaction.amount} FCFA")
        print(f"   • Opérateur: {transaction.operator}")
        print(f"   • Statut: {transaction.status}")

        return True

def test_limit_logic():
    """Test de la logique de limite pour utilisateurs web"""
    print("\n🧪 TEST DE LA LOGIQUE DE LIMITE (UTILISATEURS WEB)")
    print("=" * 60)

    with app.app_context():
        web_user = User.query.filter(
            ~User.phone_number.like('telegram_%'),
            ~User.phone_number.like('whatsapp_%')
        ).first()

        if not web_user:
            print("❌ Aucun utilisateur web pour le test")
            return False

        print(f"Test avec l'utilisateur web: {web_user.first_name}")

        # Test 1: Vérifier la limite actuelle
        can_send_1, error_1 = MessageLimitChecker.check_and_increment(web_user.id)
        print(f"✅ Premier message - Autorisé: {can_send_1}")

        # Test 2: Simuler plusieurs envois
        count = 0
        for i in range(5):
            can_send, error = MessageLimitChecker.check_and_increment(web_user.id)
            if can_send:
                count += 1
            else:
                print(f"   ⚠️  Limite atteinte après {count} messages: {error}")
                break

        print(f"✅ {count} message(s) supplémentaire(s) envoyé(s)")

        # Afficher l'état final
        limits_info = MessageLimitChecker.get_user_limits_info(web_user.id)
        print(f"✅ État final:")
        print(f"   • Utilisé: {limits_info['used_today']}")
        print(f"   • Restant: {limits_info['remaining']}")

        return True

def test_payment_routes():
    """Test des routes de paiement"""
    print("\n🧪 TEST DES ROUTES DE PAIEMENT")
    print("=" * 60)

    with app.app_context():
        from payment_routes import payment_bp

        print("✅ Blueprint payment_bp importé avec succès")

        # Vérifier que les routes existent
        routes = []
        for rule in app.url_map.iter_rules():
            if rule.endpoint and rule.endpoint.startswith('payment.'):
                routes.append(f"{rule.rule} -> {rule.endpoint}")

        print(f"✅ Routes de paiement détectées ({len(routes)}):")
        for route in routes:
            print(f"   • {route}")

        return len(routes) > 0

def test_environment_config():
    """Test de la configuration d'environnement"""
    print("\n🧪 TEST DE LA CONFIGURATION ENVIRONNEMENT")
    print("=" * 60)

    required_vars = ['EASYTRANSFERT_API_KEY', 'IPN_BASE_URL']
    missing_vars = []

    for var in required_vars:
        value = os.getenv(var)
        if value:
            if var == 'EASYTRANSFERT_API_KEY':
                masked_value = value[:10] + "***" if len(value) > 10 else "***"
                print(f"   ✅ {var}: {masked_value}")
            else:
                print(f"   ✅ {var}: {value}")
        else:
            missing_vars.append(var)
            print(f"   ❌ {var}: MANQUANTE")

    if missing_vars:
        print(f"\n⚠️  Variables manquantes: {', '.join(missing_vars)}")
        print("   Ajoutez-les dans l'onglet Secrets de Replit")
        return False

    return True

def test_database_tables():
    """Test de l'existence des tables nécessaires"""
    print("\n🧪 TEST DES TABLES DE BASE DE DONNÉES")
    print("=" * 60)

    with app.app_context():
        try:
            # Test des nouvelles tables
            plan_count = Plan.query.count()
            subscription_count = Subscription.query.count()
            transaction_count = Transaction.query.count()
            usage_count = UserUsage.query.count()

            print(f"✅ Table Plan: {plan_count} enregistrement(s)")
            print(f"✅ Table Subscription: {subscription_count} enregistrement(s)")
            print(f"✅ Table Transaction: {transaction_count} enregistrement(s)")
            print(f"✅ Table UserUsage: {usage_count} enregistrement(s)")

            # Vérifier que les plans de base existent
            if plan_count == 0:
                print("⚠️  Aucun plan trouvé. Exécutez init_plans.py")
                return False

            return True

        except Exception as e:
            print(f"❌ Erreur d'accès aux tables: {str(e)}")
            return False

def run_all_tests():
    """Exécute tous les tests d'intégration"""
    print("🚀 DÉBUT DES TESTS D'INTÉGRATION PAIEMENT (UTILISATEURS WEB)")
    print("=" * 70)

    tests = [
        ("Configuration environnement", test_environment_config),
        ("Tables de base de données", test_database_tables),
        ("Routes de paiement", test_payment_routes),
        ("Gestionnaire d'abonnements", test_subscription_manager),
        ("Création d'abonnement", test_plan_creation),
        ("Modèle Transaction", test_transaction_model),
        ("Logique de limite", test_limit_logic)
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Erreur dans {test_name}: {e}")
            results.append((test_name, False))

    # Résumé
    print("\n" + "=" * 70)
    print("📊 RÉSUMÉ DES TESTS")
    print("=" * 70)

    passed = 0
    for test_name, result in results:
        status = "✅ PASSÉ" if result else "❌ ÉCHEC"
        print(f"{status} - {test_name}")
        if result:
            passed += 1

    print(f"\n🎯 RÉSULTAT: {passed}/{len(results)} tests réussis")

    if passed == len(results):
        print("🎉 Tous les tests sont passés ! L'intégration est prête.")
        print("\n📋 PROCHAINES ÉTAPES:")
        print("1. Testez la page /payment/upgrade")
        print("2. Configurez vos vraies clés EasyTransfert")
        print("3. Testez un paiement réel avec un petit montant")
        return True
    else:
        print("⚠️  Certains tests ont échoué. Vérifiez votre configuration.")
        print("\n🔧 ACTIONS RECOMMANDÉES:")

        failed_tests = [name for name, result in results if not result]
        for failed_test in failed_tests:
            if "environnement" in failed_test.lower():
                print("   • Ajoutez les variables manquantes dans l'onglet Secrets de Replit")
            elif "base de données" in failed_test.lower():
                print("   • Exécutez python init_plans.py pour créer les plans")
            elif "utilisateur" in failed_test.lower():
                print("   • Créez un utilisateur web via /register")
            else:
                print(f"   • Vérifiez la configuration pour: {failed_test}")

        return False

if __name__ == '__main__':
    try:
        success = run_all_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        sys.exit(1)