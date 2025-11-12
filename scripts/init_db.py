from flask import Flask
from database import db
from models import User, Conversation, Message, TelegramUser, TelegramConversation, TelegramMessage, Subscription, MessageFeedback
import os

app = Flask(__name__)

# Utiliser la même configuration que dans app.py
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Créer les tables
with app.app_context():
    db.create_all()
    print("Base de données PostgreSQL initialisée avec succès !")