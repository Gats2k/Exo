from flask import session
from flask_login import current_user
from flask_socketio import emit
from database import db
from models import Conversation, Message, MessageFeedback
from utils import db_retry_session
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def handle_rename(data):
    """Renomme une conversation"""
    from app import socketio  # Lazy import pour éviter circularité

    try:
        conversation = Conversation.query.get(data['id'])
        if conversation:
            conversation.title = data['title']
            db.session.commit()
            # Include the title and id in the emit event to allow header title update
            emit('conversation_updated', {
                'success': True, 
                'title': conversation.title,
                'id': conversation.id
            })
    except Exception as e:
        emit('conversation_updated', {'success': False, 'error': str(e)})


def handle_delete(data):
    """Supprime une conversation"""
    from app import socketio  # Lazy import

    try:
        conversation = Conversation.query.get(data['id'])
        if conversation:
            # Delete associated messages first
            Message.query.filter_by(conversation_id=conversation.id).delete()
            db.session.delete(conversation)
            db.session.commit()
            emit('conversation_deleted', {'success': True})
    except Exception as e:
        emit('conversation_deleted', {'success': False, 'error': str(e)})


def handle_open_conversation(data):
    """Ouvre une conversation et récupère ses messages"""
    from app import socketio  # Lazy import

    try:
        conversation = Conversation.query.get(data['id'])
        if conversation:
            # Update session with the opened conversation
            session['thread_id'] = conversation.thread_id

            # Get messages for this conversation
            messages = Message.query.filter_by(
                conversation_id=conversation.id).order_by(
                    Message.created_at).all()
            messages_data = []

            user_id = current_user.id if current_user.is_authenticated else None

            for msg in messages:
                # Filtrer le contenu pour supprimer le texte extrait par Mathpix
                filtered_content = msg.content

                # Seulement pour les messages utilisateur qui contiennent du texte extrait
                if msg.role == 'user' and '[Extracted Image Content]' in filtered_content:
                    # Ne garder que la partie avant le texte extrait
                    filtered_content = filtered_content.split(
                        '[Extracted Image Content]')[0].strip()

                    # Si le message ne contient que le texte extrait (donc vide maintenant)
                    if not filtered_content and msg.image_url:
                        filtered_content = ""  # Message vide car l'image sera affichée

                # Add base message data
                message_data = {
                    'id': msg.id,  # Include message ID for feedback tracking
                    'role': msg.role,
                    'content': filtered_content,  # Utiliser le contenu filtré
                    'image_url': msg.image_url,
                }

                # If it's an assistant message, check for existing feedback
                if msg.role == 'assistant':
                    # Get existing feedback for this message from the current user
                    feedback = MessageFeedback.query.filter_by(
                        message_id=msg.id, user_id=user_id).first()

                    if feedback:
                        message_data['feedback'] = feedback.feedback_type

                messages_data.append(message_data)

            emit(
                'conversation_opened', {
                    'success':
                    True,
                    'messages':
                    messages_data,
                    'conversation_id':
                    conversation.id,
                    'thread_id':
                    conversation.thread_id,
                    'title':
                    conversation.title or
                    f"Conversation du {conversation.created_at.strftime('%d/%m/%Y')}"
                })
        else:
            emit('conversation_opened', {
                'success': False,
                'error': 'Conversation introuvable'
            })
    except Exception as e:
        logger.error(f"Error opening conversation: {str(e)}")
        emit('conversation_opened', {'success': False, 'error': str(e)})


def handle_clear_session():
    """Efface la session pour démarrer une nouvelle conversation"""
    from app import socketio  # Lazy import

    try:
        logger.info("L'utilisateur a demandé une nouvelle conversation")

        # Supprimer l'ancien thread_id de la session
        session.pop('thread_id', None)

        # Ne pas créer de conversation - simplement notifier que la session est effacée
        emit('session_cleared', {'success': True})

        logger.info("Session effacée - aucune conversation créée à ce stade")
    except Exception as e:
        logger.error(
            f"Erreur lors de l'effacement de la session: {str(e)}"
        )
        emit('session_cleared', {'success': False, 'error': str(e)})


