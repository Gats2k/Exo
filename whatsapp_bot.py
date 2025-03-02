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
from sqlalchemy import or_

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')

# Create Blueprint for WhatsApp routes
whatsapp = Blueprint('whatsapp', __name__)

# Add WhatsAppUser model after the existing WhatsAppMessage model
class WhatsAppUser(db.Model):
    __tablename__ = 'whatsapp_users'

    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship('WhatsAppMessage', backref='user', lazy=True,
                               primaryjoin="or_(WhatsAppUser.phone_number==WhatsAppMessage.from_number, "
                                          "WhatsAppUser.phone_number==WhatsAppMessage.to_number)")

# Update WhatsAppMessage model to include user relationship
class WhatsAppMessage(db.Model):
    __tablename__ = 'whatsapp_messages'

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.String(128), unique=True)
    from_number = db.Column(db.String(20))
    to_number = db.Column(db.String(20))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='received')
    direction = db.Column(db.String(10))  # 'inbound' or 'outbound'
    thread_id = db.Column(db.String(128))  # Store OpenAI thread ID for conversation continuity


def get_or_create_thread(phone_number):
    """Get existing thread or create new one for a phone number"""
    try:
        # Fix the query to use proper SQLAlchemy syntax
        message = WhatsAppMessage.query.filter(
            WhatsAppMessage.from_number == phone_number,
            WhatsAppMessage.thread_id.isnot(None)
        ).order_by(WhatsAppMessage.timestamp.desc()).first()

        if message and message.thread_id:
            logger.info(f"Found existing thread {message.thread_id} for {phone_number}")
            return message.thread_id

        # Create new thread if none exists
        thread = client.beta.threads.create()
        logger.info(f"Created new thread {thread.id} for {phone_number}")
        return thread.id
    except Exception as e:
        logger.error(f"Error in get_or_create_thread: {str(e)}")
        # Create new thread as fallback
        thread = client.beta.threads.create()
        return thread.id

# Ajoute cette fonction pour télécharger l'image
def download_whatsapp_image(image_id):
    """Download image from WhatsApp servers"""
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
            return None

        # Deuxième requête pour télécharger l'image réelle
        image_response = requests.get(data['url'], headers=headers)
        image_response.raise_for_status()

        # Générer un nom de fichier unique
        filename = f"{image_id}_{int(time.time())}.jpg"
        filepath = os.path.join('static/uploads', filename)

        # Sauvegarder l'image
        os.makedirs('static/uploads', exist_ok=True)
        with open(filepath, 'wb') as f:
            f.write(image_response.content)

        # Retourner l'URL locale de l'image
        return request.url_root.rstrip('/') + f"/static/uploads/{filename}"

    except Exception as e:
        logger.error(f"Error downloading WhatsApp image: {e}")
        return None

