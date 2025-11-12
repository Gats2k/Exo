import os
import sys

def quick_test():
    """Test rapide de l'intégration"""
    print("🔍 TEST RAPIDE DE L'INTÉGRATION")
    print("=" * 40)

    # Test 1: Imports
    try:
        from subscription_manager import SubscriptionManager, MessageLimitChecker
        from payment_routes import payment_bp
        print("✅ Imports réussis")
    except ImportError as e:
        print(f"❌ Erreur d'import: {e}")
        return False

    # Test 2: Variables d'environnement
    required_vars = ['EASYTRANSFERT_API_KEY', 'IPN_BASE_URL']
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print(f"❌ Variables manquantes: {', '.join(missing)}")
        return False
    else:
        print("✅ Variables d'environnement configurées")

    # Test 3: App Flask
    try:
        from app import app
        with app.app_context():
            print("✅ Contexte Flask fonctionnel")
    except Exception as e:
        print(f"❌ Erreur Flask: {e}")
        return False

    print("\n🎉 Test rapide réussi !")
    print("Lancez 'python test_payment_integration.py' pour les tests complets")
    return True

if __name__ == '__main__':
    success = quick_test()
    sys.exit(0 if success else 1)