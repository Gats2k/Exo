"""
Handler pour les enregistrements audio et leur traitement
Intègre la transcription Groq et l'amélioration par l'IA d'Exô
"""
from flask import request, jsonify
from flask_login import login_required, current_user
from flask_socketio import emit
import logging
from audio_utils import (
    transcribe_audio_groq, 
    save_uploaded_audio, 
    cleanup_audio_file,
    is_audio_service_available
)
from ai_config import get_ai_client, CURRENT_MODEL, get_system_instructions
from ai_utils import execute_chat_completion
from database import db
from models import Conversation, Message
from datetime import datetime
import json

logger = logging.getLogger(__name__)


def improve_course_transcript(transcript: str) -> dict:
    """
    Améliore un transcript de cours avec l'IA d'Exô
    
    Args:
        transcript: Texte transcrit du cours vocal
    
    Returns:
        dict: {
            'success': bool,
            'improved_text': str (si succès),
            'error': str (si échec)
        }
    """
    try:
        logger.info("🤖 Amélioration du transcript avec l'IA d'Exô...")
        
        # Créer le prompt pour améliorer le cours
        improvement_prompt = f"""
Tu as reçu l'enregistrement vocal d'un cours. Voici le texte transcrit :

---
{transcript}
---

Ta tâche est de transformer ce transcript en un cours bien structuré et facile à comprendre. 
Voici ce que tu dois faire :

1. **Corriger les erreurs** : Corrige les fautes de transcription, les répétitions, et les hésitations
2. **Structurer le contenu** : Organise les idées en sections claires avec des titres
3. **Enrichir les explications** : Ajoute des détails, des exemples concrets, et des analogies pour faciliter la compréhension
4. **Clarifier les concepts** : Explique les termes techniques de manière simple
5. **Ajouter de la valeur** : Complète avec des informations complémentaires pertinentes si nécessaire

**Important** : 
- Reste fidèle au contenu original du cours
- Utilise un ton pédagogique et encourageant
- Utilise des emojis pour rendre le contenu plus engageant 📚✨
- Formate bien le texte avec des sauts de ligne et des titres clairs

Commence directement par le cours amélioré sans introduction comme "Voici le cours amélioré...".
"""
        
        # Préparer l'historique de messages pour l'IA
        messages_history = [
            {"role": "user", "content": improvement_prompt}
        ]
        
        # Obtenir la réponse de l'IA avec execute_chat_completion
        improved_text = execute_chat_completion(
            messages_history=messages_history,
            current_model=CURRENT_MODEL,
            stream=False,
            add_system_instructions=True
        )
        
        if improved_text:
            improved_text = improved_text.strip()
            logger.info(f"✅ Cours amélioré avec succès: {len(improved_text)} caractères")
            
            return {
                'success': True,
                'improved_text': improved_text
            }
        else:
            logger.error(f"❌ Erreur lors de l'amélioration: Réponse vide")
            return {
                'success': False,
                'error': 'Réponse IA vide'
            }
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'amélioration du transcript: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


