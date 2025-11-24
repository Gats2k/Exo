import eventlet

eventlet.monkey_patch()

import os
from dotenv import load_dotenv
# Load environment variables before any other imports
load_dotenv()

from audio_handler import handle_audio_upload

from config import Config
from flask import Flask, render_template, request, jsonify, url_for, session, redirect, flash
from flask_socketio import SocketIO, emit
from openai import OpenAI
from werkzeug.utils import secure_filename
import base64
from io import BytesIO
from datetime import date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import exc
from flask import request, jsonify
from sqlalchemy import func, desc, or_
from datetime import datetime, timedelta
import shutil
import time
import logging
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
import uuid
from mathpix_utils import process_image_with_mathpix  # Added import
import json
from flask_migrate import Migrate
from telegram import Update
from telegram_bot import application as telegram_app
from telegram_bot import telegram_admin_bp
from payment_routes import payment_bp
from flask import request as flask_request
from flask import Response
import asyncio
from utils import ensure_event_loop, get_db_context
from telegram_bot import process_telegram_update
from admin_routes import admin_bp
from socket_handlers import (handle_rename, handle_delete,
                             handle_open_conversation, handle_clear_session,
                             handle_restore_session, handle_feedback,
                             handle_heartbeat)
from chat_services import handle_message_logic

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

app.config.from_object(Config)

# Provide a sensible default for local development when no DB URI is configured
if not app.config.get('SQLALCHEMY_DATABASE_URI'):
    # Prefer an on-disk SQLite DB for convenience
    default_sqlite = 'sqlite:///dev.sqlite3'
    app.config['SQLALCHEMY_DATABASE_URI'] = default_sqlite
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "No SQLALCHEMY_DATABASE_URI configured; falling back to '%s' for local development.",
        default_sqlite
    )

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize database
from database import db

# Import de la configuration IA centralisée
from ai_config import (get_ai_client, get_model_name, get_system_instructions,
                       reload_model_settings, CURRENT_MODEL, ASSISTANT_ID,
                       CONTEXT_MESSAGE_LIMIT, openai_client,
                       DEEPSEEK_INSTRUCTIONS, DEEPSEEK_REASONER_INSTRUCTIONS,
                       QWEN_INSTRUCTIONS, GEMINI_INSTRUCTIONS)

from utils import db_retry_session
from utils import db_retry_session, clean_response, save_base64_image, cleanup_uploads
from ai_utils import prepare_messages_for_api, upload_image_to_openai, process_image_for_openai, OpenAIAssistantEventHandler
from conversation_utils import conversation_is_valid, get_or_create_conversation
from auth_utils import phone_number_exists, get_or_create_web_user_for_telegram

db.init_app(app)
migrate = Migrate(app, db)

# Importer les modèles après l'initialisation de db
from models import User, Conversation, Message, TelegramUser, TelegramConversation, TelegramMessage, Subscription, MessageFeedback, Lesson

# Initialize SocketIO with eventlet
socketio = SocketIO(app,
                    async_mode='eventlet',
                    ping_timeout=60,
                    ping_interval=25,
                    cors_allowed_origins="*",
                    engineio_logger=False,
                    logger=False)

# Register SocketIO handlers
socketio.on_event('rename_conversation', handle_rename)
socketio.on_event('delete_conversation', handle_delete)
socketio.on_event('open_conversation', handle_open_conversation)
socketio.on_event('clear_session', handle_clear_session)
socketio.on_event('restore_session', handle_restore_session)
socketio.on_event('submit_feedback', handle_feedback)
socketio.on_event('heartbeat', handle_heartbeat)


# Register complex message handler with socketio passed as parameter
@socketio.on('send_message')
def handle_message(data):
    """Wrapper for handle_message_logic - passes socketio instance"""
    handle_message_logic(data, socketio)


# Assurer qu'un event loop existe pour le contexte async (important dans certains déploiements)
try:
    loop = asyncio.get_event_loop()
    logger.info(f"Event loop obtained: {loop}")
except RuntimeError:
    logger.info("No current event loop, creating a new one.")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

if telegram_app:  # Vérifier si l'import a réussi
    logger.info(
        "Initialisation de l'application Telegram (await application.initialize())..."
    )
    try:
        # Exécuter l'initialisation async dans la boucle d'événements existante
        # C'est important de le faire une fois au démarrage
        loop.run_until_complete(telegram_app.initialize())
        logger.info("Application Telegram initialisée avec succès.")
    except Exception as init_error:
        logger.error(
            f"Échec de l'initialisation de l'application Telegram: {init_error}",
            exc_info=True)
        # Gérer l'erreur critique si nécessaire
else:
    logger.error(
        "Impossible d'initialiser l'application Telegram car elle n'a pas été importée/créée."
    )


@app.route('/telegram_webhook', methods=['POST'])
def telegram_webhook_handler(
):  # Retiré 'async def' pour rendre la fonction synchrone
    logger.debug("Webhook Telegram reçu !")
    if not telegram_app:  # Vérifie si l'objet telegram_app existe (import réussi)
        logger.error("Objet application Telegram non importé/créé.")
        return Response(status=500)

    # Récupérer les données JSON
    if flask_request.content_type == 'application/json':
        json_data = flask_request.get_json(force=True)
        logger.debug(f"Payload JSON: {json_data}")

        # Utiliser eventlet.spawn pour traiter l'update dans un greenlet séparé
        eventlet.spawn(process_telegram_update, json_data)

        # Répondre immédiatement 200 OK à Telegram
        return Response(status=200)
    else:
        logger.warning(
            f"Requête Webhook reçue avec Content-Type incorrect: {flask_request.content_type}"
        )
        return Response(status=400)  # Bad Request


# Initialize LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# Ajout d'un teardown context pour s'assurer que les sessions DB sont fermées
@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()


