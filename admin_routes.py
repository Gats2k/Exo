from flask import Blueprint, request, jsonify, session
from flask_login import current_user, login_required
from database import db
from models import (
    Conversation, Message, TelegramConversation, TelegramMessage,
    User, TelegramUser, MessageFeedback
)
from utils import db_retry_session
from datetime import datetime, timedelta, date
from sqlalchemy import func, desc, or_, text
import logging

logger = logging.getLogger(__name__)

# Créer le Blueprint
admin_bp = Blueprint('admin_bp', __name__, url_prefix='/admin')


@admin_bp.route('/api/recover_message/<int:message_id>', methods=['GET'])
def recover_message(message_id):
    """Endpoint pour récupérer un message qui n'a pas pu être sauvegardé en BD ou dont le streaming s'est interrompu"""
    try:
        # D'abord, vérifier dans la base de données
        message = Message.query.get(message_id)

        # Si le message existe et a du contenu en BD
        if message and message.content and message.content.strip():
            logger.info(f"Récupération du message {message_id} depuis la BD")
            return jsonify({'success': True, 'content': message.content})

        # Sinon, vérifier dans la session
        if 'message_recovery' in session and str(message_id) in session['message_recovery']:
            content = session['message_recovery'][str(message_id)]

            # Si le message existe en BD mais est vide, le mettre à jour
            if message and (not message.content or message.content.strip() == ''):
                try:
                    message.content = content
                    db.session.commit()
                    # Si succès, supprimer de la session
                    del session['message_recovery'][str(message_id)]
                    logger.info(f"Message {message_id} récupéré de la session et sauvegardé en BD")
                except Exception as e:
                    logger.error(f"Échec de mise à jour du message {message_id} en BD: {str(e)}")

            return jsonify({'success': True, 'content': content})

        # Message non trouvé
        logger.warning(f"Message {message_id} non trouvé ni en BD ni en session")
        return jsonify({'success': False, 'error': 'Message non trouvé'})

    except Exception as e:
        logger.error(f"Erreur lors de la récupération du message {message_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/conversations/<platform>/<int:conv_id>/status', methods=['PUT'])
def update_conversation_status(platform, conv_id):
    """Met à jour le statut (active/archived) d'une conversation Web ou Telegram."""
    # Vérifier si l'utilisateur est admin (utilise la session admin)
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized access'}), 403

    try:
        data = request.get_json()
        new_status = data.get('status')

        if not new_status or new_status not in ['active', 'archived']:
            return jsonify({'error': 'Invalid or missing status parameter'}), 400

        conversation = None
        conv_model = None

        if platform == 'web':
            conv_model = Conversation
            conversation = Conversation.query.get(conv_id)
        elif platform == 'telegram':
            conv_model = TelegramConversation
            conversation = TelegramConversation.query.get(conv_id)
        else:
            return jsonify({'error': 'Platform not supported for status change'}), 400

        if not conversation:
            return jsonify({'error': 'Conversation not found'}), 404

        # Vérifier si la colonne status existe (elle devrait après la migration)
        if not hasattr(conversation, 'status'):
            logger.error(f"Tentative de mise à jour du statut mais colonne 'status' manquante pour {platform} conversation {conv_id}")
            return jsonify({'error': f"Status column missing for this platform type"}), 500

        conversation.status = new_status
        conversation.updated_at = datetime.utcnow()
        db.session.commit()

        logger.info(f"Statut de la conversation {platform} ID {conv_id} mis à jour à '{new_status}'")
        return jsonify({'success': True, 'message': 'Conversation status updated successfully'})

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error updating status for conversation {conv_id} on {platform}: {e}")
        return jsonify({'error': 'Internal server error during status update'}), 500


@admin_bp.route('/web/conversations/<int:conversation_id>/send', methods=['POST'])
@login_required
def send_admin_web_message(conversation_id):
    """Envoie un message admin à une conversation Web spécifique."""
    try:
        # Vérification Admin
        if not session.get('is_admin'):
            logger.warning("Tentative d'accès non autorisé à l'envoi de message admin Web.")
            return jsonify({'error': 'Unauthorized access'}), 403

        # Récupération du contenu
        data = request.json
        message_content = data.get('message')
        if not message_content or message_content.strip() == '':
            logger.warning("Tentative d'envoi de message admin Web vide.")
            return jsonify({'error': 'Message content is required'}), 400

        # Trouver la conversation Web
        web_conv = Conversation.query.get(conversation_id)
        if not web_conv:
            logger.warning(f"Conversation Web ID {conversation_id} non trouvée.")
            return jsonify({'error': 'Web Conversation not found'}), 404

        # Sauvegarder le message admin dans la DB Web
        new_message = Message(
            conversation_id=web_conv.id,
            role='admin',
            content=message_content,
            created_at=datetime.utcnow()
        )
        db.session.add(new_message)
        db.session.commit()
        logger.info(f"Message admin sauvegardé pour conversation Web ID: {conversation_id}, Message ID: {new_message.id}")

        # Préparer la réponse pour le frontend
        message_data_for_frontend = {
            'id': new_message.id,
            'role': 'admin',
            'content': message_content,
            'created_at': new_message.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
        return jsonify({
            'success': True,
            'message': 'Web admin message saved',
            'message_data': message_data_for_frontend
        })

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Erreur lors de l'envoi/sauvegarde message admin Web pour conversation {conversation_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500


@admin_bp.route('/conversations/<int:conversation_id>', methods=['DELETE'])
def delete_conversation_by_id(conversation_id):
    """Delete a Web or Telegram conversation by its DATABASE ID"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        conversation_deleted = False
        deleted_platform = None

        # 1. Essayer de supprimer une conversation Web
        web_conv = Conversation.query.get(conversation_id)
        if web_conv:
            logger.info(f"Tentative de suppression de la conversation Web ID: {conversation_id}")
            Message.query.filter_by(conversation_id=web_conv.id).delete()
            db.session.delete(web_conv)
            db.session.commit()
            conversation_deleted = True
            deleted_platform = 'web'
            logger.info(f"Conversation Web ID: {conversation_id} supprimée avec succès.")

        # 2. Si non trouvée/supprimée, essayer de supprimer une conversation Telegram
        if not conversation_deleted:
            tg_conv = TelegramConversation.query.get(conversation_id)
            if tg_conv:
                logger.info(f"Tentative de suppression de la conversation Telegram ID: {conversation_id}")
                TelegramMessage.query.filter_by(conversation_id=tg_conv.id).delete()
                db.session.delete(tg_conv)
                db.session.commit()
                conversation_deleted = True
                deleted_platform = 'telegram'
                logger.info(f"Conversation Telegram ID: {conversation_id} supprimée avec succès.")

        # 3. Renvoyer le résultat
        if conversation_deleted:
            return jsonify({'success': True, 'message': f'Conversation ({deleted_platform}) deleted successfully'})
        else:
            logger.warning(f"Échec de la suppression : Conversation (Web ou Telegram) avec ID {conversation_id} non trouvée.")
            return jsonify({'success': False, 'message': 'Conversation not found by ID'}), 404

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting conversation by ID {conversation_id}: {e}")
        return jsonify({'success': False, 'message': 'Error deleting conversation', 'error': str(e)}), 500


@admin_bp.route('/conversations/<int:conversation_id>/messages')
def get_conversation_messages(conversation_id):
    """Get messages for a specific Web or Telegram conversation by its DATABASE ID"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        messages_data = []
        platform_type = None

        # 1. Check regular Web conversations
        web_conv = Conversation.query.get(conversation_id)
        if web_conv:
            platform_type = 'web'
            messages = Message.query.filter_by(conversation_id=web_conv.id)\
                .order_by(Message.created_at).all()
            messages_data = [{
                'role': msg.role,
                'content': msg.content,
                'image_url': msg.image_url,
                'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
            } for msg in messages]
            logger.info(f"Messages trouvés pour la conversation Web ID: {conversation_id}")

        # 2. If not found, check Telegram conversations
        else:
            tg_conv = TelegramConversation.query.get(conversation_id)
            if tg_conv:
                platform_type = 'telegram'
                messages = TelegramMessage.query.filter_by(conversation_id=tg_conv.id)\
                    .order_by(TelegramMessage.created_at).all()
                messages_data = [{
                    'role': getattr(msg, 'role', 'unknown'),
                    'content': getattr(msg, 'content', ''),
                    'image_url': getattr(msg, 'image_url', None),
                    'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
                } for msg in messages]
                logger.info(f"Messages trouvés pour la conversation Telegram ID: {conversation_id}")

        # 3. Return messages or 404 if not found in Web or Telegram
        if platform_type:
            return jsonify({'messages': messages_data, 'platform': platform_type})
        else:
            logger.warning(f"Conversation (Web ou Telegram) avec ID {conversation_id} non trouvée via /admin/conversations/<id>/messages.")
            return jsonify({'error': 'Conversation not found by ID'}), 404

    except Exception as e:
        logger.exception(f"Error fetching Web/Telegram conversation messages by ID {conversation_id}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/whatsapp/thread/<path:thread_id>/messages')
def get_whatsapp_thread_messages(thread_id):
    """Get messages for a specific WhatsApp thread"""
    from whatsapp_bot import WhatsAppMessage  # Import local

    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        logger.debug(f"Fetching WhatsApp messages for thread: {thread_id}")

        whatsapp_messages = WhatsAppMessage.query.filter_by(thread_id=thread_id)\
            .order_by(WhatsAppMessage.timestamp).all()

        if whatsapp_messages:
            return jsonify({
                'messages': [{
                    'role': 'user' if msg.direction == 'inbound' else 'assistant',
                    'content': msg.content,
                    'created_at': msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                } for msg in whatsapp_messages]
            })

        return jsonify({'error': 'No WhatsApp messages found for this thread'}), 404

    except Exception as e:
        logger.error(f"Error fetching WhatsApp thread messages: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/whatsapp/thread/<path:thread_id>', methods=['DELETE'])
def delete_whatsapp_thread(thread_id):
    """Delete all messages associated with a WhatsApp thread_id"""
    from whatsapp_bot import WhatsAppMessage  # Import local

    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 403

        logger.info(f"Tentative de suppression de la conversation WhatsApp thread: {thread_id}")

        message_count = WhatsAppMessage.query.filter_by(thread_id=thread_id).count()

        if message_count > 0:
            WhatsAppMessage.query.filter_by(thread_id=thread_id).delete()
            db.session.commit()
            logger.info(f"Conversation WhatsApp thread {thread_id} ({message_count} messages) supprimée avec succès.")
            return jsonify({'success': True, 'message': 'WhatsApp conversation deleted successfully'})
        else:
            logger.warning(f"Échec de la suppression : Aucune conversation WhatsApp trouvée pour le thread {thread_id}.")
            return jsonify({'success': False, 'message': 'WhatsApp conversation (thread) not found'}), 404

    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting WhatsApp thread {thread_id}: {e}")
        return jsonify({'success': False, 'message': 'Error deleting WhatsApp conversation', 'error': str(e)}), 500


@admin_bp.route('/data/<platform>')
def admin_platform_data(platform):
    """Get data required ONLY for the main dashboard view"""
    from whatsapp_bot import WhatsAppMessage  # Import local en haut de la fonction

    today_date = date.today()
    tomorrow_date = today_date + timedelta(days=1)
    data = {'platform': platform}
    RECENT_LIMIT = 5

    try:
        # Calcul des Statistiques
        if platform == 'web':
            active_users_count = db.session.query(func.count(User.id)).scalar() or 0
            today_users_count = db.session.query(func.count(User.id))\
                .filter(User.created_at >= today_date, User.created_at < tomorrow_date).scalar() or 0
            today_conversations_count = db.session.query(func.count(Conversation.id))\
                .filter(Conversation.created_at >= today_date, Conversation.created_at < tomorrow_date).scalar() or 0
            total_feedbacks = db.session.query(func.count(MessageFeedback.id)).scalar() or 0
            positive_feedbacks = db.session.query(func.count(MessageFeedback.id))\
                .filter(MessageFeedback.feedback_type == 'positive').scalar() or 0
            satisfaction_rate = round((positive_feedbacks / total_feedbacks) * 100) if total_feedbacks > 0 else 0

            data.update({
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': satisfaction_rate
            })

        elif platform == 'telegram':
            active_users_count = db.session.query(func.count(TelegramUser.telegram_id)).scalar() or 0
            today_users_count = db.session.query(func.count(TelegramUser.telegram_id))\
                .filter(TelegramUser.created_at >= today_date, TelegramUser.created_at < tomorrow_date).scalar() or 0
            today_conversations_count = db.session.query(func.count(TelegramConversation.id))\
                .filter(TelegramConversation.created_at >= today_date, TelegramConversation.created_at < tomorrow_date).scalar() or 0

            data.update({
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': 0
            })

        elif platform == 'whatsapp':
            active_users_count = db.session.query(func.count(func.distinct(WhatsAppMessage.from_number)))\
                .filter(WhatsAppMessage.direction == 'inbound').scalar() or 0
            today_users_count = db.session.query(func.count(func.distinct(WhatsAppMessage.from_number)))\
                .filter(
                    WhatsAppMessage.direction == 'inbound',
                    WhatsAppMessage.timestamp >= today_date,
                    WhatsAppMessage.timestamp < tomorrow_date
                ).scalar() or 0
            subquery = db.session.query(
                WhatsAppMessage.thread_id,
                func.min(WhatsAppMessage.timestamp).label('first_message_time')
            ).group_by(WhatsAppMessage.thread_id).subquery()
            today_conversations_count = db.session.query(func.count(subquery.c.thread_id))\
                .filter(subquery.c.first_message_time >= today_date, subquery.c.first_message_time < tomorrow_date)\
                .scalar() or 0

            data.update({
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': 0
            })
        else:
            return jsonify({"error": "Platform not supported"}), 404

        # Récupération des Utilisateurs Récents (LIMIT 5)
        recent_users = []
        if platform == 'web':
            recent_users_query = User.query.order_by(User.created_at.desc()).limit(RECENT_LIMIT).all()
            recent_users = [{
                'first_name': user.first_name, 'last_name': user.last_name,
                'phone_number': user.phone_number, 'age': user.age,
                'study_level': user.study_level,
                'created_at': user.created_at.strftime('%d/%m/%Y')
            } for user in recent_users_query]
        elif platform == 'telegram':
            recent_users_query = TelegramUser.query.order_by(TelegramUser.created_at.desc()).limit(RECENT_LIMIT).all()
            recent_users = [{
                'telegram_id': user.telegram_id, 'first_name': user.first_name or "---",
                'last_name': user.last_name or "---", 'phone': user.phone_number,
                'study_level': user.study_level,
                'created_at': user.created_at.strftime('%d/%m/%Y')
            } for user in recent_users_query]
        elif platform == 'whatsapp':
            recent_user_numbers = db.session.query(WhatsAppMessage.from_number)\
                .filter(WhatsAppMessage.direction == 'inbound')\
                .distinct().limit(RECENT_LIMIT).all()
            recent_users = []
            for user_num_tuple in recent_user_numbers:
                user_num = user_num_tuple[0]
                first_msg = WhatsAppMessage.query.filter_by(from_number=user_num).order_by(WhatsAppMessage.timestamp).first()
                recent_users.append({
                    'name': f'WhatsApp User {user_num}', 'phone': user_num,
                    'study_level': 'N/A',
                    'created_at': first_msg.timestamp.strftime('%d/%m/%Y') if first_msg else 'N/A'
                })

        # Récupération des Conversations Récentes (LIMIT 5) + Last Message (Optimisé)
        recent_conversations = []
        latest_msgs_dict = {}

        if platform == 'web':
            recent_conversations_query = Conversation.query.order_by(Conversation.created_at.desc()).limit(RECENT_LIMIT).all()
            if recent_conversations_query:
                recent_conv_ids = [c.id for c in recent_conversations_query]
                subq = db.session.query(
                    Message.conversation_id, Message.content,
                    func.row_number().over(
                        partition_by=Message.conversation_id,
                        order_by=desc(Message.created_at)
                    ).label('rn')
                ).filter(Message.conversation_id.in_(recent_conv_ids)).subquery()
                latest_msgs_q = db.session.query(subq.c.conversation_id, subq.c.content).filter(subq.c.rn == 1)
                latest_msgs_dict = dict(latest_msgs_q.all())

            recent_conversations = [{
                'id': conv.id,
                'title': conv.title or "Sans titre",
                'date': conv.created_at.strftime('%d/%m/%Y'),
                'time': conv.created_at.strftime('%H:%M'),
                'last_message': latest_msgs_dict.get(conv.id, "No messages")
            } for conv in recent_conversations_query]

        elif platform == 'telegram':
            recent_conversations_query = TelegramConversation.query.order_by(TelegramConversation.created_at.desc()).limit(RECENT_LIMIT).all()
            if recent_conversations_query:
                recent_conv_ids = [c.id for c in recent_conversations_query]
                subq = db.session.query(
                    TelegramMessage.conversation_id, TelegramMessage.content,
                    func.row_number().over(
                        partition_by=TelegramMessage.conversation_id,
                        order_by=desc(TelegramMessage.created_at)
                    ).label('rn')
                ).filter(TelegramMessage.conversation_id.in_(recent_conv_ids)).subquery()
                latest_msgs_q = db.session.query(subq.c.conversation_id, subq.c.content).filter(subq.c.rn == 1)
                latest_msgs_dict = dict(latest_msgs_q.all())

            recent_conversations = [{
                'id': conv.id,
                'title': conv.title,
                'date': conv.created_at.strftime('%d/%m/%Y'),
                'time': conv.created_at.strftime('%H:%M'),
                'last_message': latest_msgs_dict.get(conv.id, "No messages")
            } for conv in recent_conversations_query]

        elif platform == 'whatsapp':
            subq_last_msg_time = db.session.query(
                WhatsAppMessage.thread_id,
                func.max(WhatsAppMessage.timestamp).label('last_msg_time')
            ).group_by(WhatsAppMessage.thread_id).subquery()

            recent_threads_q = db.session.query(subq_last_msg_time.c.thread_id, subq_last_msg_time.c.last_msg_time)\
                .order_by(desc(subq_last_msg_time.c.last_msg_time))\
                .limit(RECENT_LIMIT)

            recent_conversations_data = recent_threads_q.all()
            if recent_conversations_data:
                recent_thread_ids = [c[0] for c in recent_conversations_data]
                subq_msg = db.session.query(
                    WhatsAppMessage.thread_id, WhatsAppMessage.content,
                    func.row_number().over(
                        partition_by=WhatsAppMessage.thread_id,
                        order_by=desc(WhatsAppMessage.timestamp)
                    ).label('rn')
                ).filter(WhatsAppMessage.thread_id.in_(recent_thread_ids)).subquery()
                latest_msgs_q = db.session.query(subq_msg.c.thread_id, subq_msg.c.content).filter(subq_msg.c.rn == 1)
                latest_msgs_dict = dict(latest_msgs_q.all())

                recent_conversations = [{
                    'id': thread_id,
                    'title': f"Conversation {thread_id}",
                    'date': last_time.strftime('%d/%m/%Y'),
                    'time': last_time.strftime('%H:%M'),
                    'last_message': latest_msgs_dict.get(thread_id, "No messages")
                } for thread_id, last_time in recent_conversations_data]

        data['users'] = recent_users
        data['conversations'] = recent_conversations

        return jsonify(data)

    except Exception as e:
        logger.error(f"Error fetching dashboard data for platform {platform}: {e}")
        return jsonify({"error": "Failed to retrieve dashboard data"}), 500


@admin_bp.route('/users/<platform>')
def admin_platform_users(platform):
    """Get a paginated list of users for a specific platform, with filtering and search."""
    from whatsapp_bot import WhatsAppMessage  # Import local en haut

    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status_filter = request.args.get('status', None, type=str)
        search_term = request.args.get('search', None, type=str)

        users_data = []
        pagination_data = {}
        base_query = None
        user_model = None
        last_active_column = None

        activity_threshold = datetime.utcnow() - timedelta(seconds=900)

        if platform == 'web':
            user_model = User
            base_query = User.query
            last_active_column = User.last_active
            search_fields = [User.first_name, User.last_name, User.phone_number]
        elif platform == 'telegram':
            user_model = TelegramUser
            base_query = TelegramUser.query
            last_active_column = TelegramUser.last_active
            search_fields = [TelegramUser.first_name, TelegramUser.last_name, TelegramUser.phone_number, TelegramUser.telegram_id.cast(db.String)]
        elif platform == 'whatsapp':
            base_query = db.session.query(WhatsAppMessage.from_number).filter(
                WhatsAppMessage.direction == 'inbound'
            ).distinct()
            if search_term:
                base_query = base_query.filter(WhatsAppMessage.from_number.ilike(f'%{search_term}%'))
            base_query = base_query.order_by(WhatsAppMessage.from_number)
        else:
            return jsonify({"error": "Platform not supported"}), 404

        if platform in ['web', 'telegram']:
            if status_filter == 'active':
                if last_active_column is not None:
                    base_query = base_query.filter(last_active_column != None, last_active_column >= activity_threshold)
                else:
                    logger.warning(f"Impossible d'appliquer le filtre 'active' car la colonne last_active n'est pas définie pour {platform}")
            elif status_filter == 'inactive':
                if last_active_column is not None:
                    base_query = base_query.filter(or_(last_active_column == None, last_active_column < activity_threshold))
                else:
                    logger.warning(f"Impossible d'appliquer le filtre 'inactive' car la colonne last_active n'est pas définie pour {platform}")

            if search_term:
                search_conditions = [field.ilike(f'%{search_term}%') for field in search_fields]
                base_query = base_query.filter(or_(*search_conditions))

            base_query = base_query.order_by(desc(user_model.created_at))

        pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)

        if platform == 'web':
            users_on_page = pagination.items
            users_data = []
            for user in users_on_page:
                is_active = user.last_active is not None and user.last_active >= activity_threshold
                users_data.append({
                    'id': user.id,
                    'first_name': user.first_name, 'last_name': user.last_name,
                    'phone_number': user.phone_number, 'age': user.age,
                    'study_level': user.study_level,
                    'created_at': user.created_at.strftime('%d/%m/%Y'),
                    'active': is_active
                })

        elif platform == 'telegram':
            users_on_page = pagination.items
            users_data = []
            for user in users_on_page:
                is_active = user.last_active is not None and user.last_active >= activity_threshold
                users_data.append({
                    'id': user.telegram_id,
                    'telegram_id': user.telegram_id,
                    'first_name': user.first_name or "---", 'last_name': user.last_name or "---",
                    'phone': user.phone_number, 'study_level': user.study_level,
                    'created_at': user.created_at.strftime('%d/%m/%Y'),
                    'active': is_active
                })

        elif platform == 'whatsapp':
            numbers_on_page = [item[0] for item in pagination.items]
            first_message_times = {}
            last_message_times = {}
            if numbers_on_page:
                first_msg_subq = db.session.query(
                    WhatsAppMessage.from_number, func.min(WhatsAppMessage.timestamp).label('first_ts')
                ).filter(
                    WhatsAppMessage.from_number.in_(numbers_on_page),
                    WhatsAppMessage.direction == 'inbound'
                ).group_by(WhatsAppMessage.from_number).subquery()
                first_message_times = dict(db.session.query(first_msg_subq.c.from_number, first_msg_subq.c.first_ts).all())

                last_msg_subq = db.session.query(
                    WhatsAppMessage.from_number, func.max(WhatsAppMessage.timestamp).label('last_ts')
                ).filter(
                    WhatsAppMessage.from_number.in_(numbers_on_page),
                    WhatsAppMessage.direction == 'inbound'
                ).group_by(WhatsAppMessage.from_number).subquery()
                last_message_times = dict(db.session.query(last_msg_subq.c.from_number, last_msg_subq.c.last_ts).all())

            users_data = []
            for num in numbers_on_page:
                first_ts = first_message_times.get(num)
                last_ts = last_message_times.get(num)
                is_active = last_ts is not None and last_ts >= activity_threshold
                if status_filter is None or (status_filter == 'active' and is_active) or (status_filter == 'inactive' and not is_active):
                    users_data.append({
                        'id': num, 'name': f'WhatsApp User {num}', 'phone': num,
                        'study_level': 'N/A',
                        'created_at': first_ts.strftime('%d/%m/%Y') if first_ts else 'N/A',
                        'active': is_active
                    })

        pagination_data = {
            'total_items': pagination.total, 'total_pages': pagination.pages,
            'current_page': pagination.page, 'per_page': pagination.per_page,
            'has_next': pagination.has_next, 'has_prev': pagination.has_prev,
            'next_page_num': pagination.next_num, 'prev_page_num': pagination.prev_num
        }

        return jsonify({'users': users_data, 'pagination': pagination_data})

    except Exception as e:
        logger.exception(f"Error fetching users for platform {platform}: {e}")
        return jsonify({"error": "Failed to retrieve users"}), 500


@admin_bp.route('/conversations/<platform>')
def admin_platform_conversations(platform):
    """Get a paginated list of conversations for a specific platform, with filtering and search."""
    from whatsapp_bot import WhatsAppMessage  # Import local en haut

    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status_filter = request.args.get('filter', None, type=str)
        search_term = request.args.get('search', None, type=str)

        conversations_on_page_data = []
        pagination_data = {}
        base_query = None
        conv_model = None
        message_model = None
        conv_id_col = None
        msg_conv_fk_col = None
        msg_created_at_col = None
        search_fields = []

        activity_threshold = datetime.utcnow() - timedelta(seconds=900)

        if platform == 'web':
            conv_model = Conversation
            message_model = Message
            conv_id_col = Conversation.id
            msg_conv_fk_col = Message.conversation_id
            msg_created_at_col = Message.created_at
            search_fields = [Conversation.title]
            base_query = db.session.query(conv_model)
        elif platform == 'telegram':
            conv_model = TelegramConversation
            message_model = TelegramMessage
            conv_id_col = TelegramConversation.id
            msg_conv_fk_col = TelegramMessage.conversation_id
            msg_created_at_col = TelegramMessage.created_at
            search_fields = [TelegramConversation.title]
            base_query = db.session.query(conv_model)
        elif platform == 'whatsapp':
            last_msg_subq = db.session.query(
                WhatsAppMessage.thread_id,
                func.max(WhatsAppMessage.timestamp).label('last_msg_time')
            ).group_by(WhatsAppMessage.thread_id).subquery()
            base_query = db.session.query(
                last_msg_subq.c.thread_id, last_msg_subq.c.last_msg_time
            )
            if search_term:
                base_query = base_query.filter(last_msg_subq.c.thread_id.ilike(f'%{search_term}%'))
            conv_model = None
        else:
            return jsonify({"error": "Platform not supported"}), 404

        if platform in ['web', 'telegram']:
            if search_term and search_fields:
                search_conditions = [field.ilike(f'%{search_term}%') for field in search_fields]
                if search_conditions:
                    base_query = base_query.filter(or_(*search_conditions))

        if platform in ['web', 'telegram']:
            last_message_subquery = db.session.query(
                msg_conv_fk_col,
                func.max(msg_created_at_col).label('last_message_time')
            ).group_by(msg_conv_fk_col).subquery()

            base_query = base_query.join(
                last_message_subquery, conv_id_col == last_message_subquery.c.conversation_id
            )

            if status_filter == 'active':
                base_query = base_query.filter(last_message_subquery.c.last_message_time >= activity_threshold)
            elif status_filter == 'archived':
                base_query = base_query.filter(last_message_subquery.c.last_message_time < activity_threshold)

            base_query = base_query.add_columns(last_message_subquery.c.last_message_time)\
                                 .order_by(desc(last_message_subquery.c.last_message_time))

        elif platform == 'whatsapp':
            if status_filter == 'active':
                base_query = base_query.filter(last_msg_subq.c.last_msg_time >= activity_threshold)
            elif status_filter == 'archived':
                base_query = base_query.filter(last_msg_subq.c.last_msg_time < activity_threshold)

            base_query = base_query.order_by(desc(last_msg_subq.c.last_msg_time))

        pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)

        latest_msgs_dict = {}
        conversations_on_page_data = []

        if platform in ['web', 'telegram']:
            conversations_processed = []
            last_message_times_dict = {}
            conv_ids_on_page = []

            for item in pagination.items:
                conv_object = item[0]
                last_message_time = item[1]
                conversations_processed.append(conv_object)
                conv_id = conv_object.id
                conv_ids_on_page.append(conv_id)
                last_message_times_dict[conv_id] = last_message_time

            if conv_ids_on_page:
                subq_msg_content = db.session.query(
                    msg_conv_fk_col, message_model.content,
                    func.row_number().over(partition_by=msg_conv_fk_col, order_by=desc(msg_created_at_col)).label('rn')
                ).filter(msg_conv_fk_col.in_(conv_ids_on_page)).subquery()
                latest_msgs_q = db.session.query(subq_msg_content.c.conversation_id, subq_msg_content.c.content).filter(subq_msg_content.c.rn == 1)
                latest_msgs_dict = dict(latest_msgs_q.all())

            for conv in conversations_processed:
                last_msg_ts = last_message_times_dict.get(conv.id)
                is_active = last_msg_ts is not None and last_msg_ts >= activity_threshold
                current_status = 'active' if is_active else 'archived'
                conv_title = getattr(conv, 'title', None) or (f"Conversation {conv.id}" if platform == 'telegram' else "Sans titre")
                conv_created_at = getattr(conv, 'created_at', datetime.min)

                conversations_on_page_data.append({
                    'id': conv.id,
                    'title': conv_title,
                    'date': conv_created_at.strftime('%d/%m/%Y'),
                    'time': conv_created_at.strftime('%H:%M'),
                    'last_message': latest_msgs_dict.get(conv.id, "No messages"),
                    'status': current_status
                })

        elif platform == 'whatsapp':
            threads_on_page = pagination.items
            thread_ids_on_page = [item[0] for item in threads_on_page]
            last_message_times_dict = dict(threads_on_page)

            if thread_ids_on_page:
                subq_msg = db.session.query(
                    WhatsAppMessage.thread_id, WhatsAppMessage.content,
                    func.row_number().over(partition_by=WhatsAppMessage.thread_id, order_by=desc(WhatsAppMessage.timestamp)).label('rn')
                ).filter(WhatsAppMessage.thread_id.in_(thread_ids_on_page)).subquery()
                latest_msgs_q = db.session.query(subq_msg.c.thread_id, subq_msg.c.content).filter(subq_msg.c.rn == 1)
                latest_msgs_dict = dict(latest_msgs_q.all())

            for thread_id, last_time in threads_on_page:
                is_active = last_time is not None and last_time >= activity_threshold
                current_status = 'active' if is_active else 'archived'

                conversations_on_page_data.append({
                    'id': thread_id,
                    'title': f"Conversation {thread_id}",
                    'date': last_time.strftime('%d/%m/%Y') if last_time else 'N/A',
                    'time': last_time.strftime('%H:%M') if last_time else 'N/A',
                    'last_message': latest_msgs_dict.get(thread_id, "No messages"),
                    'status': current_status
                })

        pagination_data = {
            'total_items': pagination.total, 'total_pages': pagination.pages,
            'current_page': pagination.page, 'per_page': pagination.per_page,
            'has_next': pagination.has_next, 'has_prev': pagination.has_prev,
            'next_page_num': pagination.next_num, 'prev_page_num': pagination.prev_num
        }

        return jsonify({'conversations': conversations_on_page_data, 'pagination': pagination_data})

    except Exception as e:
        logger.exception(f"Error fetching conversations for platform {platform}: {e}")
        return jsonify({"error": "Failed to retrieve conversations"}), 500


@admin_bp.route('/data/<platform>/stats')
def admin_platform_stats(platform):
    """Get only stats for a platform without full data lists, calculated efficiently."""
    from whatsapp_bot import WhatsAppMessage  # Import local en haut

    today = datetime.today().date()
    data = {}

    try:
        if platform == 'web':
            active_users_count = db.session.query(func.count(User.id)).scalar() or 0
            today_users_count = db.session.query(func.count(User.id))\
                .filter(User.created_at >= today, User.created_at < today + timedelta(days=1)).scalar() or 0
            today_conversations_count = db.session.query(func.count(Conversation.id))\
                .filter(Conversation.created_at >= today, Conversation.created_at < today + timedelta(days=1)).scalar() or 0

            total_feedbacks = db.session.query(func.count(MessageFeedback.id)).scalar() or 0
            positive_feedbacks = db.session.query(func.count(MessageFeedback.id))\
                .filter(MessageFeedback.feedback_type == 'positive').scalar() or 0
            satisfaction_rate = round((positive_feedbacks / total_feedbacks) * 100) if total_feedbacks > 0 else 0

            data = {
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': satisfaction_rate
            }

        elif platform == 'telegram':
            active_users_count = db.session.query(func.count(TelegramUser.telegram_id)).scalar() or 0
            today_users_count = db.session.query(func.count(TelegramUser.telegram_id))\
                .filter(TelegramUser.created_at >= today, TelegramUser.created_at < today + timedelta(days=1)).scalar() or 0
            today_conversations_count = db.session.query(func.count(TelegramConversation.id))\
                .filter(TelegramConversation.created_at >= today, TelegramConversation.created_at < today + timedelta(days=1)).scalar() or 0

            data = {
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': 0
            }

        elif platform == 'whatsapp':
            active_users_count = db.session.query(func.count(func.distinct(WhatsAppMessage.from_number)))\
                .filter(WhatsAppMessage.direction == 'inbound').scalar() or 0
            today_users_count = db.session.query(func.count(func.distinct(WhatsAppMessage.from_number)))\
                .filter(
                    WhatsAppMessage.direction == 'inbound',
                    WhatsAppMessage.timestamp >= today,
                    WhatsAppMessage.timestamp < today + timedelta(days=1)
                ).scalar() or 0

            subquery = db.session.query(
                WhatsAppMessage.thread_id,
                func.min(WhatsAppMessage.timestamp).label('first_message_time')
            ).group_by(WhatsAppMessage.thread_id).subquery()

            today_conversations_count = db.session.query(func.count(subquery.c.thread_id))\
                .filter(subquery.c.first_message_time >= today, subquery.c.first_message_time < today + timedelta(days=1))\
                .scalar() or 0

            data = {
                'active_users': active_users_count,
                'active_users_today': today_users_count,
                'today_conversations': today_conversations_count,
                'satisfaction_rate': 0
            }
        else:
            return jsonify({"error": "Platform not supported"}), 404

        return jsonify(data)

    except Exception as e:
        logger.error(f"Error fetching stats for platform {platform}: {e}")
        return jsonify({"error": "Failed to retrieve statistics"}), 500