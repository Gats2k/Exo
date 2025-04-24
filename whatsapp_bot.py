import os
import hmac
import hashlib
import logging
import requests
import time
from flask import Blueprint, request, jsonify
from datetime import datetime
from database import db
from openai import OpenAI
from mathpix_utils import process_image_with_mathpix
from sqlalchemy import Index, desc, BigInteger, Text
import sys

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')

# Create Blueprint for WhatsApp routes
whatsapp = Blueprint('whatsapp', __name__)

# --- Modèle WhatsAppMessage ---
class WhatsAppMessage(db.Model):
     __tablename__ = 'whatsapp_messages'

     # Définition des colonnes EXACTEMENT comme dans la base de données
     id = db.Column(db.Integer, primary_key=True)
     message_id = db.Column(db.String(128), unique=True, nullable=True) # unique=True crée déjà un index
     from_number = db.Column(db.String(20), nullable=True)
     to_number = db.Column(db.String(20), nullable=True)
     content = db.Column(db.Text, nullable=True)
     timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
     status = db.Column(db.String(20), nullable=True) # Statut du message (sent, delivered, etc?)
     direction = db.Column(db.String(10), nullable=True) # 'inbound' ou 'outbound'?
     thread_id = db.Column(db.String(128), nullable=True) # Important pour grouper les conversations

     # Définir les index explicitement avec les noms exacts de \d
     __table_args__ = (
         db.Index('ix_whatsapp_message_from_number_timestamp', 'from_number', 'timestamp'),
         db.Index('ix_whatsapp_message_thread_id_timestamp', 'thread_id', desc('timestamp')), # Ajout de desc()
         # Ajoute d'autres contraintes ou index si nécessaire ici
     )

def get_or_create_thread(phone_number, force_new=False):
    """Get existing thread or create new one for a phone number"""
    try:
        config = get_app_config()
        current_model = config.get('CURRENT_MODEL', 'deepseek')

        logger.info(f"Recherche/création de thread pour {phone_number} avec modèle: {current_model}")

        # Cas simple: si on force un nouveau thread, on le crée et on l'utilise
        if force_new:
            thread_id = None
            # Créer un vrai thread OpenAI seulement si le modèle actuel est OpenAI
            if current_model == 'openai':
                thread = client.beta.threads.create()
                thread_id = thread.id
                logger.info(f"Création forcée d'un nouveau thread OpenAI {thread_id} pour {phone_number}")
            else:
                # Pour les autres modèles, utiliser un format local
                thread_id = f"thread_{phone_number}_{int(time.time())}"
                logger.info(f"Création forcée d'un nouveau thread local {thread_id} pour {phone_number}")

            # Émettre l'événement si c'est un nouvel utilisateur
            try:
                is_new_user = WhatsAppMessage.query.filter_by(from_number=phone_number).count() == 0
                if is_new_user:
                    from app import socketio
                    user_data = {
                        'name': f'WhatsApp User {phone_number}',
                        'phone': phone_number,
                        'platform': 'whatsapp',
                        'created_at': datetime.now().strftime('%d/%m/%Y')
                    }
                    socketio.emit('new_whatsapp_user', user_data)
            except Exception as event_error:
                logger.error(f"Erreur d'émission d'événement: {str(event_error)}")

            return thread_id

        # Chercher le thread existant le plus récent
        message = WhatsAppMessage.query.filter(
            WhatsAppMessage.from_number == phone_number,
            WhatsAppMessage.thread_id.isnot(None)
        ).order_by(WhatsAppMessage.timestamp.desc()).first()

        # Si un thread existe, l'utiliser - sauf cas particuliers
        if message and message.thread_id:
            existing_thread_id = message.thread_id
            is_local_thread = existing_thread_id.startswith("thread_")

            # On ne peut pas se fier uniquement au préfixe "thread_" car les vrais threads OpenAI 
            # commencent également par "thread_". Test: on essaie d'utiliser le thread directement
            if current_model == 'openai':
                try:
                    # Tester si le thread est utilisable avec OpenAI
                    test_response = client.beta.threads.messages.list(thread_id=existing_thread_id, limit=1)
                    # Si on arrive jusqu'ici, le thread est valide
                    logger.info(f"Thread OpenAI existant {existing_thread_id} vérifié avec succès")
                    return existing_thread_id
                except Exception as e:
                    # Le thread n'est pas utilisable avec OpenAI, créer un nouveau thread
                    logger.info(f"Thread {existing_thread_id} non utilisable avec OpenAI ({str(e)}), création d'un nouveau thread")
                    thread = client.beta.threads.create()
                    thread_id = thread.id
                    logger.info(f"Nouveau thread OpenAI créé: {thread_id}")
                    return thread_id

            # Si on a un thread OpenAI et que le modèle est aussi OpenAI, vérifier qu'il existe toujours
            if not is_local_thread and current_model == 'openai':
                try:
                    # Test si le thread OpenAI existe
                    client.beta.threads.messages.list(thread_id=existing_thread_id, limit=1)
                    logger.info(f"Utilisation du thread OpenAI existant {existing_thread_id}")
                    return existing_thread_id
                except Exception as e:
                    logger.warning(f"Thread OpenAI {existing_thread_id} invalide: {str(e)}")
                    # Créer un nouveau thread si celui-ci n'est plus valide
                    thread = client.beta.threads.create()
                    thread_id = thread.id
                    logger.info(f"Création d'un nouveau thread OpenAI {thread_id}")
                    return thread_id

            # Pour tous les autres cas (thread local avec modèle non-OpenAI, etc.)
            logger.info(f"Utilisation du thread existant {existing_thread_id}")
            return existing_thread_id

        # Aucun thread existant, en créer un nouveau
        thread_id = None
        if current_model == 'openai':
            thread = client.beta.threads.create()
            thread_id = thread.id
            logger.info(f"Création d'un nouveau thread OpenAI {thread_id}")
        else:
            thread_id = f"thread_{phone_number}_{int(time.time())}"
            logger.info(f"Création d'un nouveau thread local {thread_id}")

        return thread_id

    except Exception as e:
        logger.error(f"Erreur dans get_or_create_thread: {str(e)}")
        # Thread de secours en cas d'erreur
        fallback_thread_id = f"thread_{phone_number}_{int(time.time())}_fallback"
        return fallback_thread_id

# Fonction modifiée pour également retourner les données en base64 pour Mathpix
def download_whatsapp_image(image_id):
    """Download image from WhatsApp servers and return both URL and base64 data"""
    phone_id = os.environ.get('WHATSAPP_PHONE_ID')
    token = os.environ.get('WHATSAPP_API_TOKEN')

    if not phone_id or not token:
        logger.error("Missing WhatsApp credentials")
        raise ValueError("Missing WhatsApp credentials")

    url = f"https://graph.facebook.com/v17.0/{image_id}"

    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:
        # Première requête pour obtenir l'URL de l'image
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        if 'url' not in data:
            logger.error(f"No URL in image data: {data}")
            return None, None

        # Deuxième requête pour télécharger l'image réelle
        image_response = requests.get(data['url'], headers=headers)
        image_response.raise_for_status()

        # Obtenir le contenu binaire de l'image
        image_content = image_response.content

        # Encoder l'image en base64 pour Mathpix
        import base64
        base64_image = base64.b64encode(image_content).decode('utf-8')
        base64_data = f"data:image/jpeg;base64,{base64_image}"

        # Générer un nom de fichier unique et sauvegarder l'image (facultatif, pour référence)
        filename = f"{image_id}_{int(time.time())}.jpg"
        filepath = os.path.join('static/uploads', filename)

        # Sauvegarder l'image
        os.makedirs('static/uploads', exist_ok=True)
        with open(filepath, 'wb') as f:
            f.write(image_content)

        # Retourner l'URL locale de l'image ET les données base64
        local_url = request.url_root.rstrip('/') + f"/static/uploads/{filename}"
        return local_url, base64_data

    except Exception as e:
        logger.error(f"Error downloading WhatsApp image: {e}")
        return None, None

def generate_ai_response(message_body, thread_id, sender=None):
    """Generate response using the configured AI model"""
    try:
        # Récupérer la configuration actuelle
        config = get_app_config()
        current_model = config.get('CURRENT_MODEL', 'deepseek') # Modèle par défaut sécurisé

        logger.info(f"Generating response using model: {current_model} for thread {thread_id}")

        # --- Début de la logique OpenAI Assistant ---
        # Uniquement si OpenAI est explicitement configuré ET que le thread est valide
        if current_model == 'openai':
            try:
                # Vérifier que le thread n'est pas au format local
                if thread_id.startswith("thread_") and "_" in thread_id[7:]: # Format thread_NUMERO_TIMESTAMP
                    raise ValueError(f"Thread {thread_id} au format local, non compatible avec OpenAI")

                # Tester si le thread est utilisable avec OpenAI avant de continuer
                client.beta.threads.messages.list(thread_id=thread_id, limit=1)
                logger.info(f"Thread OpenAI existant {thread_id} utilisable pour la réponse")

                # Ajouter le message au thread OpenAI existant
                client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=message_body
                )

                # Exécuter l'assistant
                run = client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=ASSISTANT_ID
                )

                # Attendre la réponse avec timeout
                timeout = 60
                start_time = time.time()

                while True:
                    if time.time() - start_time > timeout:
                        logger.error("OpenAI response generation timed out")
                        raise TimeoutError("Response generation timed out")

                    run_status = client.beta.threads.runs.retrieve(
                        thread_id=thread_id,
                        run_id=run.id
                    )

                    if run_status.status == 'completed':
                        break
                    elif run_status.status in ['failed', 'cancelled', 'expired']:
                        logger.error(f"OpenAI run failed with status: {run_status.status}")
                        raise Exception(f"Run failed: {run_status.status}")

                    time.sleep(1)

                # Récupérer la réponse OpenAI
                messages = client.beta.threads.messages.list(thread_id=thread_id)
                response = messages.data[0].content[0].text.value
                return response

            except Exception as openai_error:
                # En cas d'erreur avec OpenAI (thread invalide ou autre), essayer de passer à un autre modèle silencieusement
                logger.error(f"OpenAI error: {str(openai_error)}, switching to fallback model")
                current_model = 'deepseek' # Passer à un modèle de secours
                logger.info(f"Basculé vers modèle de secours: {current_model}")
                # La suite du code gérera le fallback

        # --- Fin de la logique OpenAI Assistant ---


        # --- Logique unifiée pour les modèles compatibles Chat Completion (Gemini, Deepseek, Qwen, et fallback OpenAI) ---
        # Cette partie s'exécute si current_model n'est PAS 'openai' OU si le bloc OpenAI a échoué et basculé

        # Obtenir les fonctions appropriées pour le modèle actuel (qui peut être le fallback)
        get_ai_client = config['get_ai_client']
        get_model_name = config['get_model_name']
        get_system_instructions = config['get_system_instructions']
        # La ligne 'call_gemini_api = config['call_gemini_api']' est supprimée ici aussi

        # Récupérer les messages précédents (la logique reste la même)
        previous_messages = []
        message_limit = getattr(sys.modules.get('app', None), 'CONTEXT_MESSAGE_LIMIT', 50)
        messages_query = WhatsAppMessage.query.filter_by(
            thread_id=thread_id
        ).order_by(WhatsAppMessage.timestamp.desc()).limit(message_limit).all()

        for msg in reversed(messages_query):
            # S'assurer que le rôle est 'user' ou 'assistant' pour l'API Chat Completion
            role = 'user' if msg.direction == 'inbound' else 'assistant'
            previous_messages.append({
                "role": role,
                "content": msg.content
            })

        # Ajouter les instructions système
        system_instructions = get_system_instructions()
        if system_instructions:
            previous_messages.insert(0, {
                "role": "system",
                "content": system_instructions
            })

        # S'assurer que le dernier message est celui de l'utilisateur actuel s'il n'est pas déjà dans l'historique récupéré
        if not previous_messages or previous_messages[-1].get("content") != message_body or previous_messages[-1].get("role") != "user":
             # Vérifier si le message n'est pas déjà le dernier (cas où limit=1 ou conversation très courte)
             already_present = any(p.get("content") == message_body and p.get("role") == "user" for p in previous_messages)
             if not already_present:
                  logger.debug("Ajout explicite du message utilisateur courant à l'historique pour l'API.")
                  previous_messages.append({
                      "role": "user",
                      "content": message_body
                  })

        # Appel API unifié
        ai_client = get_ai_client() # Obtient le client correct (Gemini, Deepseek, Qwen)
        model = get_model_name()    # Obtient le nom de modèle correct

        # Sécurité: Vérifier si le modèle est None et assigner un fallback si nécessaire
        # (basé sur la logique de fallback précédente)
        if model is None:
            if current_model == 'deepseek': model = "deepseek-chat"
            elif current_model == 'deepseek-reasoner': model = "deepseek-reasoner"
            elif current_model == 'qwen': model = "qwen-max-latest"
            elif current_model == 'gemini': model = "gemini-pro" # Ou autre modèle compatible
            else: model = "deepseek-chat" # Fallback ultime
            logger.warning(f"Model name was None for {current_model}, using fallback value: {model}")

        try:
            logger.info(f"Appel API Chat Completion avec modèle: {model} pour {current_model} ({len(previous_messages)} messages)")
            completion = ai_client.chat.completions.create(
                model=model,
                messages=previous_messages,
                stream=False # Le bot WhatsApp n'est pas configuré pour streamer la réponse
            )
            response = completion.choices[0].message.content
            return response
        except Exception as alt_error:
            logger.error(f"Error with model {current_model}: {str(alt_error)}")
            raise # Remonter l'erreur pour qu'elle soit gérée par le bloc externe

    # Gestion globale des erreurs de la fonction
    except Exception as e:
        logger.error(f"Error generating response: {str(e)}")
        # Retourner un message par défaut en cas d'échec complet
        return "Une erreur s'est produite lors de la génération de la réponse, veuillez réessayer."

def send_whatsapp_message(to_number, message):
    """Send a WhatsApp message using the API"""
    phone_id = os.environ.get('WHATSAPP_PHONE_ID')
    token = os.environ.get('WHATSAPP_API_TOKEN')

    if not phone_id or not token:
        logger.error("Missing WhatsApp credentials")
        raise ValueError("Missing WhatsApp credentials")

    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    if not to_number.startswith('+'):
        to_number = '+' + to_number

    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message
        }
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending WhatsApp message: {e}")
        raise

def verify_webhook_signature(request_data, signature_header):
    """Verify the webhook signature from WhatsApp"""
    app_secret = os.environ.get('WHATSAPP_APP_SECRET')

    if not app_secret:
        logger.error("WHATSAPP_APP_SECRET not set")
        return False

    if not signature_header or not signature_header.startswith('sha256='):
        logger.warning(f"Invalid signature format: {signature_header}")
        return False

    try:
        actual_signature = signature_header.replace('sha256=', '')

        expected_signature = hmac.new(
            app_secret.encode('utf-8'),
            request_data,
            hashlib.sha256
        ).hexdigest()

        logger.debug(f"Verifying signatures - Expected: {expected_signature[:10]}... Actual: {actual_signature[:10]}...")

        return hmac.compare_digest(actual_signature, expected_signature)
    except Exception as e:
        logger.error(f"Error verifying signature: {str(e)}")
        return False

