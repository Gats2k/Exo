import os
from dotenv import load_dotenv

def check_environment():
    """Vérifie la configuration de l'environnement Replit"""
    print("🔍 VÉRIFICATION DE LA CONFIGURATION ENVIRONNEMENT (REPLIT)")
    print("=" * 60)

    # Sur Replit, pas besoin de load_dotenv() car les Secrets sont automatiquement chargés
    print("📍 Variables chargées depuis l'onglet Secrets de Replit")

    # Variables requises pour le système de paiement
    required_vars = {
        'EASYTRANSFERT_API_KEY': 'Clé API EasyTransfert',
        'IPN_BASE_URL': 'URL de callback pour EasyTransfert'
    }

    # Variables optionnelles mais importantes
    optional_vars = {
        'FLASK_SECRET_KEY': 'Clé secrète Flask',
        'DATABASE_URL': 'URL de la base de données',
        'OPENAI_API_KEY': 'Clé API OpenAI'
    }

    errors = []
    warnings = []

    print("📋 Variables REQUISES pour le paiement:")
    for var, description in required_vars.items():
        value = os.getenv(var)
        if value:
            if var == 'IPN_BASE_URL':
                if not value.startswith('https://'):
                    errors.append(f"{var} doit commencer par https://")
                    print(f"   ❌ {var}: {description} - ERREUR: doit commencer par https://")
                elif value == 'https://votre-nom-projet.votre-username.repl.co':
                    warnings.append(f"{var} contient encore l'exemple par défaut")
                    print(f"   ⚠️  {var}: {description} - ATTENTION: Remplacez par votre vraie URL Replit")
                else:
                    print(f"   ✅ {var}: {description} - Configurée")
            elif var == 'EASYTRANSFERT_API_KEY':
                if value == 'votre_cle_api_easytransfert_ici':
                    errors.append(f"{var} contient encore l'exemple par défaut")
                    print(f"   ❌ {var}: {description} - ERREUR: Remplacez par votre vraie clé API")
                else:
                    print(f"   ✅ {var}: {description} - Configurée")
            else:
                print(f"   ✅ {var}: {description} - Configurée")
        else:
            errors.append(f"{var} manquante")
            print(f"   ❌ {var}: {description} - MANQUANTE")

    print(f"\n📋 Variables OPTIONNELLES:")
    for var, description in optional_vars.items():
        value = os.getenv(var)
        if value:
            print(f"   ✅ {var}: {description} - Configurée")
        else:
            warnings.append(f"{var} manquante")
            print(f"   ⚠️  {var}: {description} - Manquante")

    print(f"\n{'='*60}")
    print("📊 RÉSUMÉ")
    print(f"{'='*60}")

    if errors:
        print(f"❌ ERREURS ({len(errors)}):")
        for error in errors:
            print(f"   • {error}")

    if warnings:
        print(f"⚠️  AVERTISSEMENTS ({len(warnings)}):")
        for warning in warnings:
            print(f"   • {warning}")

    if not errors and not warnings:
        print("🎉 Configuration parfaite ! Toutes les variables sont correctement configurées.")
        return True
    elif not errors:
        print("✅ Configuration fonctionnelle avec quelques avertissements.")
        return True
    else:
        print("❌ Configuration incorrecte. Corrigez les erreurs avant de continuer.")
        return False

if __name__ == '__main__':
    success = check_environment()
    exit(0 if success else 1)