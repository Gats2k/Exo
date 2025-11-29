from datetime import datetime
from database import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Index, desc
from datetime import date
import json

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(64), nullable=False)
    last_name = db.Column(db.String(64), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    phone_number = db.Column(db.String(50), nullable=False)
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

    # DÃ©finir TOUTES les colonnes, y compris la clÃ© primaire 'id'
    id = db.Column(db.Integer, primary_key=True) # <-- CLÃ‰ PRIMAIRE DÃ‰FINIE
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subscription_type = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    expiry_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False) # Ajouter index=True si on filtre souvent
    last_payment_date = db.Column(db.DateTime, nullable=True) # nullable=True car peut Ãªtre vide

    # Nouvelles colonnes pour le système de paiement
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=True)
    auto_renewal = db.Column(db.Boolean, default=False)

    # Relationship with User model
    user = db.relationship('User', backref=db.backref('subscriptions', lazy=True))
    # Nouvelles relations
    plan = db.relationship('Plan', backref=db.backref('subscriptions', lazy=True))
    transaction = db.relationship('Transaction', backref=db.backref('subscription', uselist=False))

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

class Plan(db.Model):
    """Table des plans d'abonnement disponibles"""
    __tablename__ = 'plan'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)  # 'gratuit', 'premium', 'pro'
    display_name = db.Column(db.String(100), nullable=False)  # 'Plan Gratuit', 'Plan Premium', etc.
    price = db.Column(db.Integer, nullable=False)  # Prix en FCFA (0 pour gratuit)
    duration_days = db.Column(db.Integer, nullable=False)  # Durée en jours (30 pour mensuel)
    daily_message_limit = db.Column(db.Integer, nullable=True)  # Limite messages/jour (None = illimité)
    features = db.Column(db.Text)  # JSON des fonctionnalités
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Index pour les requêtes fréquentes
    __table_args__ = (
        db.Index('ix_plan_is_active', 'is_active'),
    )


class Transaction(db.Model):
    """Table des transactions EasyTransfert"""
    __tablename__ = 'transaction'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)

    # Identifiants EasyTransfert
    easytransfert_transaction_id = db.Column(db.String(100), unique=True)  # ID retourné par EasyTransfert

    # Détails de la transaction
    amount = db.Column(db.Integer, nullable=False)  # Montant en FCFA
    phone_number = db.Column(db.String(20), nullable=False)  # Numéro de paiement
    operator = db.Column(db.String(20), nullable=False)  # 'orange', 'mtn', 'moov', 'wave'
    service_id = db.Column(db.Integer, nullable=False)  # ID service EasyTransfert

    # Statuts
    status = db.Column(db.String(20), nullable=False, default='pending')  # 'pending', 'success', 'failed'
    payment_method = db.Column(db.String(50))  # Détails du moyen de paiement

    # Métadonnées
    custom_data = db.Column(db.Text)  # Données personnalisées
    error_message = db.Column(db.Text)  # Message d'erreur si échec

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)  # Quand la transaction est finalisée

    # Relations
    user = db.relationship('User', backref=db.backref('transactions', lazy=True))
    plan = db.relationship('Plan', backref=db.backref('transactions', lazy=True))

    # Index pour les requêtes fréquentes
    __table_args__ = (
        db.Index('ix_transaction_status', 'status'),
        db.Index('ix_transaction_created_at', desc(created_at)),
        db.Index('ix_transaction_user_id_status', 'user_id', 'status'),
    )


class UserUsage(db.Model):
    """Table pour tracker l'utilisation quotidienne des utilisateurs"""
    __tablename__ = 'user_usage'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    date = db.Column(db.Date, nullable=False)  # Date du jour
    message_count = db.Column(db.Integer, default=0)  # Nombre de messages envoyés ce jour
    warning_messages_sent = db.Column(db.Integer, default=0)  # Nombre de messages d'avertissement envoyés
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    user = db.relationship('User', backref=db.backref('usage_records', lazy=True))

    # Index et contrainte unique
    __table_args__ = (
        db.Index('ix_user_usage_user_date', 'user_id', 'date'),
        db.UniqueConstraint('user_id', 'date', name='unique_user_date'),
    )

class UserMemory(db.Model):
    """Table pour stocker la mémoire personnalisée de chaque utilisateur"""
    __tablename__ = 'user_memory'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False, index=True)

    # Profil Éducatif
    nom = db.Column(db.String(150))  # Augmenté pour sécurité
    niveau = db.Column(db.String(100))  # "Terminale D", "1ère C", etc.
    matieres_difficiles = db.Column(db.JSON)  # ["Physique", "Chimie"]
    matieres_preferees = db.Column(db.JSON)  # ["Mathématiques"]
    mode_prefere = db.Column(db.String(50), default='Détaillé')  # "Détaillé" ou "Rapide"

    # Tracking d'Activité
    derniere_interaction = db.Column(db.Date)
    nb_interactions = db.Column(db.Integer, default=0)
    derniers_sujets = db.Column(db.JSON)  # [{"date": "2025-10-05", "matiere": "Physique", "sujet": "Circuit RLC"}]
    streak_jours = db.Column(db.Integer, default=0)

    # Feedback
    feedback_positif_count = db.Column(db.Integer, default=0)
    feedback_negatif_count = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    # Relation
    user = db.relationship('User', backref=db.backref('memory', uselist=False))