@whatsapp.route('/webhook', methods=['GET'])
def verify_webhook():
    """Handle the webhook verification request from WhatsApp"""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    verify_token = os.environ.get('WHATSAPP_VERIFY_TOKEN')

    logger.debug(f"Webhook verification attempt - Mode: {mode}, Token: {token}, Challenge: {challenge}")

    if not verify_token:
        logger.error("WHATSAPP_VERIFY_TOKEN not set")
        return 'Configuration error', 500

    if mode and token:
        if mode == 'subscribe' and token == verify_token:
            if challenge:
                logger.info("Webhook verified successfully")
                return challenge, 200
            return 'No challenge received', 400
        logger.warning("Invalid verification token")
        return 'Forbidden', 403

    logger.warning("Invalid verification request")
    return 'Invalid request', 400

@whatsapp.route('/webhook', methods=['POST'])
def receive_webhook():
    """Handle incoming webhook events from WhatsApp"""
    try:
        signature = request.headers.get('X-Hub-Signature-256', '')
        raw_data = request.get_data()

        logger.debug(f"Received webhook POST with signature: {signature}")

        if not verify_webhook_signature(raw_data, signature):
            logger.warning("Invalid webhook signature")
            return jsonify({"error": "Invalid signature"}), 403

        data = request.get_json()
        logger.debug(f"Webhook payload: {data}")

        if not data or 'entry' not in data:
            logger.warning("Invalid webhook payload format")
            return jsonify({"error": "Invalid payload format"}), 400

        # Récupérer la configuration actuelle au début pour éviter les incohérences
        config = get_app_config()
        current_model = config.get('CURRENT_MODEL', 'deepseek')  # Modèle par défaut sécurisé
        logger.info(f"Processing webhook with active model: {current_model}")

        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})

                # Handle messages
                for message in value.get('messages', []):
                    sender = message.get('from')
                    message_id = message.get('id')
                    message_type = message.get('type')

                    logger.info(f"Processing {message_type} message from {sender}")

                    # Vérifier si le message a déjà été traité pour éviter les doublons
                    try:
                        existing_message = WhatsAppMessage.query.filter_by(message_id=message_id).first()
                        if existing_message:
                            logger.info(f"Message {message_id} already processed. Skipping.")
                            continue
                    except Exception as db_check_error:
                        logger.warning(f"Error checking message existence: {str(db_check_error)}")
                        # Continuer même en cas d'erreur de vérification

                    try:
                        # Récupérer ou créer un thread pour cet utilisateur - sans forcer un nouveau thread
                        max_retries = 3  # Définir cette variable car elle est utilisée ailleurs dans le code
                        thread_id = None
                        try:
                            # Utiliser le thread existant plutôt que d'en créer un nouveau
                            thread_id = get_or_create_thread(sender, force_new=False)
                            if not thread_id:
                                # Uniquement en cas d'échec, créer un thread de secours
                                logger.error(f"Impossible de récupérer un thread pour {sender}")
                                thread_id = f"thread_{sender}_{int(time.time())}_fallback"
                        except Exception as thread_error:
                            logger.error(f"Erreur lors de la récupération du thread: {str(thread_error)}")
                            thread_id = f"thread_{sender}_{int(time.time())}_fallback"

                        # Vérifier si c'est une nouvelle conversation mais sans influer sur la création de thread
                        try:
                            # Vérifier si c'est la première fois qu'on utilise ce thread
                            is_new_conversation = not WhatsAppMessage.query.filter_by(thread_id=thread_id).first()
                            if is_new_conversation:
                                # Émettre l'événement de nouvelle conversation
                                from app import socketio
                                conversation_data = {
                                    'id': thread_id,
                                    'title': f"Conversation WhatsApp",
                                    'thread_id': thread_id,
                                    'user_phone': sender,
                                    'created_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
                                    'platform': 'whatsapp'
                                }
                                socketio.emit('new_whatsapp_conversation', conversation_data)
                                logger.info(f"Émission de l'événement new_whatsapp_conversation pour {thread_id}")
                        except Exception as event_error:
                            logger.error(f"Erreur lors de l'émission de l'événement: {str(event_error)}")
                            # Continuer malgré l'erreur d'émission

                        # Traiter différemment selon le type de message
                        message_body = None

                        if message_type == 'text':
                            message_body = message.get('text', {}).get('body', '')
                            logger.info(f"Text message: {message_body[:100]}...")

                        elif message_type == 'image':
                            # Récupérer l'ID de l'image avec retentatives
                            image_id = message.get('image', {}).get('id')
                            if image_id:
                                # Télécharger l'image avec retentatives
                                image_url = None
                                base64_data = None
                                for attempt in range(max_retries):
                                    try:
                                        image_url, base64_data = download_whatsapp_image(image_id)
                                        if image_url and base64_data:
                                            break
                                    except Exception as img_error:
                                        if attempt == max_retries - 1:
                                            logger.error(f"Failed to download image after {max_retries} attempts")
                                        else:
                                            logger.warning(f"Image download error (attempt {attempt+1}): {str(img_error)}")
                                            time.sleep(1)

                                logger.info(f"Image processing status: URL={bool(image_url)}, base64={bool(base64_data)}")

                                # Récupérer la légende si présente
                                caption = message.get('image', {}).get('caption', '')

                                # Traiter l'image avec Mathpix - avec gestion plus robuste d'erreurs
                                mathpix_result = None
                                formatted_summary = None

                                if base64_data:
                                    try:
                                        mathpix_result = process_image_with_mathpix(base64_data)
                                        if "error" not in mathpix_result:
                                            formatted_summary = mathpix_result.get("formatted_summary", "")
                                    except Exception as mathpix_error:
                                        logger.error(f"Mathpix processing error: {str(mathpix_error)}")
                                        # Continuer sans extraction plutôt que d'échouer complètement

                                # Construire le message pour l'assistant de manière robuste
                                message_for_assistant = ""

                                # Ajouter la légende s'il y en a une
                                if caption:
                                    message_for_assistant += f"{caption}\n\n"

                                # Ajouter les résultats d'extraction Mathpix s'ils existent
                                if formatted_summary:
                                    message_for_assistant += formatted_summary
                                else:
                                    # Message par défaut si pas d'extraction et pas de légende
                                    if not caption:
                                        message_for_assistant = "Please analyze the content I shared."

                                # Définir le message à envoyer à l'IA et à stocker
                                message_body = message_for_assistant

                        else:
                            # Type de message non supporté - ne pas envoyer de message d'erreur à l'utilisateur
                            # mais juste logger l'information et continuer
                            logger.info(f"Unsupported message type: {message_type} - skipping")
                            continue

                        # Si on arrive ici, on a un message_body à traiter
                        if not message_body:
                            logger.warning(f"Empty message body for {message_type} message. Skipping.")
                            continue

                        # Store incoming message dans une transaction indépendante
                        try:
                            new_message = WhatsAppMessage(
                                message_id=message_id,
                                from_number=sender,
                                content=message_body,
                                direction='inbound',
                                thread_id=thread_id
                            )
                            db.session.add(new_message)
                            db.session.commit()
                            logger.info(f"Stored inbound message ID {message_id}")
                        except Exception as db_error:
                            logger.error(f"Database error storing inbound message: {str(db_error)}")
                            db.session.rollback()
                            # Continuer malgré l'erreur de stockage

                        # Generate AI response en respectant strictement le modèle configuré
                        response_text = None
                        for attempt in range(max_retries):
                            try:
                                # Ne jamais connecter à OpenAI sauf si explicitement configuré
                                response_text = generate_ai_response(message_body, thread_id, sender)
                                if response_text:
                                    break
                            except Exception as ai_error:
                                if attempt == max_retries - 1:
                                    logger.error(f"Failed to generate AI response after {max_retries} attempts: {str(ai_error)}")
                                    # Message par défaut courtois comme dernier recours
                                    response_text = "Je suis à votre disposition pour vous aider. Comment puis-je vous être utile aujourd'hui?"
                                else:
                                    logger.warning(f"AI response error (attempt {attempt+1}): {str(ai_error)}")
                                    time.sleep(0.5)  # Pause un peu plus longue pour les erreurs d'IA

                        # Send response via WhatsApp avec retentatives
                        response = None
                        for attempt in range(max_retries):
                            try:
                                response = send_whatsapp_message(sender, response_text)
                                if response and 'messages' in response:
                                    break
                            except Exception as send_error:
                                if attempt == max_retries - 1:
                                    logger.error(f"Failed to send WhatsApp message after {max_retries} attempts: {str(send_error)}")
                                else:
                                    logger.warning(f"Send message error (attempt {attempt+1}): {str(send_error)}")
                                    time.sleep(1.5)

                        # Si l'envoi a échoué malgré les retentatives, continuer silencieusement
                        if not response or 'messages' not in response:
                            logger.error(f"Failed to send response for message {message_id}")
                            continue

                        # Store outbound message dans une transaction indépendante
                        try:
                            # Récupérer le thread_id actuel
                            current_thread_message = WhatsAppMessage.query.filter_by(
                                from_number=sender
                            ).order_by(WhatsAppMessage.timestamp.desc()).first()

                            current_thread_id = thread_id
                            if current_thread_message:
                                current_thread_id = current_thread_message.thread_id

                            outbound_msg = WhatsAppMessage(
                                message_id=response['messages'][0]['id'],
                                to_number=sender,
                                content=response_text,
                                direction='outbound',
                                status='sent',
                                thread_id=current_thread_id
                            )
                            db.session.add(outbound_msg)
                            db.session.commit()
                            logger.info(f"Sent and stored response to {sender}")
                        except Exception as db_error:
                            logger.error(f"Database error storing outbound message: {str(db_error)}")
                            db.session.rollback()
                            # Continuer malgré l'erreur de stockage - le message a déjà été envoyé

                    except Exception as process_error:
                        logger.error(f"Error processing message {message_id}: {str(process_error)}")
                        # Ne pas envoyer de message d'erreur à l'utilisateur et passer au message suivant
                        continue

                # Handle message statuses - traité de manière indépendante des messages
                for status in value.get('statuses', []):
                    try:
                        message_id = status.get('id')
                        status_value = status.get('status')

                        logger.debug(f"Processing status update for message {message_id}: {status_value}")

                        message = WhatsAppMessage.query.filter_by(message_id=message_id).first()
                        if message:
                            message.status = status_value
                            db.session.commit()
                    except Exception as status_error:
                        logger.error(f"Error processing status update: {str(status_error)}")
                        db.session.rollback()
                        continue

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

