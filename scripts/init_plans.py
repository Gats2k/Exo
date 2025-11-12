import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import Plan
import json

def init_plans():
    """Initialise les plans de base dans la base de données"""

    plans_data = [
        {
            'name': 'gratuit',
            'display_name': 'Plan Gratuit',
            'price': 0,
            'duration_days': 30,
            'daily_message_limit': 50,
            'features': json.dumps({
                'messages_per_day': 50,
                'basic_ai': True,
                'image_analysis': False,
                'priority_support': False,
                'advanced_features': False
            })
        },
        {
            'name': 'premium',
            'display_name': 'Plan Premium',
            'price': 1500,
            'duration_days': 30,
            'daily_message_limit': 500,
            'features': json.dumps({
                'messages_per_day': 500,
                'basic_ai': True,
                'image_analysis': True,
                'priority_support': False,
                'advanced_features': True
            })
        },
        {
            'name': 'pro',
            'display_name': 'Plan Pro',
            'price': 5000,
            'duration_days': 30,
            'daily_message_limit': None,  # Illimité
            'features': json.dumps({
                'messages_per_day': 'unlimited',
                'basic_ai': True,
                'image_analysis': True,
                'priority_support': True,
                'advanced_features': True,
                'custom_integrations': True
            })
        }
    ]

    with app.app_context():
        # Vérifier si les plans existent déjà
        existing_plans = Plan.query.count()
        if existing_plans > 0:
            print(f"❌ {existing_plans} plan(s) déjà existant(s). Suppression et recréation...")
            Plan.query.delete()
            db.session.commit()

        # Créer les nouveaux plans
        for plan_data in plans_data:
            plan = Plan(**plan_data)
            db.session.add(plan)
            print(f"✅ Plan '{plan_data['display_name']}' ajouté - {plan_data['price']} FCFA/mois")

        try:
            db.session.commit()
            print(f"🎉 {len(plans_data)} plans initialisés avec succès!")

            # Afficher un résumé
            print("\n📋 RÉSUMÉ DES PLANS :")
            plans = Plan.query.all()
            for plan in plans:
                limit = f"{plan.daily_message_limit} msg/jour" if plan.daily_message_limit else "Illimité"
                print(f"  • {plan.display_name}: {plan.price} FCFA - {limit}")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Erreur lors de l'initialisation: {e}")
            return False

    return True

if __name__ == '__main__':
    print("🚀 Initialisation des plans de paiement...")
    success = init_plans()
    if success:
        print("✅ Initialisation terminée avec succès!")
    else:
        print("❌ Échec de l'initialisation")
        sys.exit(1)