import os
import json
import logging
import time
from openai import OpenAI

# Configuration du logging
logger = logging.getLogger(__name__)

# ===================================
# INITIALISATION DES CLIENTS IA
# ===================================

openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
deepseek_client = OpenAI(
    api_key=os.getenv('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"
)
qwen_client = OpenAI(
    api_key=os.getenv('DASHSCOPE_API_KEY'),
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)
gemini_openai_client = OpenAI(
    api_key=os.getenv('GEMINI_API_KEY'),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

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

DEEPSEEK_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('DEEPSEEK_INSTRUCTIONS_FILE', 'instructions/deepseek.txt'),
    'You are a helpful educational assistant'
)

DEEPSEEK_REASONER_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('DEEPSEEK_REASONER_INSTRUCTIONS_FILE', 'instructions/deepseek_reasoner.txt'),
    'You are a helpful educational assistant focused on reasoning'
)

QWEN_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('QWEN_INSTRUCTIONS_FILE', 'instructions/qwen.txt'),
    'You are a helpful educational assistant'
)

GEMINI_INSTRUCTIONS = load_instructions_from_file(
    os.environ.get('GEMINI_INSTRUCTIONS_FILE', 'instructions/gemini.txt'),
    'You are a helpful educational assistant'
)

# ===================================
# MODÈLE ACTUEL
# ===================================

CURRENT_MODEL = os.environ.get('CURRENT_MODEL', 'openai')

# ===================================
# FONCTIONS DE SÉLECTION
# ===================================

def get_ai_client():
    """Retourne le client IA approprié selon le modèle actuel"""
    if CURRENT_MODEL in ['deepseek', 'deepseek-reasoner']:
        return deepseek_client
    elif CURRENT_MODEL == 'qwen':
        return qwen_client
    elif CURRENT_MODEL == 'gemini':
        return gemini_openai_client
    else:
        return openai_client


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


def get_system_instructions():
    """Retourne les instructions système appropriées selon le modèle actuel"""
    if CURRENT_MODEL == 'deepseek':
        return DEEPSEEK_INSTRUCTIONS
    elif CURRENT_MODEL == 'deepseek-reasoner':
        return DEEPSEEK_REASONER_INSTRUCTIONS
    elif CURRENT_MODEL == 'qwen':
        return QWEN_INSTRUCTIONS
    elif CURRENT_MODEL == 'gemini':
        return GEMINI_INSTRUCTIONS
    # Pour OpenAI ou tout autre cas, retourner une chaîne vide pour éviter les erreurs.
    return ""


def reload_model_settings():
    """
    Recharge les paramètres du modèle depuis l'environnement et les sauvegarde dans un fichier JSON.
    """
    global CURRENT_MODEL, DEEPSEEK_INSTRUCTIONS, DEEPSEEK_REASONER_INSTRUCTIONS, QWEN_INSTRUCTIONS, GEMINI_INSTRUCTIONS

    # Recharger le modèle depuis l'environnement
    CURRENT_MODEL = os.environ.get('CURRENT_MODEL', 'openai')

    # Charger les instructions depuis les fichiers
    DEEPSEEK_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('DEEPSEEK_INSTRUCTIONS_FILE', 'instructions/deepseek.txt'),
        'You are a helpful educational assistant'
    )
    DEEPSEEK_REASONER_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('DEEPSEEK_REASONER_INSTRUCTIONS_FILE', 'instructions/deepseek_reasoner.txt'),
        'You are a helpful educational assistant focused on reasoning'
    )
    QWEN_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('QWEN_INSTRUCTIONS_FILE', 'instructions/qwen.txt'),
        'You are a helpful educational assistant'
    )
    GEMINI_INSTRUCTIONS = load_instructions_from_file(
        os.environ.get('GEMINI_INSTRUCTIONS_FILE', 'instructions/gemini.txt'),
        'You are a helpful educational assistant'
    )

    # Utiliser un chemin absolu pour le fichier de configuration
    config_file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'ai_config.json'
    )

    # Sauvegarde des configurations dans un fichier JSON
    config_data = {
        'timestamp': time.time(),
        'CURRENT_MODEL': CURRENT_MODEL,
        'DEEPSEEK_INSTRUCTIONS': DEEPSEEK_INSTRUCTIONS,
        'DEEPSEEK_REASONER_INSTRUCTIONS': DEEPSEEK_REASONER_INSTRUCTIONS,
        'QWEN_INSTRUCTIONS': QWEN_INSTRUCTIONS,
        'GEMINI_INSTRUCTIONS': GEMINI_INSTRUCTIONS
    }

    try:
        with open(config_file_path, 'w') as f:
            json.dump(config_data, f)

        # S'assurer que le fichier a les permissions correctes
        os.chmod(config_file_path, 0o666)

        logger.info(f"AI model settings saved to {config_file_path}: {CURRENT_MODEL}")
    except Exception as e:
        logger.error(f"Error saving AI model settings to file ({config_file_path}): {str(e)}")