import uuid
import logging
from datetime import datetime
from flask_login import current_user
from database import db
from models import Conversation
from utils import db_retry_session

logger = logging.getLogger(__name__)


def conversation_is_valid(conversation, user):
    """Vérifie si un objet Conversation est valide et appartient à l'utilisateur."""
    if not conversation:
        return False  # N'existe pas en DB ou marquée supprimée (car on filtre par deleted=False)

    # Vérifier l'appartenance à l'utilisateur (important si authentification activée)
    if not user.is_authenticated or conversation.user_id != user.id:
        logger.warning(f"Validation échec: Conversation {conversation.id} n'appartient pas à l'utilisateur {user.id}")
        return False

    # Vérifier si le thread existe chez OpenAI (uniquement si c'est le modèle OpenAI)
    from ai_config import CURRENT_MODEL, get_ai_client

    if CURRENT_MODEL == 'openai':
        try:
            ai_client = get_ai_client()
            ai_client.beta.threads.retrieve(thread_id=conversation.thread_id)
            # Le thread existe chez OpenAI
        except Exception as e:
            logger.warning(f"Validation échec: Thread OpenAI {conversation.thread_id} introuvable ou invalide: {str(e)}.")
            return False  # Thread OpenAI invalide

    # Si toutes les vérifications passent
    return True


def get_or_create_conversation(thread_id=None, message_content=None):
    """Récupère ou crée une conversation avec gestion du thread selon le modèle."""
    with db_retry_session() as session:
        if thread_id:
            conversation = Conversation.query.filter_by(
                thread_id=thread_id).first()
            # Vérifier si cette conversation appartient à l'utilisateur actuel
            if conversation and current_user.is_authenticated and conversation.user_id == current_user.id:
                # Vérifier si le thread OpenAI existe toujours (uniquement pour le modèle OpenAI)
                from ai_config import CURRENT_MODEL, get_ai_client

                if CURRENT_MODEL == 'openai':
                    try:
                        # Tester si le thread existe dans OpenAI
                        client = get_ai_client()
                        client.beta.threads.messages.list(thread_id=thread_id, limit=1)
                        # Si on arrive jusqu'ici, le thread existe
                        return conversation
                    except Exception as e:
                        logger.warning(
                            f"Thread {thread_id} not found or invalid: {str(e)}"
                        )
                        # On continue pour créer un nouveau thread
                else:
                    # Pour les autres modèles, pas besoin de vérifier
                    return conversation
            # Si la conversation n'appartient pas à l'utilisateur actuel, on ignore ce thread_id

        # Create new thread and conversation
        from ai_config import CURRENT_MODEL, get_ai_client

        client = get_ai_client()
        if CURRENT_MODEL == 'openai':
            # Only create thread for OpenAI
            thread = client.beta.threads.create()
            thread_id = thread.id
        else:
            # For other models, generate a UUID as thread_id
            thread_id = str(uuid.uuid4())

        # Associer la conversation avec l'utilisateur connecté
        user_id = None
        if current_user.is_authenticated:
            user_id = current_user.id

        # Create appropriate title based on message content if available
        title = None
        if message_content:
            # Use message content for title (trimmed if needed)
            title = message_content[:30] + "..." if len(message_content) > 30 else message_content
            logger.info(f"Creating conversation with title from message: '{title}'")

        conversation = Conversation(thread_id=thread_id, user_id=user_id, title=title)
        session.add(conversation)
        session.commit()

        logger.info(f"Conversation {conversation.id} créée/récupérée, événement non émis à ce stade")

        return conversation