def handle_restore_session(data):
    """Restore a previous session based on a stored thread_id"""
    from app import socketio  # Lazy import
    from ai_config import get_ai_client, CURRENT_MODEL

    logger.info(f"--- handle_restore_session called with data: {data}")
    try:
        thread_id = data.get('thread_id')
        user_id_from_js = data.get('user_id')
        logger.info(f"--- Trying to restore using thread_id: {thread_id} (JS User ID: {user_id_from_js})")
        conversation = None

        if thread_id:
            logger.info(
                f"Attempting to restore session with thread_id: {thread_id}")
            # Vérifier si la conversation existe avec le thread_id correct
            conversation = Conversation.query.filter_by(thread_id=thread_id).first()
            logger.info(f"--- DB Query Result for thread_id {thread_id}: {conversation}")

            # Vérifier si la conversation appartient à l'utilisateur actuel
            if conversation and current_user.is_authenticated and conversation.user_id == current_user.id:
                logger.info(f"--- Ownership check PASSED for user {current_user.id} and conversation user {conversation.user_id}")
                # Vérifier l'existence du thread chez OpenAI si nécessaire
                ai_client = get_ai_client()
                valid_openai_thread = True
                if CURRENT_MODEL == 'openai':
                    try:
                        ai_client.beta.threads.retrieve(thread_id=thread_id)
                        logger.info(f"Thread OpenAI {thread_id} confirmé existant pour restauration.")
                    except Exception as e:
                        logger.warning(f"Thread OpenAI {thread_id} introuvable ou invalide pour restauration: {str(e)}.")
                        valid_openai_thread = False
                        conversation = None
                        session.pop('thread_id', None)
                else:
                    logger.warning(f"--- Ownership check FAILED for user {current_user.id} vs conversation user {conversation.user_id}")
                    conversation = None

                if valid_openai_thread and conversation:
                    logger.info(f"--- Preparing to restore session for valid thread_id: {conversation.thread_id}")
                    session['thread_id'] = conversation.thread_id
                    logger.info(f"--- Flask session 'thread_id' UPDATED to: {session.get('thread_id')}")
                    logger.info(
                        f"Session restored for thread_id: {conversation.thread_id}"
                    )
                    # Émettre les messages de la conversation restaurée
                    messages = Message.query.filter_by(
                        conversation_id=conversation.id).order_by(
                            Message.created_at).all()
                    messages_data = []
                    for msg in messages:
                        message_data = {'id': msg.id, 'role': msg.role, 'content': msg.content, 'image_url': msg.image_url}
                        messages_data.append(message_data)
                    emit(
                        'conversation_opened', {
                            'success': True,
                            'messages': messages_data,
                            'conversation_id': conversation.id,
                            'thread_id': conversation.thread_id,
                            'title': conversation.title or f"Conversation du {conversation.created_at.strftime('%d/%m/%Y')}"
                        })
                    # Mettre à jour la date de dernière modification
                    conversation.updated_at = datetime.utcnow()
                    db.session.commit()
                    return  # Important: sortir si la restauration a réussi

            if thread_id:
                logger.warning(
                    f"Conversation with id {thread_id} not found for session restoration"
                )
            else:
                logger.warning(
                    f"No existing conversation found for current user")
    except Exception as e:
        logger.error(f"Error in handle_restore_session: {str(e)}")
        logger.error(f"Error restoring session: {str(e)}")


def handle_feedback(data):
    """Handle feedback submission for a message"""
    from app import socketio  # Lazy import

    try:
        message_id = data.get('message_id')
        feedback_type = data.get('feedback_type')

        user_id = current_user.id if current_user.is_authenticated else None

        if not message_id or not feedback_type:
            emit('feedback_submitted', {
                'success': False,
                'error': 'Missing required parameters'
            })
            return

        if feedback_type not in ['positive', 'negative']:
            emit('feedback_submitted', {
                'success': False,
                'error': 'Invalid feedback type'
            })
            return

        with db_retry_session() as db_session:
            # Check if this user already gave feedback on this message
            existing_feedback = MessageFeedback.query.filter_by(
                message_id=message_id, user_id=user_id).first()

            if existing_feedback:
                # Update existing feedback
                existing_feedback.feedback_type = feedback_type
                db_session.commit()
            else:
                # Create new feedback entry
                new_feedback = MessageFeedback(message_id=message_id,
                                               user_id=user_id,
                                               feedback_type=feedback_type)
                db_session.add(new_feedback)
                db_session.commit()

            # Émettre le succès à l'utilisateur qui a soumis le feedback
            emit('feedback_submitted', {'success': True})

            # Calculer les nouvelles statistiques de satisfaction
            total_feedbacks = MessageFeedback.query.count()
            positive_feedbacks = MessageFeedback.query.filter_by(
                feedback_type='positive').count()
            satisfaction_rate = round((positive_feedbacks / total_feedbacks) *
                                      100) if total_feedbacks > 0 else 0

            # Émettre la mise à jour à tous les clients connectés (y compris le tableau de bord admin)
            socketio.emit(
                'feedback_stats_updated', {
                    'satisfaction_rate': satisfaction_rate,
                    'total_feedbacks': total_feedbacks,
                    'positive_feedbacks': positive_feedbacks
                })
    except Exception as e:
        logger.error(f"Error submitting feedback: {str(e)}")
        emit('feedback_submitted', {'success': False, 'error': str(e)})


def handle_heartbeat():
    """Simple heartbeat to keep the connection alive"""
    from app import socketio  # Lazy import

    # Vérifier si un thread_id est dans la session
    thread_id = session.get('thread_id')
    if thread_id:
        # Mettre à jour le timestamp de la conversation pour la garder active
        try:
            with db_retry_session() as db_session:
                conversation = Conversation.query.filter_by(thread_id=thread_id).first()
                if conversation:
                    conversation.updated_at = datetime.utcnow()
                    db_session.commit()
        except Exception as e:
            logger.warning(f"Error updating conversation timestamp during heartbeat: {str(e)}")

    # Retourner un simple ACK
    return {'status': 'ok'}