"""
Définition des fonctions que l'IA peut appeler pour mettre à jour la mémoire utilisateur.
Compatible avec tous les modèles : OpenAI, DeepSeek, Qwen, Gemini.
"""

MEMORY_FUNCTIONS = [
    {
        "type": "function",
        "function": {
            "name": "update_user_profile",
            "description": "Met à jour le profil éducatif de l'utilisateur (nom, niveau, matières, préférences). N'utiliser que si l'information est EXPLICITEMENT donnée par l'utilisateur.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nom": {
                        "type": "string",
                        "description": "Le prénom ou nom complet de l'utilisateur s'il le mentionne explicitement."
                    },
                    "niveau": {
                        "type": "string",
                        "description": "Niveau d'études exact de l'utilisateur (ex: 'Terminale D', '1ère C', '3ème', 'Licence 2')."
                    },
                    "matieres_difficiles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste des matières où l'utilisateur exprime explicitement des difficultés ou demande de l'aide."
                    },
                    "matieres_preferees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste des matières que l'utilisateur dit apprécier ou dans lesquelles il excelle."
                    },
                    "mode_prefere": {
                        "type": "string",
                        "enum": ["Détaillé", "Rapide"],
                        "description": "Préférence d'explication : 'Détaillé' si l'utilisateur demande des explications complètes avec exemples, 'Rapide' s'il veut juste la réponse directe."
                    }
                },
                "required": [],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_study_session",
            "description": "Enregistre une session d'étude avec la matière et le sujet traité. À utiliser pour CHAQUE sujet académique distinct abordé dans la conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "matiere": {
                        "type": "string",
                        "description": "La matière principale du sujet étudié (ex: 'Mathématiques', 'Physique', 'Chimie', 'SVT', 'Histoire')."
                    },
                    "sujet": {
                        "type": "string",
                        "description": "Le sujet, chapitre ou concept précis étudié (ex: 'Les équations différentielles', 'Les lois de Newton', 'La Révolution française')."
                    }
                },
                "required": ["matiere", "sujet"],
                "additionalProperties": False
            }
        }
    }
]