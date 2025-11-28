import logging
import time
from typing_extensions import override
from openai import AssistantEventHandler
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

def prepare_messages_for_api(
    messages: List[Dict[str, str]], 
    current_model: str,
    system_instructions: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Prépare l'historique des messages pour l'API IA en gérant les spécificités de chaque modèle.

    Args:
        messages: Liste de dictionnaires {"role": "user/assistant", "content": "..."}
        current_model: Le modèle actuellement utilisé (ex: 'deepseek-reasoner', 'openai', etc.)
        system_instructions: Instructions système à ajouter au début (optionnel)

    Returns:
        Liste de messages formatée et corrigée pour l'API
    """
    # Ajouter les instructions système au début si fournies
    formatted_messages = []
    if system_instructions:
        formatted_messages.append({"role": "system", "content": system_instructions})

    # Si pas de messages ou modèle non concerné, retourner tel quel
    if not messages or current_model != 'deepseek-reasoner':
        formatted_messages.extend(messages)
        return formatted_messages

    # CORRECTION 1 : Vérifier et corriger les rôles initiaux pour deepseek-reasoner
    start_index = 0
    first_message_role = messages[0]['role'] if messages else None

    # Si le premier message est 'assistant', trouver le premier 'user' et supprimer ce qui précède
    if first_message_role == 'assistant':
        logger.warning("Premier message est 'assistant', correction nécessaire pour deepseek-reasoner")
        first_user_index = -1
        for i, msg in enumerate(messages):
            if msg['role'] == 'user':
                first_user_index = i
                break

        if first_user_index != -1:
            logger.info(f"Suppression de {first_user_index} message(s) 'assistant' initiaux")
            messages = messages[first_user_index:]
        else:
            # Aucun message user trouvé, ajouter un message fictif
            logger.warning("Aucun message 'user' trouvé, ajout d'un message fictif")
            messages.insert(0, {"role": "user", "content": "Bonjour"})

    # CORRECTION 2 : Fusionner les messages consécutifs du même rôle
    if len(messages) > 1:
        logger.info("Fusion des messages consécutifs pour deepseek-reasoner")
        merged_messages = []

        if messages:
            merged_messages.append(messages[0])

            for i in range(1, len(messages)):
                current_message = messages[i]
                last_merged_message = merged_messages[-1]

                # Fusionner si même rôle et pas 'system'
                if current_message['role'] == last_merged_message['role'] and current_message['role'] != 'system':
                    merged_content = f"{last_merged_message['content']}\n\n{current_message['content']}"
                    merged_messages[-1]['content'] = merged_content
                    logger.debug(f"Fusionné message {i} (role: {current_message['role']})")
                else:
                    merged_messages.append(current_message)

        formatted_messages.extend(merged_messages)
        logger.info(f"Historique final: {len(formatted_messages)} messages après fusion")
    else:
        formatted_messages.extend(messages)

    return formatted_messages

def execute_chat_completion(
    messages_history: List[Dict[str, str]],
    current_model: str,
    stream: bool = False,
    socketio_emitter = None,
    message_id = None,
    add_system_instructions: bool = True,  # <-- NOUVEAU PARAMÈTRE
    context: str = 'chat'  # <-- NOUVEAU: contexte pour les instructions
) -> Optional[str]:
    """
    Exécute un appel Chat Completion pour les modèles non-OpenAI.

    Args:
        messages_history: Historique [{"role": "...", "content": "..."}]
        current_model: Le modèle actuel (deepseek, qwen, gemini, etc.)
        stream: Mode streaming (True pour web, False pour bots)
        socketio_emitter: Objet socketio pour émettre (si stream=True)
        message_id: ID du message pour l'émission (si stream=True)
        add_system_instructions: Si True, ajoute les instructions système par défaut.
        context: Contexte d'utilisation ('chat' ou 'lesson')

    Returns:
        - Si stream=False: retourne la réponse complète (string)
        - Si stream=True: retourne la réponse complète après streaming (string)
    """
    try:
        # 1. Récupérer client et modèle
        from ai_config import get_ai_client, get_model_name, get_system_instructions

        ai_client = get_ai_client()
        model_name = get_model_name()

        if not model_name:
            logger.error(f"Could not determine model name for {current_model}")
            raise ValueError(f"Model name not found for {current_model}")

        # 2. Préparer les messages en ajoutant les instructions système SEULEMENT SI DEMANDÉ
        system_prompt = get_system_instructions(context=context) if add_system_instructions else None

        final_messages = prepare_messages_for_api(
            messages_history,
            current_model,
            system_prompt
        )

        # 3. Appeler l'API
        logger.debug(f"Calling API with model={model_name}, stream={stream}, context={context}")
        response = ai_client.chat.completions.create(
            model=model_name,
            messages=final_messages,
            stream=stream
        )

        # 4. Gérer la réponse selon le mode (logique inchangée)
        if not stream:
            # Mode non-streaming (WhatsApp, Telegram)
            assistant_message = response.choices[0].message.content
            logger.info(f"Non-streaming response received from {current_model}")
            return assistant_message
        else:
            # Mode streaming (Web App)
            assistant_message = ""

            for chunk in response:
                chunk_content = None
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and hasattr(delta, 'content'):
                        chunk_content = delta.content

                if chunk_content:
                    # Nettoyer le chunk
                    cleaned_chunk = _clean_response_text(chunk_content)
                    assistant_message += cleaned_chunk

                    # Émettre via SocketIO si disponible
                    if socketio_emitter and message_id:
                        socketio_emitter.emit('response_stream', {
                            'content': cleaned_chunk,
                            'message_id': message_id,
                            'is_final': False
                        })

            # Émettre le signal final
            if socketio_emitter and message_id:
                socketio_emitter.emit('response_stream', {
                    'content': '',
                    'message_id': message_id,
                    'is_final': True,
                    'full_response': assistant_message
                })

            logger.info(f"Streaming response completed from {current_model}")
            return assistant_message

    except Exception as e:
        logger.error(f"Error in execute_chat_completion: {str(e)}", exc_info=True)
        raise


def _clean_response_text(text: str) -> str:
    """
    Nettoie le texte en supprimant les caractères spéciaux de formatage.

    Args:
        text: Le texte à nettoyer

    Returns:
        Le texte nettoyé
    """
    if not text:
        return text

    # Supprimer les astérisques, dièses, et autres caractères de formatage
    cleaned_text = text.replace('*', '').replace('#', '').replace('```', '').replace('---', '')
    return cleaned_text

def upload_image_to_openai(file_path: str, platform: str = "General") -> str:
    """
    Upload une image vers OpenAI et retourne l'ID du fichier

    Args:
        file_path: Chemin vers le fichier image local
        platform: Contexte d'origine ('Web', 'WhatsApp', 'Telegram', etc.)

    Returns:
        str: L'ID du fichier uploadé sur OpenAI

    Raises:
        Exception: Si l'upload échoue
    """
    from ai_config import openai_client

    try:
        with open(file_path, 'rb') as file_content:
            openai_file = openai_client.files.create(
                file=file_content,
                purpose='assistants'
            )
            logger.info(f"Image {platform} uploadée vers OpenAI avec ID: {openai_file.id}")
            return openai_file.id
    except Exception as e:
        logger.error(f"Erreur upload OpenAI ({platform}): {str(e)}")
        raise


def process_image_for_openai(
    file_path: str, 
    base64_data: str, 
    user_text: str = "",
    platform: str = "General"
) -> tuple:
    """
    Traite une image pour OpenAI avec double approche (Vision API + OCR Mathpix)

    Args:
        file_path: Chemin vers le fichier image local
        base64_data: Données image en base64 pour Mathpix
        user_text: Message utilisateur ou caption à combiner avec l'OCR
        platform: Contexte d'origine pour la journalisation

    Returns:
        tuple: (openai_file_id, enhanced_message, results_dict)
            - openai_file_id: ID du fichier sur OpenAI (ou None)
            - enhanced_message: Message enrichi avec OCR
            - results_dict: Dictionnaire avec les statuts de succès

    Raises:
        Exception: Si les deux méthodes (Mathpix et OpenAI) échouent
    """
    results = {
        'mathpix_success': False,
        'openai_success': False,
        'formatted_summary': "",
        'openai_file_id': None
    }

    # 1. Mathpix OCR (silencieux si échec)
    try:
        from mathpix_utils import process_image_with_mathpix
        mathpix_result = process_image_with_mathpix(base64_data)
        if "error" not in mathpix_result:
            results['formatted_summary'] = mathpix_result.get("formatted_summary", "")
            results['mathpix_success'] = True
            logger.info(f"Mathpix OCR réussi pour {platform}")
    except Exception as e:
        logger.error(f"Échec Mathpix pour {platform}: {str(e)}")

    # 2. OpenAI Upload (silencieux si échec)
    try:
        results['openai_file_id'] = upload_image_to_openai(file_path, platform)
        results['openai_success'] = True
        logger.info(f"Upload OpenAI réussi pour {platform}: {results['openai_file_id']}")
    except Exception as e:
        logger.error(f"Échec upload OpenAI {platform}: {str(e)}")

    # 3. Validation - Au moins une méthode doit réussir
    if not results['mathpix_success'] and not results['openai_success']:
        raise Exception(f"Impossible de traiter l'image {platform}. Veuillez réessayer.")

    # 4. Construction du message enrichi
    enhanced_message = user_text or "Veuillez analyser cette image."
    if results['formatted_summary']:
        enhanced_message += f"\n\n[Extracted Image Content]\n{results['formatted_summary']}"

    return results['openai_file_id'], enhanced_message, results

class OpenAIAssistantEventHandler(AssistantEventHandler):
    """Gestionnaire d'événements pour le streaming des réponses de l'Assistant OpenAI"""

    def __init__(self, socket, message_id):
        super().__init__()
        self.socket = socket
        self.message_id = message_id
        self.full_response = ""
        self._AssistantEventHandler__stream = None
        self.time_module = time
        self.run_id = None

    @override
    def on_event(self, event):
        if event.event == 'thread.run.created':
            self.run_id = event.data.id
            logger.info(f"EventHandler: Run créé avec ID: {self.run_id}")

    @override
    def on_text_created(self, text) -> None:
        # Initialisation du texte - pas besoin d'envoyer de contenu ici
        pass

    @override
    def on_text_delta(self, delta, snapshot):
        # Ajouter le delta au texte complet
        self.full_response += delta.value

        # Émettre le nouveau contenu à l'utilisateur
        self.socket.emit(
            'response_stream', {
                'content': delta.value,
                'message_id': self.message_id,
                'is_final': False
            })

    @override
    def on_run_completed(self):
        # Émettre l'événement final quand le run est terminé
        self.socket.emit(
            'response_stream', {
                'content': '',
                'message_id': self.message_id,
                'is_final': True,
                'full_response': self.full_response
            })

    @override
    def on_tool_call_created(self, tool_call):
        # Pour gérer les appels d'outils comme code_interpreter si nécessaire
        pass

    @override
    def on_tool_call_delta(self, delta, snapshot):
        # Gérer les mises à jour des appels d'outils
        if delta.type == 'code_interpreter':
            if delta.code_interpreter and delta.code_interpreter.input:
                self.full_response += f"\n```python\n{delta.code_interpreter.input}\n```\n"
                self.socket.emit(
                    'response_stream', {
                        'content':
                        f"\n```python\n{delta.code_interpreter.input}\n```\n",
                        'message_id': self.message_id,
                        'is_final': False
                    })

            if delta.code_interpreter and delta.code_interpreter.outputs:
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        self.full_response += f"\n```\n{output.logs}\n```\n"
                        self.socket.emit(
                            'response_stream', {
                                'content': f"\n```\n{output.logs}\n```\n",
                                'message_id': self.message_id,
                                'is_final': False
                            })

def generate_reminder_message(
    user_identifier: str,
    platform: str,
    thread_id: str = None,
    reminder_type: str = "night"
) -> str:
    """
    Génère un message de rappel via le modèle configuré en utilisant le système existant

    Args:
        user_identifier: Numéro WhatsApp ou telegram_id
        platform: 'whatsapp' ou 'telegram'
        thread_id: Thread ID de l'utilisateur (pour OpenAI ou autres modèles)
        reminder_type: 'night', 'morning', ou 'evening'

    Returns:
        str: Message de rappel personnalisé
    """
    from ai_config import CURRENT_MODEL, ASSISTANT_ID, openai_client, CONTEXT_MESSAGE_LIMIT
    from models import User, UserMemory, TelegramMessage, WhatsAppMessage
    import time

    # Messages de consigne selon le type de rappel
    reminder_prompts = {
        'night': "En te basant sur nos échanges d'aujourd'hui, envoie-moi un message de bonne nuit très court (1-2 phrases max, style nouchi) pour me souhaiter bonne nuit et célébrer mon travail de la journée.Si on a rien fait aujourd'hui, souhaite moi simplement bonne nuit.",
        'morning': "Envoie-moi un message de bon matin très court (1-2 phrases max, style nouchi) pour me souhaiter bon courage pour la journée.",
        'evening': "En te basant sur nos échanges récents, envoie-moi un message de motivation très court (1-2 phrases max, style nouchi) pour m'encourager à travailler ce soir."
    }

    user_message = reminder_prompts.get(reminder_type, reminder_prompts['night'])

    try:
        # === RÉCUPÉRATION DU CONTEXTE MÉMOIRE (comme dans le code existant) ===
        memory_context = ""
        user_phone_id = f"{platform}_{user_identifier}"

        # Import local pour éviter circularité
        from app import app
        with app.app_context():
            user = User.query.filter_by(phone_number=user_phone_id).first()
            if user:
                memory = UserMemory.query.filter_by(user_id=user.id).first()
                if memory:
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

        from ai_config import get_system_instructions
        base_instructions = get_system_instructions()
        final_system_prompt = memory_context + base_instructions

        # === LOGIQUE SELON LE MODÈLE ===
        if CURRENT_MODEL == 'openai':
            # Utiliser l'Assistant OpenAI avec le thread existant
            if not thread_id:
                logger.error("Thread ID manquant pour OpenAI Assistant")
                return f"Yo poto! Bonne nuit! 😴"

            # Ajouter le contexte + consigne au thread
            message_with_context = final_system_prompt + "\n\n---\n\n" + user_message

            openai_client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message_with_context
            )

            # Créer et exécuter la run
            run = openai_client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID
            )

            # Attendre la complétion (timeout 60s pour rappel)
            timeout = 60
            start_time = time.time()

            while True:
                if time.time() - start_time > timeout:
                    logger.error("Timeout génération rappel OpenAI")
                    raise TimeoutError("OpenAI response timed out")

                run_status = openai_client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )

                if run_status.status == 'completed':
                    break
                elif run_status.status in ['failed', 'cancelled', 'expired']:
                    raise Exception(f"OpenAI Run failed: {run_status.status}")

                time.sleep(1)

            # Récupérer la réponse
            messages = openai_client.beta.threads.messages.list(
                thread_id=thread_id,
                order='desc',
                limit=1
            )

            if messages.data and messages.data[0].role == 'assistant':
                response = messages.data[0].content[0].text.value
                logger.info(f"Message rappel généré via OpenAI Assistant pour {platform}/{user_identifier}")
                return response
            else:
                raise Exception("Pas de réponse assistant valide")

        else:
            # Utiliser Chat Completion pour les autres modèles
            # Récupérer l'historique récent pour le contexte
            messages_history = []

            with app.app_context():
                if platform == 'telegram':
                    # Chercher la conversation Telegram
                    from models import TelegramConversation
                    conversation = TelegramConversation.query.filter_by(
                        thread_id=thread_id
                    ).first()

                    if conversation:
                        messages_query = TelegramMessage.query.filter_by(
                            conversation_id=conversation.id
                        ).order_by(TelegramMessage.created_at.desc()).limit(5).all()

                        for msg in reversed(messages_query):
                            role = msg.role if msg.role == 'user' else 'assistant'
                            messages_history.append({"role": role, "content": msg.content})

                elif platform == 'whatsapp':
                    messages_query = WhatsAppMessage.query.filter_by(
                        thread_id=thread_id
                    ).order_by(WhatsAppMessage.timestamp.desc()).limit(5).all()

                    for msg in reversed(messages_query):
                        role = 'user' if msg.direction == 'inbound' else 'assistant'
                        messages_history.append({"role": role, "content": msg.content})

            # Ajouter le message de rappel
            messages_history.append({"role": "user", "content": user_message})

            # Utiliser execute_chat_completion avec système existant
            response = execute_chat_completion(
                messages_history=messages_history,
                current_model=CURRENT_MODEL,
                stream=False,
                add_system_instructions=True  # Ajoute automatiquement memory + base_instructions
            )

            logger.info(f"Message rappel généré via {CURRENT_MODEL} pour {platform}/{user_identifier}")
            return response

    except Exception as e:
        logger.error(f"Erreur génération message de rappel: {str(e)}", exc_info=True)
        # Fallback simple
        fallback_messages = {
            'night': "Yo poto! Bonne nuit! 😴",
            'morning': "Yo poto! Bonne journée! 💪",
            'evening': "Yo poto! C'est le moment de bosser! 🔥"
        }
        return fallback_messages.get(reminder_type, fallback_messages['night'])