def generate_ai_response(message_body, thread_id, image_url=None):
    """Generate response using OpenAI assistant with optional image"""
    try:
        logger.info(f"Generating AI response for thread {thread_id}")

        # Prépare le contenu du message
        if image_url:
            # Message avec image + texte optionnel
            content = [
                {
                    "type": "image_url",
                    "image_url": {"url": image_url}
                }
            ]

            # Ajoute le texte si présent
            if message_body:
                content.append({
                    "type": "text",
                    "text": message_body
                })

            # Ajoute le message au thread
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=content
            )
        else:
            # Message texte uniquement
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message_body
            )

        # Run the assistant
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID
        )

        # Wait for response with timeout
        timeout = 30
        start_time = time.time()

        while True:
            if time.time() - start_time > timeout:
                logger.error("OpenAI response generation timed out")
                return "Désolé, la génération de la réponse a pris trop de temps. Veuillez réessayer."

            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )

            logger.debug(f"Run status: {run_status.status}")

            if run_status.status == 'completed':
                break
            elif run_status.status == 'failed':
                logger.error(f"OpenAI run failed for thread {thread_id}")
                return "Désolé, je n'ai pas pu générer une réponse. Veuillez réessayer."

            time.sleep(1)

        # Get the assistant's response
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        response = messages.data[0].content[0].text.value
        logger.info(f"Generated response: {response[:100]}...")  # Log first 100 chars
        return response

    except Exception as e:
        logger.error(f"Error generating AI response: {str(e)}")
        return "Désolé, une erreur s'est produite. Veuillez réessayer plus tard."

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

        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})

                # Handle messages
                for message in value.get('messages', []):
                    sender = message.get('from')
                    message_id = message.get('id')
                    message_type = message.get('type')

                    logger.info(f"Processing {message_type} message from {sender}")

                    try:
                        # Create or update WhatsApp user
                        user = WhatsAppUser.query.filter_by(phone_number=sender).first()
                        if not user:
                            user = WhatsAppUser(phone_number=sender)
                            db.session.add(user)
                        user.last_active = datetime.utcnow()
                        db.session.commit()

                        # Get or create thread for this user
                        thread_id = get_or_create_thread(sender)

                        # Process different message types
                        message_body = None
                        image_url = None

                        if message_type == 'text':
                            message_body = message.get('text', {}).get('body', '')
                            logger.info(f"Text message: {message_body[:100]}...")

                        elif message_type == 'image':
                            # Get image ID
                            image_id = message.get('image', {}).get('id')
                            if image_id:
                                # Download image
                                image_url = download_whatsapp_image(image_id)
                                logger.info(f"Downloaded image to: {image_url}")
                                # Get caption if present
                                message_body = message.get('image', {}).get('caption', '')
                                logger.info(f"Image caption: {message_body}")

                        else:
                            # Unsupported message type
                            logger.info(f"Unsupported message type: {message_type}")
                            send_whatsapp_message(
                                sender, 
                                f"Désolé, les messages de type '{message_type}' ne sont pas encore pris en charge."
                            )
                            continue

                        # Store incoming message
                        message_content = message_body if message_body else ("Image reçue" if image_url else "Message non supporté")
                        new_message = WhatsAppMessage(
                            message_id=message_id,
                            from_number=sender,
                            content=message_content,
                            direction='inbound',
                            thread_id=thread_id
                        )
                        db.session.add(new_message)
                        db.session.commit()

                        # Generate AI response
                        response_text = generate_ai_response(message_body, thread_id, image_url)

                        # Send response via WhatsApp
                        response = send_whatsapp_message(sender, response_text)

                        # Store outbound message
                        if response and 'messages' in response:
                            outbound_msg = WhatsAppMessage(
                                message_id=response['messages'][0]['id'],
                                to_number=sender,
                                content=response_text,
                                direction='outbound',
                                status='sent',
                                thread_id=thread_id
                            )
                            db.session.add(outbound_msg)
                            db.session.commit()
                            logger.info(f"Sent response to {sender}: {response_text[:100]}...")
                    except Exception as e:
                        logger.error(f"Error processing message: {str(e)}")
                        db.session.rollback()

                        # Tenter d'envoyer un message d'erreur à l'utilisateur
                        try:
                            send_whatsapp_message(
                                sender, 
                                "Désolé, une erreur s'est produite lors du traitement de votre message. Veuillez réessayer."
                            )
                        except:
                            logger.error("Failed to send error message to user")
                        continue

                # Handle message statuses
                for status in value.get('statuses', []):
                    try:
                        message_id = status.get('id')
                        status_value = status.get('status')

                        logger.debug(f"Processing status update for message {message_id}: {status_value}")

                        message = WhatsAppMessage.query.filter_by(message_id=message_id).first()
                        if message:
                            message.status = status_value
                            db.session.commit()
                            logger.info(f"Updated status for message {message_id} to {status_value}")
                    except Exception as e:
                        logger.error(f"Error processing status update: {str(e)}")
                        db.session.rollback()
                        continue

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        db.session.rollback()
        return jsonify({"error": "Internal server error"}), 500

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