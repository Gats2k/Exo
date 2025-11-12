import os
from datetime import timedelta

class Config:
    """Configuration centrale de l'application Flask"""

    # Upload settings
    UPLOAD_FOLDER = 'static/uploads'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    MAX_UPLOAD_FOLDER_SIZE = 500 * 1024 * 1024  # 500 MB
    IMAGE_MAX_AGE_HOURS = 24

    # Flask settings
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_PERMANENT = True

    # Database settings
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 5,
        'max_overflow': 10,
        'pool_recycle': 300,
        'pool_timeout': 30,
        'pool_pre_ping': True,
    }

    @staticmethod
    def allowed_file(filename):
        """Check if file extension is allowed"""
        return '.' in filename and \
               filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS