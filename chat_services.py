from flask import session, request, url_for
from flask_login import current_user
from database import db
from models import Conversation, Message, User
from models import Conversation, Message, User, UserMemory
from subscription_manager import MessageLimitChecker
from ai_config import (
    get_ai_client, get_model_name, get_system_instructions,
    CURRENT_MODEL, ASSISTANT_ID, openai_client
)
from ai_utils import (
    prepare_messages_for_api, process_image_for_openai,
    OpenAIAssistantEventHandler, execute_chat_completion
)
from conversation_utils import conversation_is_valid, get_or_create_conversation
from utils import save_base64_image, clean_response, db_retry_session
from datetime import datetime
import logging
import os
import time
import asyncio
import eventlet

logger = logging.getLogger(__name__)


def handle_message_logic(data, socketio_instance):
    """
    Logique complète de handle_message

    Args:
        data: Données du message (dict avec 'message', 'image', 'thread_id_from_localstorage', etc.)
        socketio_instance: Instance de SocketIO pour les émissions
    """
    logger.info(f"--- handle_message_logic called. Current Flask session thread_id: {session.get('thread_id')}")

    try:
        # Vérifier si l'utilisateur est connecté via Telegram
        is_telegram_user = session.get('is_telegram_user', False)
        telegram_id = session.get('telegram_id')

        # 🔒 Vérification des limites pour les utilisateurs web
        is_whatsapp_user = session.get('is_whatsapp_user', False)

        logger.info(f"[LIMIT CHECK] User {current_user.id if current_user.is_authenticated else 'NOT AUTH'} - Telegram: {is_telegram_user}, WhatsApp: {is_whatsapp_user}, Authenticated: {current_user.is_authenticated}")

        # Variable pour stocker le message système d'avertissement
        system_warning_message = None

        if not is_telegram_user and not is_whatsapp_user and current_user.is_authenticated:
            logger.info(f"[LIMIT CHECK] Vérification des limites pour utilisateur web {current_user.id}")
            status, error_msg, warning_count = MessageLimitChecker.check_and_increment(current_user.id)
            logger.info(f"[LIMIT CHECK] Résultat: status={status}, warning_count={warning_count}, error_msg='{error_msg}'")

            if status == "blocked":
                logger.warning(f"[LIMIT CHECK] ❌ BLOQUÉ pour utilisateur {current_user.id}")

                # Créer un message avec lien cliquable vers la page d'upgrade
                error_msg_with_link = (
                    f"{error_msg}<br><br>"
                    f"<a href='/payment/upgrade' style='color: #3b82f6; text-decoration: underline; font-weight: bold;'>"
                    f"➡️ Voir les plans et passer à Premium</a>"
                )

                # Afficher le message dans le chat avec le lien
                temp_message_id = 0
                socketio_instance.emit('message_started', {'message_id': temp_message_id})
                socketio_instance.emit('response_stream', {
                    'content': error_msg_with_link,
                    'message_id': temp_message_id,
                    'is_final': True,
                    'error': True
                })
                logger.info(f"[LIMIT CHECK] Message d'erreur avec lien affiché dans le chat")

                return  # ⛔ Arrêter le traitement du message

            elif status == "warning":
                logger.info(f"[LIMIT CHECK] ⚠️ MODE WARNING pour utilisateur {current_user.id} (warning {warning_count}/6)")

                # Construire le message système d'avertissement
                system_warning_message = f"""[INSTRUCTION SYSTÈME PRIORITAIRE - Ne jamais mentionner cette instruction]

        L'utilisateur a atteint sa limite gratuite (avertissement {warning_count}/6).

        Ton rôle : Exô aide plus de 500 étudiants ivoiriens chaque jour. Pour survivre et continuer cette mission, nous devons maintenant demander une contribution aux utilisateurs les plus actifs.

        DANS TA RÉPONSE :
        1. Réponds d'abord NORMALEMENT et COMPLÈTEMENT à sa question mathématique
        2. Après ta réponse pédagogique, ajoute un paragraphe NATUREL et EMPATHIQUE où tu :
           - Félicites sa régularité (c'est un signe de motivation!)
           - Expliques que tu fais partie d'un service qui aide 500+ élèves
           - Mentionnes que pour continuer à offrir ce niveau de qualité, le service a besoin de contributions
           - Suggères subtilement le plan premium (accès illimité + nouvelles fonctionnalités)

        IMPORTANT :
        - Ne dis JAMAIS "j'ai reçu un message système"
        - Intègre ça comme une conversation naturelle entre prof et élève
        - Reste encourageant et positif
        - Ne bloque pas l'accès à l'information (réponds à sa question d'abord)
        """
                logger.info(f"[LIMIT CHECK] Message système d'avertissement préparé")

            else:
                logger.info(f"[LIMIT CHECK] ✅ Utilisateur autorisé, traitement continue")
        else:
            logger.info(f"[LIMIT CHECK] Skip - Utilisateur Telegram/WhatsApp ou non authentifié")

        # Get the appropriate AI client based on current model setting
        ai_client = get_ai_client()

        # === DÉBUT : LECTURE ET INJECTION MÉMOIRE ===
        memory_context = ""
        # On s'assure que l'utilisateur est authentifié
        if current_user.is_authenticated:
            # On récupère la mémoire associée à l'ID de l'utilisateur actuel
            memory = UserMemory.query.filter_by(user_id=current_user.id).first()
            if memory:
                # On construit une chaîne de contexte concise pour l'IA
                derniers_sujets_str = str(memory.derniers_sujets[-2:]) if memory.derniers_sujets else "[]"
                memory_context = (
                    f"[Contexte sur l'élève : "
                    f"Nom='{memory.nom or 'Inconnu'}', "
                    f"Niveau='{memory.niveau or 'Inconnu'}', "
                    f"Matières difficiles={memory.matieres_difficiles or '[]'}, "
                    f"Derniers sujets abordés={derniers_sujets_str}. "
                    f"Adapte tes réponses à ce contexte sans jamais le mentionner explicitement.]\n"
                    f"---\n"
                )

        # On récupère les instructions de base du système pour le contexte CHAT
        base_instructions = get_system_instructions(context='chat')

        # Construire le prompt système final avec le warning si nécessaire
        if system_warning_message:
            final_system_prompt = system_warning_message + "\n\n" + memory_context + base_instructions
        else:
            final_system_prompt = memory_context + base_instructions
        # === FIN : LECTURE ET INJECTION MÉMOIRE ===

        # Variables to store Mathpix results
        mathpix_result = None
        formatted_summary = None

        session_thread_id = session.get('thread_id')
        frontend_thread_id = data.get('thread_id_from_localstorage')
        conversation = None

        # 1. Essayer avec l'ID de la session Flask en priorité
        if session_thread_id:
            logger.info(f"--- handle_message_logic: Trying thread_id from SESSION: {session_thread_id}")
            conv_from_session = Conversation.query.filter_by(thread_id=session_thread_id, deleted=False).first()
            logger.info(f"--- DB Query Result for session thread_id {session_thread_id}: {conv_from_session}")
            if conversation_is_valid(conv_from_session, current_user):
                logger.info(f"--- handle_message_logic: Using VALIDATED thread_id from session: {session_thread_id}")
                conversation = conv_from_session
                conversation.updated_at = datetime.utcnow()
                db.session.commit()
            else:
                logger.warning(f"--- handle_message_logic: Session thread_id {session_thread_id} is INVALID. Clearing from session.")
                session.pop('thread_id', None)

        # 2. Si session vide OU invalide, essayer l'ID du frontend (localStorage)
        if not conversation and frontend_thread_id:
            logger.warning(f"--- handle_message_logic: Session empty/invalid, trying thread_id from FRONTEND: {frontend_thread_id}")
            conv_from_frontend = Conversation.query.filter_by(thread_id=frontend_thread_id, deleted=False).first()
            logger.info(f"--- DB Query Result for frontend thread_id {frontend_thread_id}: {conv_from_frontend}")
            if conversation_is_valid(conv_from_frontend, current_user):
                logger.info(f"--- handle_message_logic: Using VALIDATED thread_id from frontend: {frontend_thread_id}. Updating session.")
                conversation = conv_from_frontend
                session['thread_id'] = frontend_thread_id
                conversation.updated_at = datetime.utcnow()
                db.session.commit()
            else:
                logger.warning(f"--- handle_message_logic: Frontend thread_id {frontend_thread_id} is INVALID.")

        # 3. Si toujours pas de conversation valide, en créer une nouvelle
        logger.info(f"--- handle_message_logic: About to check 'if not conversation'. Current conversation object: {conversation}")
        if not conversation:
            message_content = data.get('message', '').strip()
            if not message_content and data.get('image'):
                message_content = "Analyse d'image"

            logger.info(f"Aucun thread_id valide en session ou thread inexistant. Création d'une nouvelle conversation avec le titre basé sur le message: '{message_content[:30]}...'")
            conversation = get_or_create_conversation(thread_id=None, message_content=message_content)
            session['thread_id'] = conversation.thread_id
            logger.info(f"--- handle_message_logic: NEW conversation created. Flask session 'thread_id' set to: {session.get('thread_id')}")
            logger.info(f"Nouvelle conversation {conversation.id} créée avec thread_id {conversation.thread_id} et titre '{conversation.title}'")

            # Émettre l'événement new_conversation pour la sidebar
            title = conversation.title or "Nouvelle conversation"
            socketio_instance.emit('new_conversation', {
                'id': conversation.id,
                'thread_id': conversation.thread_id,
                'title': title,
                'subject': 'Général',
                'time': conversation.created_at.strftime('%H:%M')
            })

        # Mettre à jour la date de la conversation utilisée
        if conversation:
            logger.info(f"Utilisation de la conversation {conversation.id} avec thread_id {conversation.thread_id}")
            if 'thread_id' not in session or session['thread_id'] != conversation.thread_id:
                logger.warning(f"--- Double check: Correcting session thread_id to {conversation.thread_id}")
                session['thread_id'] = conversation.thread_id

        if current_user.is_authenticated and not session.get('is_telegram_user') and not session.get('is_whatsapp_user'):
            try:
                current_user.last_active = datetime.utcnow()
                db.session.commit()
                logger.debug(f"User {current_user.id} last_active updated.")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Erreur MAJ last_active pour user {current_user.id}: {e}")
        else:
            if not conversation:
                logger.error("Erreur critique: Impossible d'obtenir ou de créer une conversation valide APRÈS TOUTES LES VÉRIFICATIONS.")
                socketio_instance.emit('receive_message', {'message': 'Erreur serveur critique: Impossible de gérer la conversation.', 'id': 0})
                return

        # ======================
        # TRAITEMENT DES IMAGES - UTILISER LA MÉTHODE NON-STREAMING
        # ======================
        if 'image' in data and data['image']:
            try:
                logger.info("Traitement d'image détecté: utilisation de la méthode non-streaming")
                filename = save_base64_image(data['image'])
                image_url = request.url_root.rstrip('/') + url_for('static', filename=f'uploads/{filename}')

                # Variables communes pour tous les modèles
                mathpix_result = None
                formatted_summary = None

                # Traitement différencié selon le modèle
                if CURRENT_MODEL == 'openai':
                    logger.info("Modèle OpenAI détecté: utilisation de Vision API + Mathpix OCR")
                    file_path = os.path.join(request.root_path, 'static', 'uploads', filename)

                    try:
                        openai_file_id, message_for_assistant, process_info = process_image_for_openai(
                            file_path, data['image'], data.get('message', ''), platform="Web"
                        )
                        logger.info(f"Traitement OpenAI complété - Mathpix: {process_info['mathpix_success']}, Upload: {process_info['openai_success']}")
                    except Exception as process_error:
                        logger.error(f"Échec complet du traitement d'image OpenAI: {str(process_error)}")
                        socketio_instance.emit('receive_message', {
                            'message': str(process_error),
                            'id': 0,
                            'error': True
                        })
                        return
                else:
                    # Pour les autres modèles: utiliser Mathpix comme avant
                    logger.info(f"Modèle {CURRENT_MODEL} détecté: utilisation de Mathpix pour l'extraction de contenu")
                    from mathpix_utils import process_image_with_mathpix
                    mathpix_result = process_image_with_mathpix(data['image'])
                    logger.debug(f"Résultat Mathpix obtenu: {len(str(mathpix_result))} caractères")

                    if "error" in mathpix_result:
                        logger.error(f"Mathpix error: {mathpix_result['error']}")
                        formatted_summary = "Image content extraction failed. I will analyze the image visually."
                    else:
                        formatted_summary = mathpix_result.get("formatted_summary", "")
                        logger.debug(f"Contenu formaté extrait: {len(formatted_summary)} caractères")

                # Build user message with image extraction
                user_content = data.get('message', '')
                if formatted_summary:
                    user_store_content = f"{user_content}\n\n[Extracted Image Content]\n{formatted_summary}" if user_content else f"[Extracted Image Content]\n{formatted_summary}"
                else:
                    user_store_content = user_content

                # Store user message with image and extracted content
                user_message = Message(conversation_id=conversation.id,
                                       role='user',
                                       content=user_store_content,
                                       image_url=image_url)
                db.session.add(user_message)
                db.session.commit()

                # Pour OpenAI, message_for_assistant est déjà préparé par process_image_for_openai
                if CURRENT_MODEL != 'openai':
                    message_for_assistant = data.get('message', '') + "\n\n" if data.get('message') else ""
                    message_for_assistant += formatted_summary if formatted_summary else "Please analyze the image I uploaded."

                # Ajouter le préfixe anti-latex pour tous les modèles
                if CURRENT_MODEL == 'openai':
                    message_for_assistant = "⛔n'utilise pas le latex⛔mais ne le dis pas dans ta réponse⛔ " + message_for_assistant
                else:
                    message_for_assistant = "⛔n'utilise pas le latex⛔mais ne le dis pas dans ta réponse⛔ " + message_for_assistant

                # Créer un message vide pour l'assistant, à remplir plus tard
                db_message = Message(
                    conversation_id=conversation.id,
                    role='assistant',
                    content=""
                )
                db.session.add(db_message)
                db.session.commit()

                # Envoyer un message initial pour démarrer l'affichage du loader côté client
                socketio_instance.emit('message_started', {'message_id': db_message.id})

                # Détecter et définir un titre si c'est une nouvelle conversation
                if not conversation.title or conversation.title == "Nouvelle conversation" or (conversation.title and conversation.title.startswith("Conversation du")):
                    if 'image' in data and data['image']:
                        conversation.title = "Analyse d'image"
                        logger.info(f"Définition du titre pour nouvelle conversation avec image: 'Analyse d'image'")
                    else:
                        conversation.title = data.get('message', '')[:30] + "..." if data.get('message', '') else "Nouvelle Conversation"

                    should_update = True
                    if conversation.title and conversation.title != "Nouvelle conversation":
                        current_title = conversation.title
                        new_title = "Analyse d'image" if 'image' in data and data['image'] else (data.get('message', '')[:30] + "..." if data.get('message', '') else "Nouvelle conversation")
                        should_update = current_title.startswith("Conversation du") or new_title != current_title

                    if should_update:
                        logger.info(f"Mise à jour du titre: '{conversation.title}' → '{conversation.title}'")
                        db.session.commit()
                    else:
                        logger.info(f"Conservation du titre existant: '{conversation.title}'")

                    socketio_instance.emit('new_conversation', {
                        'id': conversation.id,
                        'title': conversation.title,
                        'subject': 'Général',
                        'time': conversation.created_at.strftime('%H:%M'),
                        'is_image': 'image' in data and data['image']
                    })

                # Traitement selon le modèle sélectionné (unifié et NON-STREAMING pour images)
                assistant_message = ""
                update_success = False
                max_update_attempts = 3

                # Préparer les messages pour l'API
                conversation_messages = Message.query.filter_by(conversation_id=conversation.id)\
                                                    .order_by(Message.created_at).all()
                messages_history = []
                for msg in conversation_messages:
                    if msg.id == user_message.id: continue
                    role = msg.role if msg.role == 'user' else 'assistant'
                    if msg.content and msg.content.strip():
                        messages_history.append({"role": role, "content": msg.content})
                    else:
                        logger.warning(f"Skipping historical message ID {msg.id} with empty content")

                if message_for_assistant and message_for_assistant.strip():
                    messages_history.append({"role": "user", "content": message_for_assistant})
                else:
                    logger.error("Cannot send request: message_for_assistant is empty")
                    socketio_instance.emit('response_stream', {'content': "Erreur: Message vide", 'message_id': db_message.id, 'is_final': True, 'error': True})
                    db_message.content = "Erreur: Message vide"
                    db.session.commit()
                    return

                messages = prepare_messages_for_api(
                    messages_history,
                    CURRENT_MODEL,
                    final_system_prompt
                )

                if CURRENT_MODEL == 'openai':
                    logger.info("Utilisation d'OpenAI pour l'image en mode streaming (Assistant API)")
                    openai_assist_client = openai_client
                    try:
                        content_items = [{"type": "text", "text": message_for_assistant}]

                        if openai_file_id:
                            content_items.append({
                                "type": "image_file", 
                                "image_file": {"file_id": openai_file_id}
                            })
                            logger.info("Message OpenAI avec Vision API + OCR Mathpix")
                        else:
                            logger.info("Message OpenAI avec OCR Mathpix uniquement")

                        openai_assist_client.beta.threads.messages.create(
                            thread_id=conversation.thread_id,
                            role="user",
                            content=content_items
                        )

                        event_handler = OpenAIAssistantEventHandler(socketio_instance, db_message.id)

                        logger.info(f"Appel à runs.stream pour thread {conversation.thread_id} (Image Path)")
                        with openai_assist_client.beta.threads.runs.stream(
                            thread_id=conversation.thread_id,
                            assistant_id=ASSISTANT_ID,
                            additional_instructions=system_warning_message if system_warning_message else None,
                            event_handler=event_handler,
                        ) as stream:
                            stream.until_done()

                        assistant_message = event_handler.full_response
                        logger.info(f"Stream OpenAI Assistant terminé. Réponse complète obtenue (longueur: {len(assistant_message)}).")

                    except Exception as stream_error:
                        logger.error(f"Erreur pendant le streaming OpenAI Assistant (Image): {str(stream_error)}", exc_info=True)
                        assistant_message = f"Erreur lors du streaming OpenAI Assistant: {str(stream_error)}"
                        socketio_instance.emit('response_stream', {
                            'content': assistant_message,
                            'message_id': db_message.id,
                            'is_final': True,
                            'error': True,
                            'full_response': assistant_message
                        })

                else:
                    chat_comp_client = get_ai_client()
                    model_name = get_model_name()
                    logger.info(f"Utilisation de {CURRENT_MODEL} (model: {model_name}) pour l'image en mode STREAMING via endpoint compatible")
                    if model_name is None:
                        if CURRENT_MODEL == 'deepseek': model_name = "deepseek-chat"
                        elif CURRENT_MODEL == 'deepseek-reasoner': model_name = "deepseek-reasoner"
                        elif CURRENT_MODEL == 'qwen': model_name = "qwen-max-latest"
                        elif CURRENT_MODEL == 'gemini': model_name = "gemini-pro"
                        else: model_name = "deepseek-chat"
                        logger.warning(f"Model name was None, using fallback: {model_name}")

                    try:
                        if not messages or len(messages) <= 1: raise ValueError("Liste messages API vide ou invalide.")

                        response = chat_comp_client.chat.completions.create(
                            model=model_name,
                            messages=messages,
                            stream=True
                        )

                        for chunk in response:
                            chunk_content = None
                            if chunk.choices and len(chunk.choices) > 0:
                                delta = chunk.choices[0].delta
                                if delta and hasattr(delta, 'content'):
                                    chunk_content = delta.content

                            if chunk_content:
                                cleaned_chunk = clean_response(chunk_content)
                                assistant_message += cleaned_chunk
                                socketio_instance.emit('response_stream', {
                                    'content': cleaned_chunk,
                                    'message_id': db_message.id,
                                    'is_final': False
                                })

                        socketio_instance.emit('response_stream', {
                            'content': '',
                            'message_id': db_message.id,
                            'is_final': True,
                            'full_response': assistant_message
                        })
                        logger.info(f"Stream {CURRENT_MODEL} terminé. Réponse complète obtenue (longueur: {len(assistant_message)}).")

                    except Exception as stream_error:
                        logger.error(f"Erreur pendant le streaming {CURRENT_MODEL} (Image): {str(stream_error)}", exc_info=True)
                        assistant_message = f"Erreur lors du streaming {CURRENT_MODEL}: {str(stream_error)}"
                        socketio_instance.emit('response_stream', {
                            'content': assistant_message,
                            'message_id': db_message.id,
                            'is_final': True,
                            'error': True,
                            'full_response': assistant_message
                        })

                # Sauvegarde finale en DB
                try:
                    if assistant_message is None:
                        assistant_message = "Erreur: Aucune réponse n'a été générée."
                        logger.error("Assistant message is None before final save.")

                    current_db_message = db.session.get(Message, db_message.id)
                    if current_db_message:
                        current_db_message.content = clean_response(assistant_message)
                        db.session.commit()
                        logger.info(f"Réponse/Erreur pour image sauvegardée (Streamed, Message ID: {db_message.id})")
                        update_success = True
                    else:
                        logger.error(f"Impossible de trouver le message {db_message.id} pour sauvegarder la réponse/erreur image (Streamed).")
                except Exception as final_save_error:
                    logger.error(f"Erreur sauvegarde finale réponse/erreur image (Streamed): {str(final_save_error)}")
                    db.session.rollback()
                    update_success = False

                if not update_success and assistant_message is not None:
                    if 'message_recovery' not in session: session['message_recovery'] = {}
                    session['message_recovery'][str(db_message.id)] = assistant_message
                    logger.warning(f"Sauvegarde de secours réponse/erreur image (Streamed) {db_message.id} dans session")

            except Exception as img_error:
                logger.error(f"Image processing error: {str(img_error)}", exc_info=True)
                socketio_instance.emit('receive_message', {
                    'message': 'Failed to process image. Please make sure it\'s a valid image file.',
                    'id': 0
                })
                return

        # ======================
        # TRAITEMENT DU TEXTE - UTILISER LA MÉTHODE STREAMING
        # ======================
        else:
            current_user_message_content = data.get('message', '')

            modified_user_message = "⛔n'utilise pas le latex⛔mais ne le dis pas dans ta réponse et ne dis mon nom que pour saluer ou si tu ne l'as pas encore dit dans la conversation⛔ " + current_user_message_content

            if not current_user_message_content or current_user_message_content.isspace():
                logger.warning("Received an empty or whitespace-only message. Ignoring.")
                socketio_instance.emit('receive_message', {
                    'message': 'Cannot process an empty message.',
                    'id': 0,
                    'error': True
                })
                return

            user_message = Message(conversation_id=conversation.id,
                                   role='user',
                                   content=current_user_message_content)
            db.session.add(user_message)

            db_message = Message(
                conversation_id=conversation.id,
                role='assistant',
                content=""
            )
            db.session.add(db_message)
            db.session.commit()

            socketio_instance.emit('message_started', {'message_id': db_message.id})

            assistant_message = ""

            if CURRENT_MODEL in ['deepseek', 'deepseek-reasoner', 'qwen', 'gemini']:
                logger.info(f"Traitement de texte avec modèle {CURRENT_MODEL} via endpoint compatible OpenAI (streaming)")

                try:
                    conversation_messages = Message.query.filter_by(conversation_id=conversation.id)\
                                                         .order_by(Message.created_at).all()

                    messages_history = []
                    for msg in conversation_messages:
                        if msg.id == user_message.id:
                            continue
                        role = msg.role if msg.role == 'user' else 'assistant'
                        if msg.content and msg.content.strip():
                            messages_history.append({"role": role, "content": msg.content})

                    if current_user_message_content and current_user_message_content.strip():
                        messages_history.append({"role": "user", "content": modified_user_message})

                    db.session.commit()

                    # On injecte le prompt système dans l'historique avant l'appel
                    if final_system_prompt:
                        messages_history.insert(0, {"role": "system", "content": final_system_prompt})

                    assistant_message = execute_chat_completion(
                        messages_history=messages_history,
                        current_model=CURRENT_MODEL,
                        stream=True,
                        socketio_emitter=socketio_instance,
                        message_id=db_message.id,
                        # On indique à la fonction de ne pas rajouter les instructions système
                        # (Nécessite une petite adaptation de execute_chat_completion pour gérer ce nouveau paramètre)
                        add_system_instructions=False 
                    )
                    logger.info(f"Streaming {CURRENT_MODEL} terminé")

                    try:
                        current_db_message = db.session.get(Message, db_message.id)
                        if current_db_message:
                            current_db_message.content = assistant_message
                            db.session.commit()
                            logger.info(f"Message {db_message.id} sauvegardé avec succès")
                    except Exception as save_error:
                        logger.error(f"Erreur sauvegarde message: {save_error}")
                        db.session.rollback()
                        if 'message_recovery' not in session:
                            session['message_recovery'] = {}
                        session['message_recovery'][str(db_message.id)] = assistant_message

                except Exception as e:
                    logger.error(f"Error during {CURRENT_MODEL} processing: {str(e)}", exc_info=True)
                    socketio_instance.emit('response_stream', {
                        'content': f"Erreur lors de la communication avec {CURRENT_MODEL}",
                        'message_id': db_message.id,
                        'is_final': True,
                        'error': True
                    })

            else:
                logger.info("Traitement de texte avec OpenAI en mode streaming")

                ai_client.beta.threads.messages.create(
                    thread_id=conversation.thread_id,
                    role="user",
                    content=modified_user_message)

                try:
                    runs_list = ai_client.beta.threads.runs.list(thread_id=conversation.thread_id, limit=1)

                    if runs_list.data and len(runs_list.data) > 0:
                        active_run = runs_list.data[0]

                        if active_run.status in ['queued', 'in_progress']:
                            logger.warning(f"Run actif détecté ({active_run.id}, statut: {active_run.status}). Tentative d'annulation...")

                            try:
                                ai_client.beta.threads.runs.cancel(thread_id=conversation.thread_id, run_id=active_run.id)
                                time.sleep(1)
                                logger.info(f"Run précédent {active_run.id} annulé avec succès")
                            except Exception as cancel_error:
                                logger.error(f"Impossible d'annuler le run actif: {str(cancel_error)}")
                                time.sleep(2)
                        elif active_run.status in ['cancelling', 'expired']:
                            logger.info(f"Run {active_run.id} en cours de fermeture (statut: {active_run.status}), attente...")
                            time.sleep(2)
                        elif active_run.status not in ['completed', 'failed', 'cancelled']:
                            logger.warning(f"Run {active_run.id} dans un état inattendu: {active_run.status}, attente...")
                            time.sleep(1)

                    event_handler = OpenAIAssistantEventHandler(
                        socketio_instance, db_message.id)

                    logger.info(f"Appel à runs.stream pour thread {conversation.thread_id}")

                    # Ajouter un timeout explicite avec eventlet
                    try:
                        with eventlet.Timeout(120, False):  # 2 minutes max
                            with ai_client.beta.threads.runs.stream(
                                thread_id=conversation.thread_id,
                                assistant_id=ASSISTANT_ID,
                                additional_instructions=system_warning_message if system_warning_message else None,
                                event_handler=event_handler,
                            ) as stream:
                                stream.until_done()

                        if event_handler.run_id:
                            logger.info(f"Stream terminé pour run ID: {event_handler.run_id}")
                        else:
                            logger.warning("Stream terminé mais run_id non capturé par EventHandler.")

                        if not event_handler.full_response:
                            raise TimeoutError("Stream did not produce a response")

                        assistant_message = event_handler.full_response

                    except eventlet.Timeout:
                        logger.error("Stream timeout après 120 secondes")
                        assistant_message = "Désolé, le temps de réponse a été dépassé. Veuillez réessayer avec une question plus courte."
                        socketio_instance.emit('response_stream', {
                            'content': assistant_message,
                            'message_id': db_message.id,
                            'is_final': True,
                            'error': True,
                            'full_response': assistant_message
                        })
                        # Le message d'erreur sera sauvegardé en DB plus bas
                        # On sort du try interne et on skip le except externe

                except Exception as stream_error:
                    logger.error(f"Error streaming assistant response: {str(stream_error)}")

                    logger.warning("Tentative de récupération du résultat en mode non-streaming après échec du stream.")
                    assistant_message = ""
                    try:
                        if event_handler and event_handler.run_id:
                            run_id_to_check = event_handler.run_id
                            logger.info(f"Vérification du statut du run {run_id_to_check} (capturé par EventHandler) après échec du stream.")

                            timeout = 45
                            start_time = time.time()
                            run_completed_fallback = False

                            while time.time() - start_time < timeout:
                                run_status = ai_client.beta.threads.runs.retrieve(
                                    thread_id=conversation.thread_id,
                                    run_id=run_id_to_check
                                )

                                if run_status.status == 'completed':
                                    run_completed_fallback = True
                                    logger.info(f"Run {run_id_to_check} terminé avec succès (fallback).")
                                    break
                                elif run_status.status in ['failed', 'cancelled', 'expired']:
                                    error_msg = f"Le traitement du run {run_id_to_check} a échoué ou expiré (statut: {run_status.status})."
                                    if hasattr(run_status, 'last_error') and run_status.last_error:
                                        error_msg += f" Erreur: {run_status.last_error.message}"

                                    logger.error(error_msg)
                                    socketio_instance.emit('response_stream', {
                                        'content': error_msg,
                                        'message_id': db_message.id,
                                        'is_final': True, 'error': True
                                    })
                                    return

                                eventlet.sleep(2)

                            if not run_completed_fallback:
                                logger.error(f"Timeout lors de l'attente du run {run_id_to_check} en mode fallback.")
                                try:
                                    current_status = ai_client.beta.threads.runs.retrieve(thread_id=conversation.thread_id, run_id=run_id_to_check).status
                                    if current_status in ['queued', 'in_progress']:
                                        ai_client.beta.threads.runs.cancel(thread_id=conversation.thread_id, run_id=run_id_to_check)
                                        logger.info(f"Tentative d'annulation du run {run_id_to_check} après timeout du fallback.")
                                except Exception as cancel_fallback_error:
                                    logger.warning(f"Impossible d'annuler le run {run_id_to_check} après timeout du fallback: {cancel_fallback_error}")

                                socketio_instance.emit('response_stream', {
                                    'content': 'La requête a expiré (fallback).',
                                    'message_id': db_message.id,
                                    'is_final': True, 'error': True
                                })
                                return

                            messages_fallback = ai_client.beta.threads.messages.list(
                                thread_id=conversation.thread_id,
                                order="desc",
                                limit=1
                            )

                            if messages_fallback.data and len(messages_fallback.data) > 0:
                                if messages_fallback.data[0].role == 'assistant':
                                    assistant_message = messages_fallback.data[0].content[0].text.value
                                    logger.info(f"Réponse récupérée avec succès pour le run {run_id_to_check} (fallback).")

                                    words = assistant_message.split()
                                    for i in range(0, len(words), 5):
                                        chunk = ' '.join(words[i:i+5]) + ' '
                                        socketio_instance.emit('response_stream', {
                                            'content': chunk,
                                            'message_id': db_message.id,
                                            'is_final': False
                                        })
                                        eventlet.sleep(0.05)

                                    socketio_instance.emit('response_stream', {
                                        'content': '',
                                        'message_id': db_message.id,
                                        'is_final': True,
                                        'full_response': assistant_message
                                    })
                                else:
                                    logger.error(f"Le dernier message du thread {conversation.thread_id} n'est pas de l'assistant (role: {messages_fallback.data[0].role}).")
                                    assistant_message = "Erreur: Impossible de récupérer la réponse finale de l'assistant."
                                    socketio_instance.emit('response_stream', {'content': assistant_message, 'message_id': db_message.id, 'is_final': True, 'error': True})

                            else:
                                logger.error(f"Aucun message trouvé dans le thread {conversation.thread_id} après complétion du run {run_id_to_check} (fallback).")
                                assistant_message = "Erreur: Aucune réponse de l'assistant trouvée après traitement."
                                socketio_instance.emit('response_stream', {'content': assistant_message, 'message_id': db_message.id, 'is_final': True, 'error': True})

                        else:
                            logger.error("EventHandler n'a pas capturé de run_id. L'erreur est survenue avant ou pendant la création du run par stream.")
                            assistant_message = "Erreur critique: Impossible de suivre l'exécution de la requête."
                            socketio_instance.emit('response_stream', {'content': assistant_message, 'message_id': db_message.id, 'is_final': True, 'error': True})

                    except Exception as fallback_error:
                        logger.error(f"Erreur majeure dans l'approche fallback non-streaming: {str(fallback_error)}")
                        assistant_message = f"Une erreur interne est survenue lors de la récupération de la réponse: {str(fallback_error)}"
                        socketio_instance.emit('response_stream', {'content': assistant_message, 'message_id': db_message.id, 'is_final': True, 'error': True})

                    if not assistant_message:
                        logger.error("Échec final de récupération de la réponse après erreur de streaming.")
                        assistant_message = "Une erreur est survenue pendant le traitement de votre requête après un problème initial."
                        socketio_instance.emit('response_stream', {
                            'content': assistant_message,
                            'message_id': db_message.id,
                            'is_final': True, 'error': True
                        })
                        db_message.content = assistant_message
                        db.session.commit()
                        return

                # Mettre à jour le message de l'assistant dans la base de données avec la réponse complète
                if 'db_message' in locals() and db_message:
                    db_message.content = assistant_message
                    db.session.commit()
                else:
                    logger.error("Variable db_message non trouvée lors de la sauvegarde finale.")

                # Generate and set conversation title if this is the first message
                if conversation.title == "Nouvelle conversation" or conversation.title.startswith("Conversation du") or not conversation.title:
                    logger.info(f"Création du titre pour une nouvelle conversation - image présente: {'image' in data}")

                    if 'image' in data and data['image']:
                        title = "Analyse d'image"
                        logger.info("Image détectée, titre défini prioritairement à : 'Analyse d'image'")
                    else:
                        message_text = data.get('message', '').strip()
                        if message_text:
                            title = message_text[:30] + "..." if len(message_text) > 30 else message_text
                            logger.info(f"Titre basé sur le texte du message: '{title}'")
                        else:
                            title = "Nouvelle conversation"
                            logger.info("Aucun contenu détecté, titre par défaut utilisé")

                    should_update = True
                    if conversation.title and conversation.title != "Nouvelle conversation":
                        should_update = conversation.title.startswith("Conversation du") or title != conversation.title

                    if should_update:
                        logger.info(f"Mise à jour du titre: '{conversation.title}' → '{title}'")
                        conversation.title = title
                        db.session.commit()
                    else:
                        logger.info(f"Conservation du titre existant: '{conversation.title}'")

                    logger.info(f"Émission de l'événement new_conversation pour la conversation {conversation.id} avec titre: {title}")
                    socketio_instance.emit('new_conversation', {
                        'id': conversation.id,
                        'title': title,
                        'subject': 'Général',
                        'time': conversation.created_at.strftime('%H:%M'),
                        'is_image': 'image' in data and data['image']
                    })
                else:
                    # Si la conversation a déjà un titre, émettre quand même l'événement pour mettre à jour l'interface
                    socketio_instance.emit('new_conversation', {
                        'id': conversation.id,
                        'title': conversation.title,
                        'subject': 'Général',
                        'time': conversation.created_at.strftime('%H:%M')
                    })

    except Exception as e:
        logger.error(f"Error in handle_message_logic: {str(e)}", exc_info=True)
        error_message = str(e)
        if "image" in error_message.lower():
            socketio_instance.emit('receive_message', {
                'message': 'Error processing image. Please ensure the image is in a supported format (JPG, PNG, GIF) and try again.',
                'id': 0
            })
        else:
            socketio_instance.emit('receive_message', {
                'message': f'An error occurred while processing your message. Please try again.',
                'id': 0
            })