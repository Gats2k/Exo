import os
import hmac
import hashlib
import logging
import requests
from flask import Blueprint, request, jsonify
from datetime import datetime
from database import db
from openai import OpenAI

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')

# Create Blueprint for WhatsApp routes
whatsapp = Blueprint('whatsapp', __name__)

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
    message = WhatsAppMessage.query.filter_by(
        from_number=phone_number,
        thread_id__isnot=None
    ).order_by(WhatsAppMessage.timestamp.desc()).first()

    if message and message.thread_id:
        return message.thread_id

    # Create new thread if none exists
    thread = client.beta.threads.create()
    return thread.id

def generate_ai_response(message_body, thread_id):
    """Generate response using OpenAI assistant"""
    try:
        # Add the user's message to the thread
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

        # Wait for response
        while True:
            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            if run_status.status == 'completed':
                break
            elif run_status.status == 'failed':
                return "Désolé, je n'ai pas pu générer une réponse. Veuillez réessayer."

        # Get the assistant's response
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        return messages.data[0].content[0].text.value

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
                    if message.get('type') == 'text':
                        sender = message.get('from')
                        message_body = message.get('text', {}).get('body', '')
                        message_id = message.get('id')

                        logger.info(f"Processing message from {sender}: {message_body}")

                        try:
                            # Get or create thread for this user
                            thread_id = get_or_create_thread(sender)

                            # Store incoming message
                            new_message = WhatsAppMessage(
                                message_id=message_id,
                                from_number=sender,
                                content=message_body,
                                direction='inbound',
                                thread_id=thread_id
                            )
                            db.session.add(new_message)
                            db.session.commit()

                            # Generate AI response
                            response_text = generate_ai_response(message_body, thread_id)

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
                                logger.info(f"Sent response to {sender}: {response_text}")
                        except Exception as e:
                            logger.error(f"Error processing message: {str(e)}")
                            db.session.rollback()
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