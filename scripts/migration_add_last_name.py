from database import db
from app import app
import sqlalchemy as sa

def migrate():
    with app.app_context():
        # Vérifier si la colonne existe déjà pour éviter les erreurs
        inspector = sa.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('telegram_user')]

        if 'last_name' not in columns:
            # Ajouter la colonne
            db.session.execute(sa.text("ALTER TABLE telegram_user ADD COLUMN last_name VARCHAR(64) DEFAULT '---'"))
            db.session.commit()
            print("La colonne 'last_name' a été ajoutée à la table 'telegram_user'")
        else:
            print("La colonne 'last_name' existe déjà")

if __name__ == "__main__":
    migrate()