# Import models after db initialization to avoid circular imports
from models import Conversation, Message, User, TelegramUser, TelegramConversation, TelegramMessage, Subscription, MessageFeedback
from whatsapp_bot import whatsapp
from models import WhatsAppMessage

# Create tables within application context
with app.app_context():
    db.create_all()

# Register the WhatsApp blueprint
app.register_blueprint(whatsapp, url_prefix='/whatsapp')

# Register the Telegram blueprint
app.register_blueprint(telegram_admin_bp)
app.register_blueprint(payment_bp)
app.register_blueprint(admin_bp)


# Contexte d'application pour les commandes flask
@app.cli.command("init-db")
def init_db():
    db.create_all()
    print("Base de données initialisée !")


@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))


@app.route('/api/audio/upload', methods=['POST'])
@login_required
def audio_upload():
    """Route pour uploader et traiter un fichier audio"""
    return handle_audio_upload()

@app.route('/privacy-policy')
def privacy_policy():
    """Privacy Policy page"""
    return render_template('privacy_policy.html')


@app.route('/')
@login_required
def chat():
    try:
        with db_retry_session() as db_session:

            conversation_history = []

            # Vérifier si l'utilisateur est connecté via Telegram ou WhatsApp
            is_telegram_user = session.get('is_telegram_user', False)
            telegram_id = session.get('telegram_id')
            is_whatsapp_user = session.get('is_whatsapp_user', False)
            whatsapp_number = session.get('whatsapp_number')

            # Vérifier si l'utilisateur actuel est réellement l'utilisateur Telegram indiqué
            if is_telegram_user and telegram_id and current_user.is_authenticated:
                if not current_user.phone_number.startswith(
                        f"telegram_{telegram_id}"):
                    # Les identifiants ne correspondent pas, nettoyer les données Telegram
                    session.pop('is_telegram_user', None)
                    session.pop('telegram_id', None)
                    is_telegram_user = False
                    telegram_id = None
                    logger.warning(
                        f"Session Telegram incohérente détectée pour l'utilisateur {current_user.id}, nettoyage effectué"
                    )

            # Vérifier si l'utilisateur actuel est réellement l'utilisateur WhatsApp indiqué
            if is_whatsapp_user and whatsapp_number and current_user.is_authenticated:
                if not current_user.phone_number.startswith(
                        f"whatsapp_{whatsapp_number}"):
                    # Les identifiants ne correspondent pas, nettoyer les données WhatsApp
                    session.pop('is_whatsapp_user', None)
                    session.pop('whatsapp_number', None)
                    is_whatsapp_user = False
                    whatsapp_number = None
                    logger.warning(
                        f"Session WhatsApp incohérente détectée pour l'utilisateur {current_user.id}, nettoyage effectué"
                    )

            else:
                # Ce bloc gère maintenant TOUS les utilisateurs connectés (Web, WhatsApp via Web, Telegram via Web)
                if current_user.is_authenticated:  # Vérification si l'utilisateur est authentifié
                    # Récupère les conversations de la table Conversation liées à cet user_id
                    # (Fonctionne pour 'user_123', 'whatsapp_...', ET 'telegram_...')
                    recent_conversations = Conversation.query.filter_by(
                        deleted=False, user_id=current_user.id).order_by(
                            Conversation.updated_at.desc()).limit(
                                CONTEXT_MESSAGE_LIMIT).all()

                    for conv in recent_conversations:
                        # Chercher le premier message de l'utilisateur dans cette conversation (pour le titre)
                        first_user_message = Message.query.filter_by(
                            conversation_id=conv.id, role='user').order_by(
                                Message.created_at.asc()).first()

                        # Définir le titre basé sur le premier message ou le titre existant
                        title = conv.title
                        if first_user_message and first_user_message.content and not title:
                            message_text = first_user_message.content.strip()
                            # Exclure le contenu extrait d'image si présent
                            if '[Extracted Image Content]' in message_text:
                                message_text = message_text.split(
                                    '[Extracted Image Content]')[0].strip()

                            if message_text:
                                title = message_text[:30] + "..." if len(
                                    message_text) > 30 else message_text

                        # Utiliser le titre par défaut si aucun titre n'a été défini
                        if not title:
                            title = f"Conversation du {conv.created_at.strftime('%d/%m/%Y')}"

                        # Ajouter à l'historique pour la barre latérale (sans marqueur de plateforme)
                        conversation_history.append({
                            'id':
                            conv.id,
                            'title':
                            title,
                            'subject':
                            'Général',  # Peut être ajusté si nécessaire
                            'time':
                            conv.created_at.strftime('%H:%M')
                            # PAS de clé 'is_telegram' ou 'is_whatsapp' ici
                        })

            return render_template(
                'chat.html',
                history=[],
                conversation_history=conversation_history,
                # is_telegram=is_telegram_user, # Ligne supprimée
                credits=42)
    except Exception as e:
        logger.error(f"Error in chat route: {str(e)}")
        return render_template(
            'chat.html',
            history=[],
            conversation_history=[],
            credits=42,
            error="Une erreur est survenue. Veuillez réessayer.")


# ============================================================================
# ROUTES POUR LE SYSTÈME DE MATIÈRES ET ENREGISTREMENT AUDIO
# ============================================================================

@app.route('/subjects')
@login_required
def subjects_page():
    """Page affichant les 4 matières disponibles pour l'enregistrement"""
    return render_template('subjects.html')


@app.route('/record/mathematics')
@login_required
def record_mathematics():
    """Page d'enregistrement audio pour Mathématiques"""
    return render_template('record_mathematics.html')


@app.route('/record/physics')
@login_required
def record_physics():
    """Page d'enregistrement audio pour Physique"""
    return render_template('record_physics.html')


@app.route('/record/chemistry')
@login_required
def record_chemistry():
    """Page d'enregistrement audio pour Chimie"""
    return render_template('record_chemistry.html')


