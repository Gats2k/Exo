import os
import json
import logging
import time
from typing import Optional
from openai import OpenAI

# Configuration du logging
logger = logging.getLogger(__name__)

# ===================================
# INITIALISATION DES CLIENTS IA (LAZY)
# ===================================

def _create_openai_client(api_key: Optional[str], base_url: Optional[str] = None) -> Optional[OpenAI]:
    """Crée un client OpenAI si une clé est fournie, sinon retourne None."""
    if not api_key:
        return None
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)

# Cached clients (créés à la demande)
openai_client: Optional[OpenAI] = None
deepseek_client: Optional[OpenAI] = None
qwen_client: Optional[OpenAI] = None
gemini_openai_client: Optional[OpenAI] = None

ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')
CONTEXT_MESSAGE_LIMIT = int(os.environ.get('CONTEXT_MESSAGE_LIMIT', '30'))

# ===================================
# CHARGEMENT DES INSTRUCTIONS
# ===================================

def load_instructions_from_file(file_path, default_value):
    """Charge les instructions depuis un fichier texte"""
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    return default_value

# ===================================
# INSTRUCTIONS POUR LE CONTEXTE CHAT (ton familier, emojis)
# ===================================

DEEPSEEK_CHAT_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('DEEPSEEK_CHAT_INSTRUCTIONS_FILE', 'instructions/chat/deepseek.txt'),
    'You are a helpful educational assistant'
)

DEEPSEEK_REASONER_CHAT_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('DEEPSEEK_REASONER_CHAT_INSTRUCTIONS_FILE', 'instructions/deepseek_reasoner.txt'),
    'You are a helpful educational assistant focused on reasoning'
)

QWEN_CHAT_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('QWEN_CHAT_INSTRUCTIONS_FILE', 'instructions/chat/qwen.txt'),
    'You are a helpful educational assistant'
)

GEMINI_CHAT_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('GEMINI_CHAT_INSTRUCTIONS_FILE', 'instructions/chat/gemini.txt'),
    'You are a helpful educational assistant'
)

# ===================================
# INSTRUCTIONS POUR LE CONTEXTE LESSON (ton factuel, neutre)
# ===================================

DEEPSEEK_LESSON_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('DEEPSEEK_LESSON_INSTRUCTIONS_FILE', 'instructions/lesson/deepseek.txt'),
    'You are a professional academic transcription improvement system'
)

DEEPSEEK_REASONER_LESSON_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('DEEPSEEK_REASONER_LESSON_INSTRUCTIONS_FILE', 'instructions/lesson/deepseek.txt'),
    'You are a professional academic transcription improvement system'
)

QWEN_LESSON_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('QWEN_LESSON_INSTRUCTIONS_FILE', 'instructions/lesson/qwen.txt'),
    'You are a professional academic transcription improvement system'
)

GEMINI_LESSON_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('GEMINI_LESSON_INSTRUCTIONS_FILE', 'instructions/lesson/gemini.txt'),
    'You are a professional academic transcription improvement system'
)

# Rétrocompatibilité : garder les anciennes variables pour ne pas casser le code existant
DEEPSEEK_INSTRUCTIONS = DEEPSEEK_CHAT_INSTRUCTIONS
DEEPSEEK_REASONER_INSTRUCTIONS = DEEPSEEK_REASONER_CHAT_INSTRUCTIONS
QWEN_INSTRUCTIONS = QWEN_CHAT_INSTRUCTIONS
GEMINI_INSTRUCTIONS = GEMINI_CHAT_INSTRUCTIONS

# ===================================
# MODÈLE ACTUEL
# ===================================

CURRENT_MODEL = os.environ.get('CURRENT_MODEL')
if not CURRENT_MODEL:
    # Favoriser Deepseek par défaut si une clé Deepseek est présente,
    # sinon conserver le comportement historique ('openai').
    if os.environ.get('DEEPSEEK_API_KEY'):
        CURRENT_MODEL = 'deepseek'
    else:
        CURRENT_MODEL = 'openai'

# ===================================
# FONCTIONS DE SÉLECTION
# ===================================