def get_app_config():
    """
    Récupère dynamiquement les configurations actuelles depuis le fichier de configuration.
    Cela permet de toujours obtenir les dernières valeurs sans redémarrer le bot.
    """
    import json
    import os
    from app import CURRENT_MODEL, get_ai_client, get_model_name, get_system_instructions

    # Utiliser un chemin absolu pour le fichier de configuration
    config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_config.json')

    # Essayer d'abord de lire depuis le fichier de configuration
    try:
        if os.path.exists(config_file_path):
            with open(config_file_path, 'r') as f:
                config_data = json.load(f)

            # Log la configuration trouvée pour débogage
            logger.info(f"Found config in file: model={config_data['CURRENT_MODEL']}, timestamp={config_data.get('timestamp', 0)}")

            # Retourner les configurations depuis le fichier sans vérifier l'âge
            return {
                'CURRENT_MODEL': config_data['CURRENT_MODEL'],
                'get_ai_client': get_ai_client,
                'get_model_name': get_model_name,
                'get_system_instructions': get_system_instructions,
            }
    except Exception as e:
        logger.error(f"Error reading config file ({config_file_path}): {str(e)}")

    # Fallback aux configurations du module app
    logger.info(f"Using config from app module: {CURRENT_MODEL}")
    return {
        'CURRENT_MODEL': CURRENT_MODEL,
        'get_ai_client': get_ai_client,
        'get_model_name': get_model_name,
        'get_system_instructions': get_system_instructions,
    }

def calculate_test_signature(payload):
    """Helper function to calculate webhook signature for testing"""
    app_secret = os.environ.get('WHATSAPP_APP_SECRET')
    if not app_secret:
        return None

    signature = hmac.new(
        app_secret.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"sha256={signature}"