@app.route('/record/svt')
@login_required
def record_svt():
    """Page d'enregistrement audio pour SVT (Sciences de la Vie et de la Terre)"""
    return render_template('record_svt.html')


@app.route('/api/save-audio', methods=['POST'])
@login_required
def save_audio():
    """
    API pour sauvegarder un enregistrement audio de cours et déclencher le traitement
    
    Cette route reçoit :
    - audio : fichier audio (webm format)
    - subject : matière (Mathématiques, Physique, Chimie, SVT)
    
    Processus complet :
    1. Sauvegarde temporaire du fichier
    2. Transcription via Groq Whisper
    3. Amélioration du texte par l'IA d'Exô
    4. Enregistrement dans la base de données (table Lesson)
    5. Nettoyage du fichier temporaire
    """
    try:
        from audio_handler import save_lesson_from_audio
        
        audio_file = request.files.get('audio')
        subject = request.form.get('subject')
        
        if not audio_file or not subject:
            logger.warning(f"Requête audio incomplète - audio: {bool(audio_file)}, subject: {subject}")
            return jsonify({'error': 'Fichier audio ou matière manquant'}), 400
        
        logger.info(f"🎓 Traitement de leçon {subject} pour l'utilisateur {current_user.id}")
        
        # Traiter l'audio avec le système intégré (transcription + amélioration + sauvegarde BD)
        result = save_lesson_from_audio(
            audio_file=audio_file,
            subject=subject,
            user_id=current_user.id
        )
        
        if result.get('success'):
            logger.info(f"✅ Leçon {result.get('lesson_id')} traitée avec succès")
            return jsonify({
                'success': True,
                'message': 'Leçon enregistrée avec succès',
                'lesson_id': result.get('lesson_id'),
                'subject': subject,
                'transcript': result.get('transcript'),
                'improved_text': result.get('improved_text'),
                'duration': result.get('duration')
            }), 200
        else:
            logger.error(f"❌ Échec du traitement: {result.get('error')}")
            return jsonify({
                'success': False,
                'error': result.get('error', 'Erreur lors du traitement de l\'audio')
            }), 500
        
    except Exception as e:
        logger.error(f"❌ Erreur critique dans save_audio: {str(e)}", exc_info=True)
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500

# ============================================================================
# FIN DES ROUTES MATIÈRES
# ============================================================================


# ============================================================================
# ROUTES DE VISUALISATION DES LEÇONS
# ============================================================================

@app.route('/lessons/mathematics')
@login_required
def lessons_mathematics():
    """Page de liste des leçons de Mathématiques"""
    return render_template('lessons_mathematics.html')


@app.route('/lessons/physics')
@login_required
def lessons_physics():
    """Page de liste des leçons de Physique"""
    return render_template('lessons_physics.html')


@app.route('/lessons/chemistry')
@login_required
def lessons_chemistry():
    """Page de liste des leçons de Chimie"""
    return render_template('lessons_chemistry.html')


@app.route('/lessons/svt')
@login_required
def lessons_svt():
    """Page de liste des leçons de SVT"""
    return render_template('lessons_svt.html')


@app.route('/lesson/<int:lesson_id>')
@login_required
def lesson_detail(lesson_id):
    """Page de détail d'une leçon"""
    return render_template('lesson_detail.html')


# ============================================================================
# API ENDPOINTS POUR LES LEÇONS
# ============================================================================

