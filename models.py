from datetime import datetime
from app import db

class Thread(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assistant_thread_id = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship('Message', backref='thread', lazy=True)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(50), nullable=False)  # 'user' or 'assistant'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    thread_id = db.Column(db.Integer, db.ForeignKey('thread.id'), nullable=False)
