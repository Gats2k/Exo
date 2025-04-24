from datetime import datetime
from database import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Index, desc # <-- AJOUTER desc

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(64), nullable=False)
    last_name = db.Column(db.String(64), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(256))
    study_level = db.Column(db.String(20), nullable=False)
    grade_goals = db.Column(db.String(50), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # Sans index=True
    last_active = db.Column(db.DateTime, nullable=True) # Sans index=True mais on garde la colonne

    # Définir TOUS les index ici
    __table_args__ = (
        db.Index('ix_user_created_at', desc(created_at)), # Nom exact + ordre DESC
        db.Index('ix_user_last_active', last_active),     # Index pour la nouvelle colonne
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def is_admin_credentials(phone_number, password):
        from os import environ
        return phone_number == environ.get('ADMIN_PHONE') and password == environ.get('ADMIN_PASSWORD')

class Conversation(db.Model):
    __tablename__ = 'conversation'
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.String(255), nullable=False, unique=True) # unique=True crée déjà un index implicite
    title = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True) # FK crée souvent un index implicite
    deleted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # Sans index=True
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = db.Column(db.String(20), nullable=False, default='active') # Sans index=True mais on garde la colonne

    messages = db.relationship('Message', backref='conversation', lazy=True, cascade='all, delete-orphan')
    user = db.relationship('User', backref=db.backref('conversations', lazy=True))

    # Définir les index explicitement
    __table_args__ = (
        db.Index('ix_conversation_created_at', desc(created_at)), # Nom exact + ordre DESC
        db.Index('ix_conversation_status', status),             # Index pour la nouvelle colonne
        # Pas besoin de redéfinir l'index pour thread_id (unique=True) ou user_id (ForeignKey)
    )

class Message(db.Model):
    __tablename__ = 'message'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Index combiné explicite avec DESC
    __table_args__ = (
        db.Index('ix_message_conversation_id_created_at', "conversation_id", desc(created_at)), # Nom exact + ordre DESC
    )

class TelegramUser(db.Model):
    __tablename__ = 'telegram_user'
    telegram_id = db.Column(db.BigInteger, primary_key=True)
    first_name = db.Column(db.String(64), default="---")
    last_name = db.Column(db.String(64), default="---")
    phone_number = db.Column(db.String(20), default="---")
    study_level = db.Column(db.String(20), default="---")
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # Sans index=True
    last_active = db.Column(db.DateTime, nullable=True) # Sans index=True mais on garde la colonne

    conversations = db.relationship('TelegramConversation', backref='user', lazy=True)

    # Définir les index explicitement
    __table_args__ = (
        db.Index('ix_telegram_user_created_at', desc(created_at)), # Nom exact + ordre DESC
        db.Index('ix_telegram_user_last_active', last_active),     # Index pour la nouvelle colonne
    )


class TelegramConversation(db.Model):
    __tablename__ = 'telegram_conversation'
    id = db.Column(db.Integer, primary_key=True)
    telegram_user_id = db.Column(db.BigInteger, db.ForeignKey('telegram_user.telegram_id'), nullable=False) # FK crée index implicite
    thread_id = db.Column(db.String(255), nullable=False, unique=True) # unique=True crée index implicite
    title = db.Column(db.String(255), default="Nouvelle conversation")
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # Sans index=True
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = db.Column(db.String(20), nullable=False, default='active') # Sans index=True mais on garde la colonne

    messages = db.relationship('TelegramMessage', backref='conversation', lazy=True, cascade='all, delete-orphan')

     # Définir les index explicitement
    __table_args__ = (
        db.Index('ix_telegram_conversation_created_at', desc(created_at)), # Nom exact + ordre DESC
        db.Index('ix_telegram_conversation_status', status),             # Index pour la nouvelle colonne
    )


class TelegramMessage(db.Model):
    __tablename__ = 'telegram_message'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('telegram_conversation.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Index combiné explicite avec DESC
    __table_args__ = (
        db.Index('ix_telegram_message_conversation_id_created_at', "conversation_id", desc(created_at)), # Nom exact + ordre DESC
    )

# Dans models.py

class Subscription(db.Model):
    __tablename__ = 'subscription'

    # Définir TOUTES les colonnes, y compris la clé primaire 'id'
    id = db.Column(db.Integer, primary_key=True) # <-- CLÉ PRIMAIRE DÉFINIE
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subscription_type = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    expiry_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False) # Ajouter index=True si on filtre souvent
    last_payment_date = db.Column(db.DateTime, nullable=True) # nullable=True car peut être vide

    # Relationship with User model
    user = db.relationship('User', backref=db.backref('subscriptions', lazy=True))

class MessageFeedback(db.Model):
    __tablename__ = 'message_feedback'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True) # FK crée index implicite
    feedback_type = db.Column(db.String(10), nullable=False) # Sans index=True
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    message = db.relationship('Message', backref=db.backref('feedback', lazy=True))
    user = db.relationship('User', backref=db.backref('feedback', lazy=True))

    # Index explicite
    __table_args__ = (
        db.Index('ix_message_feedback_feedback_type', 'feedback_type'), # Nom exact
    )