@app.route('/api/lessons/<subject>')
@login_required
def get_lessons_by_subject(subject):
    """Récupère toutes les leçons d'une matière pour l'utilisateur connecté"""
    try:
        # Mapper les noms de matières URL vers les noms en base
        subject_map = {
            'mathematics': 'Mathématiques',
            'physics': 'Physique',
            'chemistry': 'Chimie',
            'svt': 'SVT'
        }
        
        subject_name = subject_map.get(subject)
        if not subject_name:
            return jsonify({'success': False, 'error': 'Matière invalide'}), 400
        
        # Récupérer les leçons de l'utilisateur pour cette matière
        lessons = Lesson.query.filter_by(
            user_id=current_user.id,
            subject=subject_name
        ).order_by(Lesson.created_at.desc()).all()
        
        # Convertir en JSON
        lessons_data = [{
            'id': lesson.id,
            'subject': lesson.subject,
            'original_transcript': lesson.original_transcript,
            'improved_transcript': lesson.improved_transcript,
            'duration_seconds': lesson.duration_seconds,
            'language': lesson.language,
            'status': lesson.status,
            'created_at': lesson.created_at.isoformat(),
            'updated_at': lesson.updated_at.isoformat()
        } for lesson in lessons]
        
        return jsonify({
            'success': True,
            'lessons': lessons_data,
            'count': len(lessons_data)
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des leçons: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/lesson/<int:lesson_id>')
@login_required
def get_lesson_detail(lesson_id):
    """Récupère les détails d'une leçon spécifique"""
    try:
        lesson = Lesson.query.filter_by(
            id=lesson_id,
            user_id=current_user.id
        ).first()
        
        if not lesson:
            return jsonify({'success': False, 'error': 'Leçon introuvable'}), 404
        
        lesson_data = {
            'id': lesson.id,
            'subject': lesson.subject,
            'original_transcript': lesson.original_transcript,
            'improved_transcript': lesson.improved_transcript,
            'duration_seconds': lesson.duration_seconds,
            'language': lesson.language,
            'status': lesson.status,
            'audio_filename': lesson.audio_filename,
            'audio_url': lesson.audio_url,
            'error_message': lesson.error_message,
            'created_at': lesson.created_at.isoformat(),
            'updated_at': lesson.updated_at.isoformat()
        }
        
        return jsonify({
            'success': True,
            'lesson': lesson_data
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de la leçon: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/lesson/<int:lesson_id>', methods=['DELETE'])
@login_required
def delete_lesson(lesson_id):
    """Supprime une leçon"""
    try:
        lesson = Lesson.query.filter_by(
            id=lesson_id,
            user_id=current_user.id
        ).first()
        
        if not lesson:
            return jsonify({'success': False, 'error': 'Leçon introuvable'}), 404
        
        # Supprimer le fichier audio si existe
        if lesson.audio_filename:
            audio_path = os.path.join('uploads', 'audio', lesson.audio_filename)
            if os.path.exists(audio_path):
                os.remove(audio_path)
        
        # Supprimer de la base de données
        db.session.delete(lesson)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Leçon supprimée avec succès'
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de la leçon: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_mode = request.form.get('login_mode', 'web')

        if login_mode == 'web' or login_mode == 'whatsapp':
            # Nettoyer les données Telegram de la session
            session.pop('is_telegram_user', None)
            session.pop('telegram_id', None)

            phone_number = request.form.get('phone_number')
            password = request.form.get('password')

            # S'assurer que le numéro commence par +225 si ce n'est pas déjà le cas
            if not phone_number.startswith('+'):
                phone_number = '+225' + phone_number

            # Vérifier le format du numéro de téléphone
            if not phone_number.startswith('+225') or len(
                    phone_number) != 12 or not phone_number[1:].isdigit():
                flash(
                    'Le numéro de téléphone doit être au format +22500000000.',
                    'error')
                return redirect(url_for('login'))

            # Check for admin credentials first
            if phone_number == os.environ.get('ADMIN_PHONE') and \
               password == os.environ.get('ADMIN_PASSWORD'):
                session['is_admin'] = True
                flash('Connecté en tant qu\'administrateur.', 'success')
                return redirect(url_for('admin_dashboard'))

            # Vérifier si le numéro existe quelque part dans la base de données
            if not phone_number_exists(phone_number):
                # Rediriger avec paramètre d'erreur "no_account"
                return redirect(url_for('login', error='no_account'))

            # Normaliser le numéro en supprimant le + pour les formats spéciaux
            normalized_number = phone_number.replace('+', '')

            # Traitement spécifique pour login WhatsApp
            if login_mode == 'whatsapp':
                # Vérifier si un utilisateur web "normal" existe avec ce numéro
                web_user = User.query.filter_by(
                    phone_number=phone_number).first()

                # Vérifier si un utilisateur Telegram existe avec ce numéro
                telegram_user = TelegramUser.query.filter(
                    TelegramUser.phone_number != "---",
                    TelegramUser.phone_number == phone_number).first()

                # Si l'utilisateur existe dans la base de données web ou Telegram, afficher un message approprié
                if web_user:
                    # Rediriger avec un paramètre spécial pour afficher le modal indiquant que c'est un compte web
                    return redirect(
                        url_for('login',
                                error='web_account',
                                phone=phone_number))

                if telegram_user:
                    # Rediriger avec un paramètre spécial pour afficher le modal indiquant que c'est un compte Telegram
                    return redirect(
                        url_for('login',
                                error='telegram_account',
                                phone=phone_number))

                # Si l'utilisateur n'existe pas en tant que compte web ou Telegram, continuer avec la logique WhatsApp
                # Vérifier si un utilisateur web existe déjà pour ce numéro avec préfixe WhatsApp
                user = User.query.filter_by(
                    phone_number=f"whatsapp_{normalized_number}").first()

                if not user:
                    # Vérifier si le numéro existe dans les messages WhatsApp
                    whatsapp_message = WhatsAppMessage.query.filter_by(
                        from_number=normalized_number).first()

                    if not whatsapp_message:
                        # Pas de message WhatsApp trouvé pour ce numéro
                        flash('Aucun compte WhatsApp trouvé avec ce numéro.',
                              'error')
                        return redirect(
                            url_for('login', error='no_whatsapp_account'))

                    # Créer un nouvel utilisateur web pour ce numéro WhatsApp
                    user = User(
                        first_name="WhatsApp",
                        last_name="User",
                        age=18,  # Valeur par défaut
                        phone_number=
                        f"whatsapp_{normalized_number}",  # Format spécial pour identifier les utilisateurs WhatsApp
                        study_level="Non spécifié",
                        grade_goals="average"  # Valeur par défaut
                    )
                    # Définir le mot de passe entré
                    user.set_password(password)

                    db.session.add(user)
                    db.session.commit()

                    # Émettre l'événement de nouvel utilisateur Web pour le tableau de bord
                    socketio.emit(
                        'new_web_user', {
                            'id': user.id,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'phone_number': user.phone_number
                        })
                else:
                    # Si l'utilisateur existe, vérifier le mot de passe
                    if not user.check_password(password):
                        return redirect(
                            url_for('login', error='wrong_password'))

                # Définir les variables de session pour indiquer une connexion via WhatsApp
                session['is_whatsapp_user'] = True
                session['whatsapp_number'] = normalized_number

                # Connecter l'utilisateur et rediriger vers le chat
                login_user(user)
                flash('Connecté via WhatsApp avec succès!', 'success')
                return redirect(url_for('chat'))

            # Logique pour login Web standard - vérifier tous les types d'utilisateurs
            # D'abord essayer de trouver un utilisateur web standard
            user = User.query.filter_by(phone_number=phone_number).first()

            if not user:
                # Vérifier s'il existe un message WhatsApp pour ce numéro
                whatsapp_message = WhatsAppMessage.query.filter_by(
                    from_number=normalized_number).first()
                if whatsapp_message:
                    # Rediriger vers login avec paramètre d'erreur 'whatsapp_account'
                    return redirect(
                        url_for('login',
                                error='whatsapp_account',
                                phone=phone_number))

                # Vérifier s'il existe un utilisateur WhatsApp pour ce numéro
                whatsapp_user = User.query.filter_by(
                    phone_number=f"whatsapp_{normalized_number}").first()
                if whatsapp_user:
                    # Rediriger vers login avec paramètre d'erreur 'whatsapp_account'
                    return redirect(
                        url_for('login',
                                error='whatsapp_account',
                                phone=phone_number))

                # Si aucun compte WhatsApp, vérifier Telegram
                telegram_user = TelegramUser.query.filter(
                    TelegramUser.phone_number != "---",
                    TelegramUser.phone_number == phone_number).first()

                if telegram_user:
                    # Obtenir ou créer un utilisateur Web associé à ce TelegramUser
                    user = get_or_create_web_user_for_telegram(telegram_user)
                    session['is_telegram_user'] = True
                    session['telegram_id'] = telegram_user.telegram_id
                else:
                    # Si aucun utilisateur trouvé, rediriger avec erreur
                    return redirect(url_for('login', error='no_account'))
            else:
                # Si l'utilisateur est un utilisateur web standard
                session.pop('is_whatsapp_user', None)
                session.pop('whatsapp_number', None)
                session.pop('is_telegram_user', None)
                session.pop('telegram_id', None)

            # Vérifier si le mot de passe est correct
            if not user.check_password(password):
                # Rediriger avec paramètre d'erreur "wrong_password"
                return redirect(url_for('login', error='wrong_password'))

            # Si tout est correct, connecter l'utilisateur
            login_user(user)
            return redirect(url_for('chat'))

        elif login_mode == 'telegram':
            # Récupérer l'ID Telegram et le numéro de téléphone
            telegram_id = request.form.get('telegram_id')
            telegram_phone = request.form.get('telegram_phone')

            # Validation de l'ID Telegram
            if not telegram_id or not telegram_id.strip().isdigit():
                flash('Veuillez entrer un ID Telegram valide (numérique).',
                      'error')
                return redirect(url_for('login'))

            # Validation du numéro de téléphone
            if not telegram_phone:
                flash('Veuillez entrer un numéro de téléphone.', 'error')
                return redirect(url_for('login'))

            # S'assurer que le numéro commence par +225 si ce n'est pas déjà le cas
            if not telegram_phone.startswith('+'):
                telegram_phone = '+225' + telegram_phone

            # Vérifier le format du numéro
            if not telegram_phone.startswith('+225') or len(
                    telegram_phone) != 12 or not telegram_phone[1:].isdigit():
                flash(
                    'Le numéro de téléphone doit être au format +22500000000.',
                    'error')
                return redirect(url_for('login'))

            # Convertir en entier
            telegram_id = int(telegram_id)

            # Vérifier si cet ID existe dans la base de données
            telegram_user = TelegramUser.query.get(telegram_id)

            if not telegram_user:
                flash('Aucun compte Telegram trouvé avec cet ID.', 'error')
                return redirect(url_for('login'))

            # Mettre à jour le numéro de téléphone de l'utilisateur Telegram s'il n'en a pas encore
            if telegram_user.phone_number == "---":
                telegram_user.phone_number = telegram_phone
                db.session.commit()

            # Obtenir ou créer un utilisateur Web associé à cet utilisateur Telegram
            user = get_or_create_web_user_for_telegram(telegram_user)

            # Connecter l'utilisateur
            login_user(user)

            # Définir des variables de session pour indiquer une connexion via Telegram
            session['is_telegram_user'] = True
            session['telegram_id'] = telegram_id

            flash('Connecté via Telegram avec succès!', 'success')
            return redirect(url_for('chat'))

        flash('Identifiants de connexion incorrects.', 'error')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    """Logout route for all users"""
    # Nettoyer toutes les données de session pertinentes
    session.pop('is_telegram_user', None)
    session.pop('telegram_id', None)
    session.pop('thread_id', None)
    session.pop('is_admin', None)
    logout_user()  # Fonction de Flask-Login pour déconnecter l'utilisateur
    flash('Vous avez été déconnecté.', 'success')
    return redirect(url_for('login'))


@app.route('/refresh_session', methods=['POST'])
def refresh_session():
    """Endpoint pour maintenir la session active"""
    # Simplement renvoyer un succès pour maintenir la session
    return jsonify({'success': True})


@app.route('/admin')
def admin_dashboard():
    """Admin dashboard route that displays platform statistics"""
    # Check if user is admin
    if not session.get('is_admin'):
        flash(
            'Accès non autorisé. Veuillez vous connecter en tant qu\'administrateur.',
            'error')
        return redirect(url_for('login'))

    try:
        # Get web platform data
        users = User.query.all()
        conversations = Conversation.query.all()
        today = datetime.today().date()

        # Count today's conversations
        today_conversations = sum(1 for conv in conversations
                                  if conv.created_at.date() == today)

        # Get actual number of users
        active_users = len(users)
        # Count users created today
        active_users_today = sum(1 for user in users
                                 if user.created_at.date() == today)

        # Calculate satisfaction rate based on message feedback
        total_feedbacks = MessageFeedback.query.count()
        positive_feedbacks = MessageFeedback.query.filter_by(
            feedback_type='positive').count()

        # Calculate satisfaction rate (percentage of positive feedback)
        satisfaction_rate = round((positive_feedbacks / total_feedbacks) *
                                  100) if total_feedbacks > 0 else 0

        # Get OpenAI Assistant ID for settings
        openai_assistant_id = os.environ.get('OPENAI_ASSISTANT_ID',
                                             'Non configuré')

        return render_template(
            'admin_dashboard.html',
            active_users=active_users,
            active_users_today=active_users_today,
            today_conversations=today_conversations,
            satisfaction_rate=satisfaction_rate,
            is_admin=True,
            openai_assistant_id=openai_assistant_id,  # Add OpenAI Assistant ID
            current_model=CURRENT_MODEL,  # Add current model selection
            deepseek_instructions=
            DEEPSEEK_INSTRUCTIONS,  # Add DeepSeek instructions
            deepseek_reasoner_instructions=
            DEEPSEEK_REASONER_INSTRUCTIONS,  # Add DeepSeek Reasoner instructions
            qwen_instructions=QWEN_INSTRUCTIONS,  # Add Qwen instructions
            gemini_instructions=GEMINI_INSTRUCTIONS  # Add Gemini instructions
        )
    except Exception as e:
        logger.error(f"Error in admin dashboard: {str(e)}")
        flash('Une erreur est survenue lors du chargement du tableau de bord.',
              'error')
        return redirect(url_for('login'))


@app.route('/admin/settings/model', methods=['POST'])
def update_model_settings():
    """Update AI model settings"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        data = request.get_json()
        model = data.get('model')
        instructions = data.get('instructions')

        if model not in [
                'openai', 'deepseek', 'deepseek-reasoner', 'qwen', 'gemini'
        ]:
            return jsonify({'error': 'Invalid model selection'}), 400

        # Update the current model in ai_config
        import ai_config
        ai_config.CURRENT_MODEL = model

        # Update environment variables for persistence
        os.environ['CURRENT_MODEL'] = model

        # Ensure instructions directory exists
        os.makedirs('instructions', exist_ok=True)

        # Update instructions based on model
        if model == 'deepseek' and instructions:
            DEEPSEEK_INSTRUCTIONS = instructions
            with open('instructions/deepseek.txt', 'w', encoding='utf-8') as f:
                f.write(instructions)
        elif model == 'deepseek-reasoner' and instructions:
            DEEPSEEK_REASONER_INSTRUCTIONS = instructions
            with open('instructions/deepseek_reasoner.txt',
                      'w',
                      encoding='utf-8') as f:
                f.write(instructions)
        elif model == 'qwen' and instructions:
            QWEN_INSTRUCTIONS = instructions
            with open('instructions/qwen.txt', 'w', encoding='utf-8') as f:
                f.write(instructions)
        elif model == 'gemini' and instructions:
            GEMINI_INSTRUCTIONS = instructions
            with open('instructions/gemini.txt', 'w', encoding='utf-8') as f:
                f.write(instructions)

        # Update .env with only the model selection
        env_path = '.env'
        env_vars = {}

        # Read existing variables
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        env_vars[key] = value

        # Update with new model value
        env_vars['CURRENT_MODEL'] = model

        # Set file paths in env vars
        env_vars['DEEPSEEK_INSTRUCTIONS_FILE'] = 'instructions/deepseek.txt'
        env_vars[
            'DEEPSEEK_REASONER_INSTRUCTIONS_FILE'] = 'instructions/deepseek_reasoner.txt'
        env_vars['QWEN_INSTRUCTIONS_FILE'] = 'instructions/qwen.txt'
        env_vars['GEMINI_INSTRUCTIONS_FILE'] = 'instructions/gemini.txt'

        # Write back to .env
        with open(env_path, 'w') as f:
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")

        # Reload environment variables
        load_dotenv()

        # Recharger les paramètres du modèle
        reload_model_settings()

        return jsonify({
            'success': True,
            'message': 'Model settings updated successfully'
        })
    except Exception as e:
        logger.error(f"Error updating model settings: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


if 'RUN_TELEGRAM_BOT' not in os.environ:
    os.environ['RUN_TELEGRAM_BOT'] = 'true'
    logger.info("Enabled Telegram bot (RUN_TELEGRAM_BOT=true)")

    # Mettre à jour .env également
    env_path = '.env'
    env_vars = {}

    # Lire les variables existantes
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    env_vars[key] = value

    # Mettre à jour avec la nouvelle valeur
    env_vars['RUN_TELEGRAM_BOT'] = 'true'

    # Écrire dans .env
    with open(env_path, 'w') as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")


@app.route('/admin/logout')
def admin_logout():
    """Logout route for admin"""
    session.pop('is_admin', None)
    flash('Vous avez été déconnecté.', 'success')
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Nettoyer les données Telegram de la session pour les nouveaux utilisateurs
        session.pop('is_telegram_user', None)
        session.pop('telegram_id', None)
        session.pop('thread_id', None)

        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        age = request.form.get('age')
        phone_number = request.form.get('phone_number')
        password = request.form.get('password')
        study_level = request.form.get(
            'study_level') or 'Terminal A'  # Default value
        grade_goals = request.form.get(
            'grade_goals') or 'average'  # Default value

        # Basic validation
        if not all([first_name, last_name, age, phone_number, password]):
            flash('Tous les champs obligatoires doivent être remplis.',
                  'error')
            return redirect(url_for('register'))

        # Vérifier le format du numéro de téléphone (doit commencer par +225 suivi de 8 chiffres)
        if not phone_number.startswith('+225') or len(
                phone_number) != 12 or not phone_number[1:].isdigit():
            flash('Le numéro de téléphone doit être au format +22500000000.',
                  'error')
            return redirect(url_for('register'))

        # Vérifier si le numéro existe déjà
        if phone_number_exists(phone_number):
            flash('Ce numéro de téléphone est déjà utilisé.', 'error')
            # Rediriger avec un paramètre pour afficher la modal
            return redirect(url_for('register', error='phone_exists'))

        try:
            # Create new user
            user = User(first_name=first_name,
                        last_name=last_name,
                        age=int(age),
                        phone_number=phone_number,
                        study_level=study_level,
                        grade_goals=grade_goals)
            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            # Émettre l'événement de nouvel utilisateur Web pour le tableau de bord
            socketio.emit(
                'new_web_user', {
                    'id': user.id,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'phone_number': user.phone_number
                })

            # Log the user in
            login_user(user)
            return redirect(url_for('chat'))

        except Exception as e:
            db.session.rollback()
            flash('Une erreur est survenue lors de l\'inscription.', 'error')
            app.logger.error(f"Registration error: {str(e)}")
            return redirect(url_for('register'))

    # Vérifier s'il y a un paramètre d'erreur pour afficher la modal
    error = request.args.get('error')
    return render_template('register.html', error=error)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        account_type = request.form.get('account_type', 'web')
        phone_number = request.form.get('phone_number')
        new_password = request.form.get('new_password')

        if not new_password:
            flash('Veuillez entrer un nouveau mot de passe.', 'error')
            return redirect(url_for('forgot_password'))

        user = None

        if account_type == 'whatsapp':
            # Formater le numéro pour correspondre au format WhatsApp
            if phone_number.startswith('+'):
                whatsapp_number = phone_number[1:]  # Enlever le + si présent
            else:
                whatsapp_number = phone_number

            # Rechercher l'utilisateur avec le préfixe whatsapp_
            user = User.query.filter_by(
                phone_number=f"whatsapp_{whatsapp_number}").first()

            # Si l'utilisateur n'existe pas, vérifier s'il y a des messages WhatsApp pour ce numéro
            if not user:
                whatsapp_message = WhatsAppMessage.query.filter_by(
                    from_number=whatsapp_number).first()

                if whatsapp_message:
                    # Créer un nouvel utilisateur pour ce numéro WhatsApp
                    user = User(
                        first_name="WhatsApp",
                        last_name="User",
                        age=18,  # Valeur par défaut
                        phone_number=f"whatsapp_{whatsapp_number}",
                        study_level="Non spécifié",
                        grade_goals="average"  # Valeur par défaut
                    )
                    db.session.add(user)
                    logger.info(
                        f"Nouvel utilisateur WhatsApp créé lors de la réinitialisation du mot de passe: {whatsapp_number}"
                    )
        else:
            # Recherche standard pour les utilisateurs web
            user = User.query.filter_by(phone_number=phone_number).first()

        if user:
            # Mettre à jour le mot de passe de l'utilisateur
            user.set_password(new_password)
            db.session.commit()
            logger.info(
                f"Mot de passe mis à jour pour l'utilisateur: {user.phone_number}"
            )

            # Passer un paramètre pour afficher le popup
            return render_template('forgot_password.html',
                                   password_updated=True)

        flash(
            f"Aucun compte {'WhatsApp' if account_type == 'whatsapp' else ''} trouvé avec ce numéro.",
            'error')
        return redirect(url_for('forgot_password'))

    return render_template('forgot_password.html')


# --- NOTE IMPORTANTE ---
# La route PUT /admin/conversations/<platform>/<int:conv_id>/status
# devient moins pertinente pour gérer l'état "actif/inactif" basé sur le temps.
# Elle pourrait être conservée pour une fonctionnalité d'archivage manuel explicite
# qui serait distincte de l'activité récente, ou être supprimée/modifiée.
# --- FIN NOTE ---


@login_manager.unauthorized_handler
def unauthorized():
    """Redirect unauthorized users to Login page."""
    flash('Please log in to access this page.')
    return redirect(url_for('register'))


@app.route('/admin/users/<user_id>', methods=['DELETE'])
def delete_user(user_id):
    """Delete a user and their associated data."""
    try:
        logger.info(f"Attempting to delete user with ID: {user_id}")

        # Find the user based on the platform data
        user = None

        # Try to find in web users
        user = User.query.filter_by(phone_number=user_id).first()
        if user:
            logger.info(
                f"Found web user with ID {user.id}, phone: {user.phone_number}"
            )

            try:
                # Importer le module text pour les requêtes SQL
                from sqlalchemy import text

                # Utiliser du SQL pur avec une connexion directe pour éviter
                # les problèmes avec le modèle ORM et gérer les transactions correctement
                with db.engine.begin() as connection:
                    # 1. Récupérer l'ID de l'utilisateur pour les requêtes suivantes
                    user_id_to_delete = user.id

                    # 2. Supprimer les associations dans user_subscription
                    logger.info(
                        f"Deleting subscription relationships for user {user_id_to_delete}"
                    )
                    connection.execute(
                        text(
                            "DELETE FROM subscription WHERE user_id = :user_id"
                        ), {"user_id": user_id_to_delete})

                    # 3. Supprimer les messages liés aux conversations de l'utilisateur
                    logger.info(
                        f"Deleting messages for user {user_id_to_delete}")
                    connection.execute(
                        text("""DELETE FROM message 
                                WHERE conversation_id IN (
                                    SELECT id FROM conversation WHERE user_id = :user_id
                                )"""), {"user_id": user_id_to_delete})

                    # 4. Supprimer les conversations de l'utilisateur
                    logger.info(
                        f"Deleting conversations for user {user_id_to_delete}")
                    connection.execute(
                        text(
                            "DELETE FROM conversation WHERE user_id = :user_id"
                        ), {"user_id": user_id_to_delete})

                    # 5. Supprimer l'utilisateur lui-même
                    # Note: le mot-clé "user" est réservé dans SQL, donc on le met entre guillemets
                    logger.info(f"Deleting user with ID {user_id_to_delete}")
                    connection.execute(
                        text("DELETE FROM \"user\" WHERE id = :user_id"),
                        {"user_id": user_id_to_delete})

                # Si on arrive ici, c'est que la transaction a été validée avec succès
                logger.info(f"Web user {user_id} deleted successfully")
                return jsonify({
                    'success': True,
                    'message': 'User deleted successfully'
                })

            except Exception as e:
                logger.error(f"Error deleting web user: {str(e)}")
                return jsonify({
                    'success': False,
                    'message': f'Error deleting user: {str(e)}'
                }), 500

        # Try to find in Telegram users
        user = TelegramUser.query.filter_by(telegram_id=user_id).first()
        if user:
            try:
                with db_retry_session() as session:
                    # Delete all messages first
                    for conv in user.conversations:
                        TelegramMessage.query.filter_by(
                            conversation_id=conv.id).delete()
                    session.flush()

                    # Delete all conversations
                    TelegramConversation.query.filter_by(
                        telegram_user_id=user.telegram_id).delete()
                    session.flush()

                    # Finally delete the user
                    session.delete(user)
                    session.commit()
                    return jsonify({
                        'success':
                        True,
                        'message':
                        'Telegram user deleted successfully'
                    })
            except Exception as telegram_error:
                logger.error(
                    f"Error deleting Telegram user: {str(telegram_error)}")
                session.rollback()
                return jsonify({
                    'success':
                    False,
                    'message':
                    f'Error deleting Telegram user: {str(telegram_error)}'
                }), 500

        # Check WhatsApp users (using the phone number as ID)
        messages = WhatsAppMessage.query.filter_by(from_number=user_id).all()
        if messages:
            try:
                with db_retry_session() as session:
                    # On récupère d'abord tous les thread_id associés à ce numéro
                    thread_ids = db.session.query(WhatsAppMessage.thread_id)\
                        .filter(WhatsAppMessage.from_number == user_id)\
                        .distinct().all()

                    # Pour chaque thread_id, on supprime tous les messages associés
                    for thread_id in thread_ids:
                        thread_id = thread_id[
                            0]  # Extraction de la valeur depuis le tuple
                        logger.info(
                            f"Deleting all messages for WhatsApp thread {thread_id}"
                        )
                        WhatsAppMessage.query.filter_by(
                            thread_id=thread_id).delete()

                    session.commit()
                    return jsonify({
                        'success':
                        True,
                        'message':
                        'WhatsApp user and all associated conversations deleted successfully'
                    })
            except Exception as whatsapp_error:
                logger.error(
                    f"Error deleting WhatsApp messages: {str(whatsapp_error)}")
                session.rollback()
                return jsonify({
                    'success':
                    False,
                    'message':
                    f'Error deleting WhatsApp messages: {str(whatsapp_error)}'
                }), 500

        return jsonify({'success': False, 'message': 'User not found'}), 404

    except Exception as e:
        logger.error(f"Error in delete_user function for {user_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Server error: {str(e)}'
        }), 500


@app.route('/admin/subscriptions', methods=['GET'])
def get_subscriptions():
    """Get all subscriptions data"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        subscriptions = Subscription.query.all()

        return jsonify({
            'subscriptions': [{
                'id':
                sub.id,
                'user_id':
                sub.user_id,
                'user_name':
                f"{sub.user.first_name} {sub.user.last_name}",
                'type':
                sub.subscription_type,
                'start_date':
                sub.start_date.strftime('%Y-%m-%d'),
                'expiry_date':
                sub.expiry_date.strftime('%Y-%m-%d'),
                'status':
                sub.status,
                'last_payment_date':
                sub.last_payment_date.strftime('%Y-%m-%d')
                if sub.last_payment_date else None
            } for sub in subscriptions]
        })

    except Exception as e:
        logger.error(f"Error fetching subscriptions: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/admin/subscriptions', methods=['POST'])
def create_subscription():
    """Create a new subscription"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        data = request.get_json()

        # Validate required fields
        required_fields = [
            'user_id', 'subscription_type', 'expiry_date', 'status'
        ]
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        # Create new subscription
        subscription = Subscription(
            user_id=data['user_id'],
            subscription_type=data['subscription_type'],
            start_date=datetime.now(),
            expiry_date=datetime.strptime(data['expiry_date'], '%Y-%m-%d'),
            status=data['status'],
            last_payment_date=datetime.now())

        db.session.add(subscription)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Subscription created successfully',
            'subscription_id': subscription.id
        })

    except Exception as e:
        logger.error(f"Error creating subscription: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/admin/subscriptions/<int:subscription_id>', methods=['PUT'])
def update_subscription(subscription_id):
    """Update an existing subscription"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        subscription = Subscription.query.get(subscription_id)
        if not subscription:
            return jsonify({'error': 'Subscription not found'}), 404

        data = request.get_json()

        # Update fields if provided
        if 'subscription_type' in data:
            subscription.subscription_type = data['subscription_type']
        if 'expiry_date' in data:
            subscription.expiry_date = datetime.strptime(
                data['expiry_date'], '%Y-%m-%d')
        if 'status' in data:
            subscription.status = data['status']

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Subscription updated successfully'
        })

    except Exception as e:
        logger.error(f"Error updating subscription: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/admin/subscriptions/<int:subscription_id>', methods=['DELETE'])
def delete_subscription(subscription_id):
    """Delete a subscription"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        subscription = Subscription.query.get(subscription_id)
        if not subscription:
            return jsonify({'error': 'Subscription not found'}), 404

        db.session.delete(subscription)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Subscription deleted successfully'
        })

    except Exception as e:
        logger.error(f"Error deleting subscription: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


# --- DÉMARRAGE DU SCHEDULER ---
# Import ici pour éviter l'import circulaire avec les modèles
from memory_consolidator import run_consolidation_task
from reminder_system import run_night_reminder_job

# Initialisation du scheduler
scheduler = BackgroundScheduler()
# Tâche de nettoyage des uploads (toutes les heures)
scheduler.add_job(func=cleanup_uploads, trigger="interval", hours=1)
# Tâche de consolidation de la mémoire (tous les jours à 00h10)
scheduler.add_job(func=run_consolidation_task,
                  trigger="cron",
                  hour=1,
                  minute=0)
# Tâche de rappel nuit (tous les jours à 22h30)
scheduler.add_job(func=run_night_reminder_job,
                  trigger="cron",
                  hour=23,
                  minute=0)

# Démarrer le scheduler si ce n'est pas déjà fait
# (La condition est utile pour éviter les redémarrages multiples en mode debug)
if not scheduler.running:
    scheduler.start()
    logger.info(
        "Scheduler démarré : cleanup (1h) + consolidation mémoire (00h10) + rappel nuit (22h30)"
    )
# --- FIN DÉMARRAGE DU SCHEDULER ---

if __name__ == '__main__':

    socketio.run(app, host='0.0.0.0', port=8080, debug=True)
