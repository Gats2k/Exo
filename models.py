from datetime import datetime
from database import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(64), nullable=False)
    last_name = db.Column(db.String(64), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(256))
    study_level = db.Column(db.String(20), nullable=False)  # Terminal A, D, or C
    grade_goals = db.Column(db.String(50), nullable=False)  # Different grade ranges
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def is_admin_credentials(phone_number, password):
        return phone_number == "Hokage" and password == "09791308n"

class Conversation(db.Model):
    __tablename__ = 'conversation'
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.String(255), nullable=False, unique=True)
    title = db.Column(db.String(255))
    deleted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    messages = db.relationship('Message', backref='conversation', lazy=True, cascade='all, delete-orphan')

class Message(db.Model):
    __tablename__ = 'message'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(512))  # Optional, for messages with images
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Telegram-specific models
class TelegramUser(db.Model):
    __tablename__ = 'telegram_user'
    telegram_id = db.Column(db.BigInteger, primary_key=True)  # Telegram user IDs are large numbers
    first_name = db.Column(db.String(64), default="---")
    phone_number = db.Column(db.String(20), default="---")
    study_level = db.Column(db.String(20), default="---")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    conversations = db.relationship('TelegramConversation', backref='user', lazy=True)

class TelegramConversation(db.Model):
    __tablename__ = 'telegram_conversation'
    id = db.Column(db.Integer, primary_key=True)
    telegram_user_id = db.Column(db.BigInteger, db.ForeignKey('telegram_user.telegram_id'), nullable=False)
    thread_id = db.Column(db.String(255), nullable=False, unique=True)
    title = db.Column(db.String(255), default="Nouvelle conversation")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    messages = db.relationship('TelegramMessage', backref='conversation', lazy=True, cascade='all, delete-orphan')

class TelegramMessage(db.Model):
    __tablename__ = 'telegram_message'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('telegram_conversation.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(512))  # Optional, for messages with images
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# WhatsApp-specific models
class WhatsAppUser(db.Model):
    __tablename__ = 'whatsapp_user'
    phone_number = db.Column(db.String(20), primary_key=True)  # WhatsApp users are identified by phone numbers
    name = db.Column(db.String(64), default="---")
    study_level = db.Column(db.String(20), default="---")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    conversations = db.relationship('WhatsAppConversation', backref='user', lazy=True)

class WhatsAppConversation(db.Model):
    __tablename__ = 'whatsapp_conversation'
    id = db.Column(db.Integer, primary_key=True)
    whatsapp_user_phone = db.Column(db.String(20), db.ForeignKey('whatsapp_user.phone_number'), nullable=False)
    thread_id = db.Column(db.String(255), nullable=False, unique=True)
    title = db.Column(db.String(255), default="Nouvelle conversation")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    messages = db.relationship('WhatsAppMessage', backref='conversation', lazy=True, cascade='all, delete-orphan')

class WhatsAppMessage(db.Model):
    __tablename__ = 'whatsapp_message'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('whatsapp_conversation.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(512))  # Optional, for messages with images
    created_at = db.Column(db.DateTime, default=datetime.utcnow)