class ConsolidatedConversation(db.Model):
    """Table pour tracer les conversations déjà consolidées (évite les doublons)"""
    __tablename__ = 'consolidated_conversation'

    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(20), nullable=False, index=True)  # 'web', 'telegram', 'whatsapp'
    conversation_id = db.Column(db.String(255), nullable=False, index=True)  # Compatible thread_id WhatsApp
    consolidated_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Index pour éviter la consolidation en double
    __table_args__ = (
        db.Index('ix_consolidated_conv_platform_id', 'platform', 'conversation_id'),
    )

class WhatsAppMessage(db.Model):
     __tablename__ = 'whatsapp_messages'

     id = db.Column(db.Integer, primary_key=True)
     message_id = db.Column(db.String(128), unique=True, nullable=True)
     from_number = db.Column(db.String(20), nullable=True)
     to_number = db.Column(db.String(20), nullable=True)
     content = db.Column(db.Text, nullable=True)
     timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
     status = db.Column(db.String(20), nullable=True)
     direction = db.Column(db.String(10), nullable=True)
     thread_id = db.Column(db.String(128), nullable=True)

     __table_args__ = (
         db.Index('ix_whatsapp_message_from_number_timestamp', 'from_number', 'timestamp'),
         db.Index('ix_whatsapp_message_thread_id_timestamp', 'thread_id', desc('timestamp')),
     )

class ReminderLog(db.Model):
    """Table pour tracer l'envoi des rappels et éviter les doublons"""
    __tablename__ = 'reminder_log'

    id = db.Column(db.Integer, primary_key=True)
    user_identifier = db.Column(db.String(100), nullable=False, index=True)  # phone_number ou telegram_id
    platform = db.Column(db.String(20), nullable=False, index=True)  # 'whatsapp' ou 'telegram'
    reminder_type = db.Column(db.String(20), nullable=False)  # 'night', 'morning', 'evening'

    # Timestamps
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    scheduled_for = db.Column(db.DateTime, nullable=False)  # Heure prévue (ex: 22h30)

    # Métadonnées
    message_content = db.Column(db.Text)  # Message envoyé
    user_last_active = db.Column(db.DateTime)  # Dernière activité de l'utilisateur au moment de l'envoi
    hours_since_active = db.Column(db.Float)  # Heures depuis dernière activité

    # Résultat
    status = db.Column(db.String(20), default='sent')  # 'sent', 'failed', 'skipped'
    error_message = db.Column(db.Text)  # Si erreur

    # Index pour requêtes fréquentes
    __table_args__ = (
        db.Index('ix_reminder_log_user_platform', 'user_identifier', 'platform'),
        db.Index('ix_reminder_log_sent_at', desc(sent_at)),
        db.Index('ix_reminder_log_status', 'status'),
    )

class Lesson(db.Model):
    """Table pour stocker les leçons enregistrées via audio par matière"""
    __tablename__ = 'lesson'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    subject = db.Column(db.String(50), nullable=False)  # Mathématiques, Physique, Chimie, SVT
    
    # Audio
    audio_filename = db.Column(db.String(255))  # Nom du fichier audio
    audio_url = db.Column(db.String(512))  # URL si stocké en ligne
    
    # Transcription
    original_transcript = db.Column(db.Text)  # Transcription brute de Groq Whisper
    improved_transcript = db.Column(db.Text)  # Transcription améliorée par l'IA
    
    # Images (captures de cours manuscrits)
    images = db.Column(db.JSON)  # Liste d'objets: [{"id": "...", "url": "...", "ocr_text": "...", "uploaded_at": "..."}]
    
    # Métadonnées
    duration_seconds = db.Column(db.Integer)  # Durée en secondes
    language = db.Column(db.String(10), default='fr')  # Langue détectée
    status = db.Column(db.String(20), default='processing')  # processing, completed, failed
    error_message = db.Column(db.Text)  # Message d'erreur si échec
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    user = db.relationship('User', backref=db.backref('lessons', lazy=True))
    
    # Index pour les requêtes fréquentes
    __table_args__ = (
        db.Index('ix_lesson_user_id_created_at', 'user_id', desc(created_at)),
        db.Index('ix_lesson_subject', 'subject'),
        db.Index('ix_lesson_status', 'status'),
    )
