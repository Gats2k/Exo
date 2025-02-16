from datetime import datetime
from database import db

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.String(255), nullable=False, unique=True)
    title = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    messages = db.relationship('Message', backref='conversation', lazy=True, cascade='all, delete-orphan')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(512))  # Optional, for messages with images
    created_at = db.Column(db.DateTime, default=datetime.utcnow)