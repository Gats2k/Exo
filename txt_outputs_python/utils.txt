import time
import logging
from contextlib import contextmanager
from sqlalchemy import exc
from database import db

logger = logging.getLogger(__name__)

import os
import uuid
import base64
from datetime import datetime, timedelta
from config import Config
import asyncio

def ensure_event_loop():
    """Vérifie qu'une boucle d'événements est disponible et active, ou en crée une nouvelle."""
    try:
        # Essayer d'obtenir la boucle actuelle
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            # Si la boucle est fermée, en créer une nouvelle et la définir comme boucle globale
            logger.warning("Boucle d'événements fermée, création d'une nouvelle boucle")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop
    except RuntimeError:
        # S'il n'y a pas de boucle, en créer une nouvelle et la définir comme boucle globale
        logger.warning("Pas de boucle d'événements, création d'une nouvelle boucle")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def get_db_context():
    """Get the Flask application context for database operations."""
    # Import local pour éviter la circularité
    from app import app
    return app.app_context()

def clean_response(text):
    """
    Nettoie le texte en supprimant les astérisques (*) et les dièses (#)

    Args:
        text (str): Le texte à nettoyer

    Returns:
        str: Le texte nettoyé
    """
    if not text:
        return text

    # Supprimer uniquement les astérisques et dièses
    cleaned_text = text.replace('*', '').replace('#', '').replace('```', '').replace('---', '')

    return cleaned_text

def save_base64_image(base64_string):
    """
    Sauvegarde une image encodée en base64 dans le dossier d'upload

    Args:
        base64_string (str): Image au format base64

    Returns:
        str: Nom du fichier sauvegardé
    """
    # Extract image type and data
    header, encoded = base64_string.split(",", 1)

    # Generate a unique filename
    filename = f"{uuid.uuid4()}.jpg"

    # Decode the image
    img_data = base64.b64decode(encoded)

    # Save the image
    filepath = os.path.join(Config.UPLOAD_FOLDER, filename)
    with open(filepath, "wb") as f:
        f.write(img_data)

    return filename

def cleanup_uploads():
    """Nettoie le dossier uploads des anciennes images et vérifie la taille totale"""
    try:
        upload_folder = Config.UPLOAD_FOLDER
        max_size = Config.MAX_UPLOAD_FOLDER_SIZE
        max_age_hours = Config.IMAGE_MAX_AGE_HOURS

        # Delete files older than IMAGE_MAX_AGE_HOURS
        current_time = datetime.now()
        for filename in os.listdir(upload_folder):
            filepath = os.path.join(upload_folder, filename)
            file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
            if current_time - file_modified > timedelta(hours=max_age_hours):
                os.remove(filepath)

        # Check the total size of the folder
        total_size = sum(
            os.path.getsize(os.path.join(upload_folder, f))
            for f in os.listdir(upload_folder))

        # If the size exceeds the limit, delete the oldest files
        if total_size > max_size:
            files = [(os.path.join(upload_folder, f),
                      os.path.getmtime(os.path.join(upload_folder, f)))
                     for f in os.listdir(upload_folder)]
            files.sort(key=lambda x: x[1])

            for filepath, _ in files:
                os.remove(filepath)
                total_size = sum(
                    os.path.getsize(os.path.join(upload_folder, f))
                    for f in os.listdir(upload_folder))
                if total_size <= max_size:
                    break

    except Exception as e:
        print(f"Error during upload cleanup: {str(e)}")

@contextmanager
def db_retry_session(max_retries=3, retry_delay=0.5):
    """Context manager for database operations with retry logic"""
    # Importation locale pour éviter les dépendances circulaires
    from app import app

    # Envelopper toute la logique dans le contexte de l'application Flask
    with app.app_context():
        try:
            for attempt in range(max_retries):
                try:
                    yield db.session
                    break
                except exc.OperationalError as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Database operation failed after {max_retries} attempts: {str(e)}", exc_info=True)
                        raise
                    logger.warning(f"Database connection failed, retrying... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Database error after {max_retries} attempts: {str(e)}", exc_info=True)
                        raise
                    logger.warning(f"Database operation failed, retrying... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
        except GeneratorExit:
            pass