@login_required
def handle_audio_upload():
    """
    Route Flask pour gérer l'upload d'un fichier audio
    
    Returns:
        JSON response avec le texte transcrit et amélioré
    """
    try:
        # Vérifier que le service est disponible
        if not is_audio_service_available():
            return jsonify({
                'success': False,
                'error': 'Service de transcription audio non disponible'
            }), 503
        
        # Vérifier qu'un fichier audio a été envoyé
        if 'audio' not in request.files:
            return jsonify({
                'success': False,
                'error': 'Aucun fichier audio trouvé'
            }), 400
        
        audio_file = request.files['audio']
        
        if audio_file.filename == '':
            return jsonify({
                'success': False,
                'error': 'Nom de fichier vide'
            }), 400
        
        logger.info(f"🎙️ Réception d'un fichier audio: {audio_file.filename}")
        
        # Sauvegarder le fichier audio temporairement
        temp_audio_path = save_uploaded_audio(audio_file, audio_file.filename)
        
        try:
            # Étape 1: Transcrire l'audio avec Groq Whisper
            logger.info("📝 Transcription en cours...")
            transcription_result = transcribe_audio_groq(temp_audio_path, language="fr")
            
            if not transcription_result.get('success'):
                return jsonify({
                    'success': False,
                    'error': transcription_result.get('error', 'Erreur de transcription')
                }), 500
            
            transcript = transcription_result.get('text', '')
            
            # Étape 2: Améliorer le transcript avec l'IA d'Exô
            logger.info("✨ Amélioration du cours en cours...")
            improvement_result = improve_course_transcript(transcript)
            
            if not improvement_result.get('success'):
                # En cas d'échec de l'amélioration, retourner quand même le transcript brut
                logger.warning("⚠️ Amélioration échouée, retour du transcript brut")
                return jsonify({
                    'success': True,
                    'transcript': transcript,
                    'improved_text': transcript,
                    'improvement_failed': True,
                    'warning': 'Le cours n\'a pas pu être amélioré, voici le texte transcrit brut'
                })
            
            improved_text = improvement_result.get('improved_text', transcript)
            
            logger.info("🎉 Traitement audio terminé avec succès")
            
            return jsonify({
                'success': True,
                'transcript': transcript,
                'improved_text': improved_text,
                'duration': transcription_result.get('duration'),
                'language': transcription_result.get('language', 'fr')
            })
        
        finally:
            # Nettoyer le fichier temporaire
            cleanup_audio_file(temp_audio_path)
    
    except Exception as e:
        logger.error(f"❌ Erreur lors du traitement audio: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erreur serveur: {str(e)}'
        }), 500


def handle_audio_socketio(data):
    """
    Handler Socket.IO pour l'enregistrement audio
    Permet le streaming en temps réel
    
    Args:
        data: Dictionnaire contenant les données audio
    """
    try:
        audio_data = data.get('audio_data')
        filename = data.get('filename', 'recording.webm')
        
        if not audio_data:
            emit('audio_error', {'error': 'Aucune donnée audio reçue'})
            return
        
        logger.info(f"🎙️ Réception audio via Socket.IO: {filename}")
        
        # Décoder les données audio (base64 si nécessaire)
        import base64
        if isinstance(audio_data, str):
            audio_bytes = base64.b64decode(audio_data)
        else:
            audio_bytes = audio_data
        
        # Sauvegarder temporairement
        temp_audio_path = save_uploaded_audio(audio_bytes, filename)
        
        try:
            # Émettre un événement de début de traitement
            emit('audio_processing', {'status': 'transcription'})
            
            # Transcrire
            transcription_result = transcribe_audio_groq(temp_audio_path, language="fr")
            
            if not transcription_result.get('success'):
                emit('audio_error', {
                    'error': transcription_result.get('error', 'Erreur de transcription')
                })
                return
            
            transcript = transcription_result.get('text', '')
            
            # Émettre le transcript
            emit('audio_transcribed', {'transcript': transcript})
            
            # Améliorer avec l'IA
            emit('audio_processing', {'status': 'improvement'})
            
            improvement_result = improve_course_transcript(transcript)
            
            if improvement_result.get('success'):
                improved_text = improvement_result.get('improved_text', transcript)
                emit('audio_completed', {
                    'transcript': transcript,
                    'improved_text': improved_text,
                    'duration': transcription_result.get('duration')
                })
            else:
                # Retourner le transcript brut en cas d'échec
                emit('audio_completed', {
                    'transcript': transcript,
                    'improved_text': transcript,
                    'warning': 'Amélioration échouée'
                })
        
        finally:
            cleanup_audio_file(temp_audio_path)
    
    except Exception as e:
        logger.error(f"❌ Erreur Socket.IO audio: {str(e)}")
        emit('audio_error', {'error': str(e)})


