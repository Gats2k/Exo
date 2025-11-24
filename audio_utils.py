"""
Module pour la transcription audio avec Groq Whisper
Gère l'enregistrement de cours vocaux et leur transcription
"""
import os
import logging
import tempfile
from groq import Groq

# Charger le fichier .env si disponible
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv pas installé, pas grave si les variables sont déjà dans l'environnement

logger = logging.getLogger(__name__)

# Configuration Groq
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# Initialiser le client Groq si la clé API est disponible
groq_client = None
if GROQ_API_KEY:
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        logger.info("✅ Client Groq initialisé avec succès")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'initialisation du client Groq: {str(e)}")
else:
    logger.warning("⚠️ GROQ_API_KEY non définie - transcription audio désactivée")


def transcribe_audio_groq(audio_file_path: str, language: str = "fr") -> dict:
    """
    Transcrit un fichier audio en utilisant Groq Whisper
    
    Args:
        audio_file_path: Chemin vers le fichier audio
        language: Code de langue (par défaut "fr" pour français)
    
    Returns:
        dict: {
            'success': bool,
            'text': str (si succès),
            'error': str (si échec)
        }
    """
    if not groq_client:
        logger.error("Client Groq non disponible")
        return {
            'success': False,
            'error': 'Service de transcription non configuré'
        }
    
    try:
        logger.info(f"🎙️ Début de la transcription avec Groq Whisper: {audio_file_path}")
        
        # Vérifier que le fichier existe
        if not os.path.exists(audio_file_path):
            logger.error(f"Fichier audio introuvable: {audio_file_path}")
            return {
                'success': False,
                'error': 'Fichier audio introuvable'
            }
        
        # Vérifier la taille du fichier (limite Groq: 25 MB)
        file_size = os.path.getsize(audio_file_path)
        if file_size > 25 * 1024 * 1024:  # 25 MB
            logger.error(f"Fichier audio trop volumineux: {file_size} bytes")
            return {
                'success': False,
                'error': 'Fichier audio trop volumineux (max 25MB)'
            }
        
        # Ouvrir et transcrire le fichier audio
        with open(audio_file_path, "rb") as audio_file:
            # Utiliser le modèle Whisper de Groq
            transcription = groq_client.audio.transcriptions.create(
                file=(os.path.basename(audio_file_path), audio_file.read()),
                model="whisper-large-v3-turbo",  # Modèle Whisper optimisé
                language=language,
                response_format="verbose_json",  # Pour obtenir plus de détails
                temperature=0.0  # Pour une transcription déterministe
            )
        
        # Extraire le texte transcrit
        transcribed_text = transcription.text.strip()
        
        if not transcribed_text:
            logger.warning("Transcription vide")
            return {
                'success': False,
                'error': 'Aucun texte détecté dans l\'audio'
            }
        
        logger.info(f"✅ Transcription réussie: {len(transcribed_text)} caractères")
        logger.debug(f"Texte transcrit: {transcribed_text[:100]}...")
        
        return {
            'success': True,
            'text': transcribed_text,
            'duration': getattr(transcription, 'duration', None),
            'language': language
        }
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la transcription: {str(e)}")
        return {
            'success': False,
            'error': f'Erreur de transcription: {str(e)}'
        }


def save_uploaded_audio(audio_data, filename: str = None) -> str:
    """
    Sauvegarde un fichier audio uploadé dans un fichier temporaire
    
    Args:
        audio_data: Données audio (bytes ou objet file)
        filename: Nom du fichier (optionnel)
    
    Returns:
        str: Chemin vers le fichier temporaire
    """
    try:
        # Créer un fichier temporaire
        suffix = os.path.splitext(filename)[1] if filename else '.webm'
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        
        # Écrire les données audio
        if hasattr(audio_data, 'read'):
            temp_file.write(audio_data.read())
        else:
            temp_file.write(audio_data)
        
        temp_file.close()
        logger.info(f"📁 Fichier audio sauvegardé: {temp_file.name}")
        
        return temp_file.name
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la sauvegarde de l'audio: {str(e)}")
        raise


def cleanup_audio_file(file_path: str):
    """
    Nettoie un fichier audio temporaire
    
    Args:
        file_path: Chemin vers le fichier à supprimer
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"🗑️ Fichier audio supprimé: {file_path}")
    except Exception as e:
        logger.warning(f"⚠️ Erreur lors de la suppression du fichier audio: {str(e)}")


def is_audio_service_available() -> bool:
    """
    Vérifie si le service de transcription audio est disponible
    
    Returns:
        bool: True si le service est disponible
    """
    return groq_client is not None
