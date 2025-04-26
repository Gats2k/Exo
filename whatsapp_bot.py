import os
import hmac
import hashlib
import logging
import requests
import time
from flask import Blueprint, request, jsonify
from datetime import datetime
from database import db
from openai import OpenAI, BadRequestError, APIError
from mathpix_utils import process_image_with_mathpix
from sqlalchemy import Index, desc, BigInteger, Text
import sys
from threading import Lock
from collections import defaultdict

_thread_locks = defaultdict(Lock)
_dict_lock = Lock()

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
    """Generate response using the configured AI model with non-blocking lock check and robust fallback"""
    response = None
    thread_lock = None # Initialiser
    acquired = False # Pour savoir si on doit release

    # --- Obtenir le verrou spécifique à ce thread_id ---
    with _dict_lock:
        thread_lock = _thread_locks[thread_id] # Récupère ou crée le Lock pour ce thread

    logger.debug(f"Thread {thread_id}: Tentative d'acquisition NON-BLOQUANTE du verrou...")
    # --- Tenter d'acquérir le verrou SANS attendre ---
    acquired = thread_lock.acquire(blocking=False)

    if acquired:
        logger.debug(f"Thread {thread_id}: Verrou acquis (non-bloquant). Début du traitement.")
        try:
            # Récupérer la configuration actuelle
            config = get_app_config()
            current_model_key = config.get('CURRENT_MODEL', 'deepseek') # Le modèle configuré
            effective_model_key = current_model_key # Le modèle qu'on va réellement utiliser
            logger.info(f"Thread {thread_id}: Modèle configuré: {current_model_key}")

            # --- Logique OpenAI Assistant ---
            if current_model_key == 'openai':
                try:
                    logger.info(f"Thread {thread_id}: Tentative avec OpenAI.")
                    client.beta.threads.messages.list(thread_id=thread_id, limit=1) # Test validité
                    logger.info(f"Thread {thread_id}: Thread OpenAI valide.")

                    # 1. AJOUTER LE MESSAGE
                    logger.debug(f"Thread {thread_id}: Ajout du message...")
                    client.beta.threads.messages.create(
                        thread_id=thread_id, role="user", content=message_body
                    )
                    logger.debug(f"Thread {thread_id}: Message ajouté.")

                    # 2. CRÉER ET EXÉCUTER LA RUN
                    logger.debug(f"Thread {thread_id}: Création de la run...")
                    run = client.beta.threads.runs.create(
                        thread_id=thread_id, assistant_id=ASSISTANT_ID
                    )
                    logger.debug(f"Thread {thread_id}: Run {run.id} créée.")

                    # 3. ATTENDRE LA FIN DE LA RUN
                    timeout = 60; start_time = time.time()
                    logger.debug(f"Thread {thread_id}: Attente de la fin de la run {run.id}...")
                    while True:
                        if time.time() - start_time > timeout:
                            logger.error(f"Thread {thread_id}: Timeout attente run {run.id}")
                            raise TimeoutError("OpenAI response generation timed out") # L'erreur sera catchée plus bas

                        run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                        if run_status.status == 'completed':
                            logger.info(f"Thread {thread_id}: Run {run.id} terminée.")
                            break
                        elif run_status.status in ['failed', 'cancelled', 'expired']:
                            logger.error(f"Thread {thread_id}: Run {run.id} échouée: {run_status.status}")
                            raise Exception(f"OpenAI Run failed: {run_status.status}") # L'erreur sera catchée plus bas
                        time.sleep(1)

                    # 4. RÉCUPÉRER LA RÉPONSE
                    logger.debug(f"Thread {thread_id}: Récupération des messages...")
                    messages = client.beta.threads.messages.list(thread_id=thread_id, order='desc', limit=1)
                    if messages.data and messages.data[0].role == 'assistant':
                        # Succès OpenAI ! On définit la réponse.
                        response = messages.data[0].content[0].text.value
                        logger.info(f"Thread {thread_id}: Réponse OpenAI reçue.")
                    else:
                        logger.error(f"Thread {thread_id}: Impossible de récupérer message assistant valide après run complétée.")
                        # Pas de réponse valide, on laisse response = None pour déclencher fallback

                # --- Gestion unifiée des erreurs OpenAI ---
                except Exception as openai_error:
                    # On logue l'erreur mais on ne définit PAS response ici.
                    # On laisse response = None pour que le fallback s'exécute.
                    logger.error(f"Thread {thread_id}: Erreur OpenAI: {str(openai_error)}. Basculement vers fallback.")

            # --- Logique Fallback / Autres modèles (s'exécute si response est encore None) ---
            if response is None:
                # Si on est ici, soit current_model n'était pas 'openai', soit la tentative OpenAI a échoué.
                logger.info(f"Thread {thread_id}: Utilisation modèle Chat Completion: {effective_model_key}")
                try:
                    # Récupérer les fonctions/clients pour le modèle *effectif*
                    # Note: adapter get_ai_client etc. si vous avez forcé effective_model_key
                    ai_client = config['get_ai_client']() # Ou config['get_ai_client'](effective_model_key) ?
                    model = config['get_model_name']()   # Ou config['get_model_name'](effective_model_key) ?
                    if model is None: # Assigner un fallback si le nom du modèle est None
                        # (Votre logique de fallback pour le nom de modèle ici...)
                         if effective_model_key == 'deepseek': model = "deepseek-chat"
                         elif effective_model_key == 'deepseek-reasoner': model = "deepseek-reasoner"
                         elif effective_model_key == 'qwen': model = "qwen-max-latest"
                         elif effective_model_key == 'gemini': model = "gemini-pro"
                         else: model = "deepseek-chat" # Fallback ultime
                         logger.warning(f"Thread {thread_id}: Model name was None for {effective_model_key}, using fallback: {model}")


                    # --- Récupération de l'historique (identique à Code 1) ---
                    get_system_instructions = config['get_system_instructions']() # Idem, potentiellement passer effective_model_key
                    previous_messages = []
                    message_limit = getattr(sys.modules.get('app', None), 'CONTEXT_MESSAGE_LIMIT', 50)
                    messages_query = WhatsAppMessage.query.filter_by(
                        thread_id=thread_id
                    ).order_by(WhatsAppMessage.timestamp.desc()).limit(message_limit).all()

                    for msg in reversed(messages_query):
                        role = 'user' if msg.direction == 'inbound' else 'assistant'
                        previous_messages.append({"role": role, "content": msg.content})

                    system_instructions = get_system_instructions
                    if system_instructions:
                        previous_messages.insert(0, {"role": "system", "content": system_instructions})

                    if not previous_messages or previous_messages[-1].get("content") != message_body or previous_messages[-1].get("role") != "user":
                        already_present = any(p.get("content") == message_body and p.get("role") == "user" for p in previous_messages)
                        if not already_present:
                            logger.debug("Ajout explicite du message utilisateur courant à l'historique pour l'API.")
                            previous_messages.append({"role": "user", "content": message_body})

                    messages_history = previous_messages

                    # --- Ajout : Vérification et correction pour deepseek-reasoner
                    if model == 'deepseek-reasoner' and len(messages_history) > 1:
                        first_message_index = 0
                        if messages_history[0]['role'] == 'system':
                            first_message_index = 1

                        if len(messages_history) > first_message_index and messages_history[first_message_index]['role'] == 'assistant':
                            logger.warning(f"Thread {thread_id}: Premier message après system pour deepseek-reasoner est 'assistant'. Tentative de correction.")

                            # Trouver l'index du premier message 'user' après le message système
                            first_user_msg_index = -1
                            for i in range(first_message_index, len(messages_history)):
                                if messages_history[i]['role'] == 'user':
                                    first_user_msg_index = i
                                    break

                            if first_user_msg_index != -1 and first_user_msg_index > first_message_index:
                                # Supprimer les messages 'assistant' initiaux (entre system et premier user)
                                messages_to_remove = first_user_msg_index - first_message_index
                                del messages_history[first_message_index:first_user_msg_index]
                                logger.info(f"Thread {thread_id}: Supprimé {messages_to_remove} message(s) 'assistant' initiaux. Nouvelle longueur historique: {len(messages_history)}")
                            elif first_user_msg_index == -1:
                                logger.error(f"Thread {thread_id}: Aucun message 'user' trouvé après le message 'assistant' initial pour deepseek-reasoner. L'historique pourrait être invalide.")

                    # --- Ajout Correction 2: Fusionner les messages consécutifs (UNIQUEMENT pour deepseek-reasoner) ---
                    if model == 'deepseek-reasoner' and len(messages_history) > 1:
                        logger.info(f"Thread {thread_id}: Vérification/Fusion des messages consécutifs pour deepseek-reasoner.")
                        merged_messages_list = []
                        if messages_history:
                            # Commencer avec le premier message (system ou le premier valide)
                            merged_messages_list.append(messages_history[0])

                            # Itérer à partir du deuxième message
                            for i in range(1, len(messages_history)):
                                current_message = messages_history[i]
                                last_merged_message = merged_messages_list[-1]

                                # Vérifier si les rôles sont identiques ET ne sont pas 'system'
                                if current_message['role'] == last_merged_message['role'] and current_message['role'] != 'system':
                                    # Fusionner le contenu avec deux sauts de ligne entre les messages
                                    merged_content = f"{last_merged_message['content']}\n\n{current_message['content']}"
                                    # Mettre à jour le contenu du dernier message dans la liste fusionnée
                                    merged_messages_list[-1]['content'] = merged_content
                                    logger.debug(f"Thread {thread_id}: Fusionné message {i} (role: {current_message['role']}) avec le précédent.")
                                else:
                                    # Rôles différents ou message système, ajouter simplement le message courant
                                    merged_messages_list.append(current_message)

                        # Utiliser la liste potentiellement fusionnée pour l'appel API
                        final_messages_for_api = merged_messages_list
                        logger.info(f"Thread {thread_id}: Historique après fusion pour reasoner: {len(final_messages_for_api)} messages.")

                    # Appel API Chat Completion
                    logger.info(f"Thread {thread_id}: Appel API Chat Completion avec modèle: {model} pour {effective_model_key} ({len(messages_history)} messages)")
                    completion = ai_client.chat.completions.create(
                        model=model,
                        messages=final_messages_for_api, # Envoi de l'historique potentiellement corrigé
                        stream=False
                    )
                    response = completion.choices[0].message.content # Définir la réponse ici
                    logger.info(f"Thread {thread_id}: Réponse Chat Completion/Fallback reçue.")

                except Exception as alt_error:
                    logger.error(f"Thread {thread_id}: Erreur modèle fallback {effective_model_key} -> {str(alt_error)}")
                    # L'erreur s'est produite PENDANT le fallback, définir une réponse d'erreur générique
                    response = "Désolé, une erreur technique est survenue lors de la génération de la réponse."

        # --- Gestion d'erreur globale PENDANT que le verrou est détenu ---
        except Exception as e:
            logger.error(f"Thread {thread_id}: Erreur GLOABLE dans generate_ai_response (sous verrou) -> {str(e)}")
            if response is None: # Si aucune réponse n'a été définie même après fallback
                response = "Une erreur interne majeure est survenue. Veuillez réessayer."

        # --- LIBÉRER LE VERROU IMPÉRATIVEMENT ---
        finally:
            if acquired:
                thread_lock.release()
                logger.debug(f"Thread {thread_id}: Verrou libéré.")

    else:
        # --- LE VERROU N'A PAS ÉTÉ ACQUIS (déjà pris) ---
        logger.info(f"Thread {thread_id}: Verrou déjà détenu. Envoi du message 'Molo molo'.")
        response = "⛔⛔⛔Molo molo 😅 je ne peux recevoir qu'un message à la fois. Attends que je réponde à ton premier message avant d'envoyer un autre.⛔⛔⛔"

    # --- Retour de la fonction ---
    if response is None:
        # Sécurité finale si aucune réponse n'a été assignée
        logger.error(f"Thread {thread_id}: La réponse finale est None après toutes les tentatives.")
        return "Je rencontre des difficultés techniques pour répondre. Veuillez réessayer plus tard."

    return response

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