def save_lesson_from_audio(audio_file, subject: str, user_id: int) -> dict:
    """
    Traite un enregistrement audio de cours et le sauvegarde en base de données
    
    Args:
        audio_file: Fichier audio uploadé (Flask request.files)
        subject: Matière (Mathématiques, Physique, Chimie, SVT)
        user_id: ID de l'utilisateur
    
    Returns:
        dict: {
            'success': bool,
            'lesson_id': int (si succès),
            'transcript': str (si succès),
            'improved_text': str (si succès),
            'error': str (si échec)
        }
    """
    from models import Lesson
    
    temp_audio_path = None
    
    try:
        logger.info(f"🎓 Début du traitement de leçon pour {subject} (user_id={user_id})")
        
        # Vérifier que le service est disponible
        if not is_audio_service_available():
            return {
                'success': False,
                'error': 'Service de transcription audio non disponible'
            }
        
        # Sauvegarder le fichier audio temporairement
        temp_audio_path = save_uploaded_audio(audio_file, audio_file.filename)
        logger.info(f"💾 Audio sauvegardé temporairement: {temp_audio_path}")
        
        # Créer l'enregistrement en BD avec status 'processing'
        lesson = Lesson(
            user_id=user_id,
            subject=subject,
            audio_filename=audio_file.filename,
            status='processing'
        )
        db.session.add(lesson)
        db.session.commit()
        lesson_id = lesson.id
        logger.info(f"📝 Leçon créée en BD: ID={lesson_id}")
        
        try:
            # Étape 1: Transcrire l'audio avec Groq Whisper
            logger.info("🔍 Transcription en cours...")
            transcription_result = transcribe_audio_groq(temp_audio_path, language="fr")
            
            if not transcription_result.get('success'):
                error_msg = transcription_result.get('error', 'Erreur de transcription')
                lesson.status = 'failed'
                lesson.error_message = error_msg
                db.session.commit()
                
                return {
                    'success': False,
                    'error': error_msg,
                    'lesson_id': lesson_id
                }
            
            transcript = transcription_result.get('text', '')
            duration = transcription_result.get('duration')
            language = transcription_result.get('language', 'fr')
            
            logger.info(f"✅ Transcription réussie: {len(transcript)} caractères")
            
            # Mettre à jour la leçon avec la transcription
            lesson.original_transcript = transcript
            lesson.duration_seconds = duration
            lesson.language = language
            db.session.commit()
            
            # Étape 2: Améliorer le transcript avec l'IA d'Exô
            logger.info("✨ Amélioration du cours en cours...")
            improvement_result = improve_course_transcript(transcript)
            
            if improvement_result.get('success'):
                improved_text = improvement_result.get('improved_text', transcript)
                lesson.improved_transcript = improved_text
                lesson.status = 'completed'
                logger.info(f"🎉 Leçon améliorée avec succès: {len(improved_text)} caractères")
            else:
                # En cas d'échec de l'amélioration, on garde le transcript brut
                logger.warning("⚠️ Amélioration échouée, conservation du transcript brut")
                lesson.improved_transcript = transcript
                lesson.status = 'completed'
                improved_text = transcript
            
            db.session.commit()
            
            logger.info(f"✅ Leçon {lesson_id} sauvegardée avec succès")
            
            return {
                'success': True,
                'lesson_id': lesson_id,
                'transcript': transcript,
                'improved_text': improved_text,
                'duration': duration,
                'language': language
            }
        
        except Exception as e:
            # Marquer la leçon comme échouée
            lesson.status = 'failed'
            lesson.error_message = str(e)
            db.session.commit()
            raise
    
    except Exception as e:
        logger.error(f"❌ Erreur lors du traitement de la leçon: {str(e)}")
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }
    
    finally:
        # Nettoyer le fichier temporaire
        if temp_audio_path:
            cleanup_audio_file(temp_audio_path)
            logger.info("🧹 Fichier temporaire nettoyé")