def get_ai_client():
    """Retourne le client IA approprié selon le modèle actuel"""
    global openai_client, deepseek_client, qwen_client, gemini_openai_client

    # Deepseek models
    if CURRENT_MODEL in ['deepseek', 'deepseek-reasoner']:
        if deepseek_client is None:
            deepseek_client = _create_openai_client(os.getenv('DEEPSEEK_API_KEY'), base_url="https://api.deepseek.com")
        if deepseek_client is None:
            raise RuntimeError("Deepseek client not configured. Set DEEPSEEK_API_KEY or change CURRENT_MODEL.")
        return deepseek_client

    # Qwen
    if CURRENT_MODEL == 'qwen':
        if qwen_client is None:
            qwen_client = _create_openai_client(os.getenv('DASHSCOPE_API_KEY'), base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        if qwen_client is None:
            raise RuntimeError("Qwen client not configured. Set DASHSCOPE_API_KEY.")
        return qwen_client

    # Gemini
    if CURRENT_MODEL == 'gemini':
        if gemini_openai_client is None:
            gemini_openai_client = _create_openai_client(os.getenv('GEMINI_API_KEY'), base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
        if gemini_openai_client is None:
            raise RuntimeError("Gemini client not configured. Set GEMINI_API_KEY.")
        return gemini_openai_client

    # Default / openai
    if openai_client is None:
        openai_client = _create_openai_client(os.getenv('OPENAI_API_KEY'))
    if openai_client:
        return openai_client

    # Fallback: if OpenAI not configured, prefer Deepseek if available
    if os.getenv('DEEPSEEK_API_KEY'):
        if deepseek_client is None:
            deepseek_client = _create_openai_client(os.getenv('DEEPSEEK_API_KEY'), base_url="https://api.deepseek.com")
        if deepseek_client:
            return deepseek_client

    raise RuntimeError("No AI client configured for CURRENT_MODEL='%s'. Set the appropriate API key in environment." % CURRENT_MODEL)


def get_model_name():
    """Retourne le nom du modèle approprié selon le modèle actuel"""
    if CURRENT_MODEL == 'deepseek':
        return "deepseek-chat"
    elif CURRENT_MODEL == 'deepseek-reasoner':
        return "deepseek-reasoner"
    elif CURRENT_MODEL == 'qwen':
        return "qwen-max-latest"
    elif CURRENT_MODEL == 'gemini':
        return "gemini-2.5-flash-preview-04-17"
    return None


def get_system_instructions(context='chat'):
    """
    Retourne les instructions système appropriées selon le modèle actuel et le contexte
    
    Args:
        context (str): Le contexte d'utilisation ('chat' ou 'lesson')
                      - 'chat': Ton familier, emojis, conversationnel
                      - 'lesson': Ton factuel, neutre, académique
    
    Returns:
        str: Les instructions système appropriées
    """
    if context == 'lesson':
        # Instructions pour le traitement des cours (ton factuel)
        if CURRENT_MODEL == 'deepseek':
            return DEEPSEEK_LESSON_INSTRUCTIONS
        elif CURRENT_MODEL == 'deepseek-reasoner':
            return DEEPSEEK_REASONER_LESSON_INSTRUCTIONS
        elif CURRENT_MODEL == 'qwen':
            return QWEN_LESSON_INSTRUCTIONS
        elif CURRENT_MODEL == 'gemini':
            return GEMINI_LESSON_INSTRUCTIONS
    else:
        # Instructions pour le chat (ton familier) - par défaut
        if CURRENT_MODEL == 'deepseek':
            return DEEPSEEK_CHAT_INSTRUCTIONS
        elif CURRENT_MODEL == 'deepseek-reasoner':
            return DEEPSEEK_REASONER_CHAT_INSTRUCTIONS
        elif CURRENT_MODEL == 'qwen':
            return QWEN_CHAT_INSTRUCTIONS
        elif CURRENT_MODEL == 'gemini':
            return GEMINI_CHAT_INSTRUCTIONS
    
    # Pour OpenAI ou tout autre cas, retourner une chaîne vide pour éviter les erreurs.
    return ""


def reload_model_settings():
    """
    Recharge les paramètres du modèle depuis l'environnement et les sauvegarde dans un fichier JSON.
    """
    global CURRENT_MODEL
    global DEEPSEEK_CHAT_INSTRUCTIONS, DEEPSEEK_REASONER_CHAT_INSTRUCTIONS, QWEN_CHAT_INSTRUCTIONS, GEMINI_CHAT_INSTRUCTIONS
    global DEEPSEEK_LESSON_INSTRUCTIONS, DEEPSEEK_REASONER_LESSON_INSTRUCTIONS, QWEN_LESSON_INSTRUCTIONS, GEMINI_LESSON_INSTRUCTIONS
    global DEEPSEEK_INSTRUCTIONS, DEEPSEEK_REASONER_INSTRUCTIONS, QWEN_INSTRUCTIONS, GEMINI_INSTRUCTIONS

    # Recharger le modèle depuis l'environnement
    CURRENT_MODEL = os.environ.get('CURRENT_MODEL')
    if not CURRENT_MODEL:
        if os.environ.get('DEEPSEEK_API_KEY'):
            CURRENT_MODEL = 'deepseek'
        else:
            CURRENT_MODEL = 'openai'

    # Charger les instructions CHAT depuis les fichiers
    DEEPSEEK_CHAT_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('DEEPSEEK_CHAT_INSTRUCTIONS_FILE', 'instructions/chat/deepseek.txt'),
        'You are a helpful educational assistant'
    )
    DEEPSEEK_REASONER_CHAT_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('DEEPSEEK_REASONER_CHAT_INSTRUCTIONS_FILE', 'instructions/deepseek_reasoner.txt'),
        'You are a helpful educational assistant focused on reasoning'
    )
    QWEN_CHAT_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('QWEN_CHAT_INSTRUCTIONS_FILE', 'instructions/chat/qwen.txt'),
        'You are a helpful educational assistant'
    )
    GEMINI_CHAT_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('GEMINI_CHAT_INSTRUCTIONS_FILE', 'instructions/chat/gemini.txt'),
        'You are a helpful educational assistant'
    )

    # Charger les instructions LESSON depuis les fichiers
    DEEPSEEK_LESSON_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('DEEPSEEK_LESSON_INSTRUCTIONS_FILE', 'instructions/lesson/deepseek.txt'),
        'You are a professional academic transcription improvement system'
    )
    DEEPSEEK_REASONER_LESSON_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('DEEPSEEK_REASONER_LESSON_INSTRUCTIONS_FILE', 'instructions/lesson/deepseek.txt'),
        'You are a professional academic transcription improvement system'
    )
    QWEN_LESSON_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('QWEN_LESSON_INSTRUCTIONS_FILE', 'instructions/lesson/qwen.txt'),
        'You are a professional academic transcription improvement system'
    )
    GEMINI_LESSON_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('GEMINI_LESSON_INSTRUCTIONS_FILE', 'instructions/lesson/gemini.txt'),
        'You are a professional academic transcription improvement system'
    )

    # Rétrocompatibilité
    DEEPSEEK_INSTRUCTIONS = DEEPSEEK_CHAT_INSTRUCTIONS
    DEEPSEEK_REASONER_INSTRUCTIONS = DEEPSEEK_REASONER_CHAT_INSTRUCTIONS
    QWEN_INSTRUCTIONS = QWEN_CHAT_INSTRUCTIONS
    GEMINI_INSTRUCTIONS = GEMINI_CHAT_INSTRUCTIONS

    # Utiliser un chemin absolu pour le fichier de configuration
    config_file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'ai_config.json'
    )

    # Sauvegarde des configurations dans un fichier JSON
    config_data = {
        'timestamp': time.time(),
        'CURRENT_MODEL': CURRENT_MODEL,
        'DEEPSEEK_CHAT_INSTRUCTIONS': DEEPSEEK_CHAT_INSTRUCTIONS,
        'DEEPSEEK_REASONER_CHAT_INSTRUCTIONS': DEEPSEEK_REASONER_CHAT_INSTRUCTIONS,
        'QWEN_CHAT_INSTRUCTIONS': QWEN_CHAT_INSTRUCTIONS,
        'GEMINI_CHAT_INSTRUCTIONS': GEMINI_CHAT_INSTRUCTIONS,
        'DEEPSEEK_LESSON_INSTRUCTIONS': DEEPSEEK_LESSON_INSTRUCTIONS,
        'DEEPSEEK_REASONER_LESSON_INSTRUCTIONS': DEEPSEEK_REASONER_LESSON_INSTRUCTIONS,
        'QWEN_LESSON_INSTRUCTIONS': QWEN_LESSON_INSTRUCTIONS,
        'GEMINI_LESSON_INSTRUCTIONS': GEMINI_LESSON_INSTRUCTIONS
    }

    try:
        with open(config_file_path, 'w') as f:
            json.dump(config_data, f)
        # S'assurer que le fichier a les permissions correctes (skippé sous Windows)
        try:
            if os.name != 'nt':
                os.chmod(config_file_path, 0o666)
        except Exception:
            # Ne pas faire échouer la recharge pour des erreurs de permissions
            logger.debug("Could not chmod ai_config.json; continuing.")

        # Clear cached clients so they will be re-created lazily with new env vars
        global openai_client, deepseek_client, qwen_client, gemini_openai_client
        openai_client = None
        deepseek_client = None
        qwen_client = None
        gemini_openai_client = None

        logger.info(f"AI model settings saved to {config_file_path}: {CURRENT_MODEL}")
    except Exception as e:
        logger.error(f"Error saving AI model settings to file ({config_file_path}): {str(e)}")