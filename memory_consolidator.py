"""
Service de consolidation de la mémoire utilisateur.
Analyse les conversations terminées et met à jour les profils utilisateurs de manière asynchrone.
"""

import logging
import json
import time
from datetime import datetime, timedelta, date
from sqlalchemy import or_, func

# Avoid importing `app` at module import time to prevent circular imports.
# Import `app` lazily inside functions that need an application context.
from database import db
from models import (
    User, UserMemory, ConsolidatedConversation,
    Conversation, Message,
    TelegramConversation, TelegramMessage,
    WhatsAppMessage
)
from ai_config import openai_client, CURRENT_MODEL
from ai_functions import MEMORY_FUNCTIONS

logger = logging.getLogger(__name__)


# ============================================================================
# FONCTIONS DE MISE À JOUR DE LA BASE DE DONNÉES
# ============================================================================

def _update_memory_profile(user_id, data):
    """
    Met à jour le profil mémoire d'un utilisateur avec les nouvelles informations.

    Args:
        user_id: ID de l'utilisateur dans la table User
        data: Dictionnaire contenant les champs à mettre à jour
    """
    try:
        from app import app as _app
        with _app.app_context():
            memory = UserMemory.query.filter_by(user_id=user_id).first()

            if not memory:
                memory = UserMemory(user_id=user_id)
                db.session.add(memory)
                logger.info(f"Création d'une nouvelle mémoire pour user_id {user_id}")

            # Mise à jour des champs simples
            if data.get('nom'):
                memory.nom = data['nom']
                logger.debug(f"Nom mis à jour pour user {user_id}: {data['nom']}")

            if data.get('niveau'):
                # Tronquer à 100 caractères pour éviter l'erreur de troncature
                niveau_value = str(data['niveau'])[:100]
                memory.niveau = niveau_value
                logger.debug(f"Niveau mis à jour pour user {user_id}: {niveau_value}")

            if data.get('mode_prefere'):
                memory.mode_prefere = data['mode_prefere']
                logger.debug(f"Mode préféré mis à jour pour user {user_id}: {data['mode_prefere']}")

            # Mise à jour des listes (sans dupliquer)
            if data.get('matieres_difficiles'):
                current = set(memory.matieres_difficiles or [])
                current.update(data['matieres_difficiles'])
                memory.matieres_difficiles = list(current)
                logger.debug(f"Matières difficiles mises à jour pour user {user_id}: {list(current)}")

            if data.get('matieres_preferees'):
                current = set(memory.matieres_preferees or [])
                current.update(data['matieres_preferees'])
                memory.matieres_preferees = list(current)
                logger.debug(f"Matières préférées mises à jour pour user {user_id}: {list(current)}")

            memory.updated_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"✅ Profil mémoire mis à jour pour user_id {user_id}")

    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du profil pour user_id {user_id}: {e}", exc_info=True)
        db.session.rollback()


def _log_study_session(user_id, data):
    """
    Enregistre une session d'étude (matière + sujet) dans la mémoire.

    Args:
        user_id: ID de l'utilisateur
        data: Dict avec 'matiere' et 'sujet'
    """
    try:
        from app import app as _app
        with _app.app_context():
            memory = UserMemory.query.filter_by(user_id=user_id).first()

            if not memory:
                memory = UserMemory(user_id=user_id)
                db.session.add(memory)

            new_topic = {
                "date": date.today().isoformat(),
                "matiere": data['matiere'],
                "sujet": data['sujet']
            }

            current_sujets = memory.derniers_sujets or []
            current_sujets.append(new_topic)

            # Garder uniquement les 10 derniers sujets
            memory.derniers_sujets = current_sujets[-10:]

            db.session.commit()
            logger.info(f"✅ Session d'étude enregistrée pour user_id {user_id}: {data['matiere']} - {data['sujet']}")

    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement de la session pour user_id {user_id}: {e}", exc_info=True)
        db.session.rollback()


def _update_streak(memory):
    """
    Met à jour le streak (jours consécutifs d'utilisation) de l'utilisateur.

    Args:
        memory: Objet UserMemory
    """
    try:
        today = date.today()
        last_interaction = memory.derniere_interaction

        if not last_interaction:
            # Première interaction
            memory.streak_jours = 1
        elif last_interaction == today:
            # Déjà interagi aujourd'hui, pas de changement
            pass
        elif last_interaction == today - timedelta(days=1):
            # Interaction hier, on incrémente le streak
            memory.streak_jours = (memory.streak_jours or 0) + 1
        else:
            # Rupture du streak
            memory.streak_jours = 1

        memory.derniere_interaction = today

    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du streak: {e}")


# ============================================================================
# FONCTION PRINCIPALE DE CONSOLIDATION
# ============================================================================

def consolidate_memory_for_user(user_id, conversation_transcript):
    """
    Analyse un transcript de conversation et met à jour la mémoire de l'utilisateur.
    Utilise l'IA avec function calling pour extraire les informations pertinentes.

    Args:
        user_id: ID de l'utilisateur dans la table User
        conversation_transcript: Texte complet de la conversation à analyser
    """
    if not conversation_transcript or not conversation_transcript.strip():
        logger.warning(f"Tentative de consolidation pour user_id {user_id} avec un transcript vide.")
        return

    # Limiter la taille du transcript pour éviter de dépasser les limites de tokens
    max_chars = 15000  # ~3-4K tokens
    if len(conversation_transcript) > max_chars:
        logger.warning(f"Transcript trop long pour user {user_id} ({len(conversation_transcript)} chars), troncature à {max_chars}")
        conversation_transcript = conversation_transcript[-max_chars:]  # Garder la fin

    consolidation_prompt = f"""
Analyse cette conversation entre un élève et Exô (assistant éducatif).
Ton objectif est d'extraire des informations clés sur le profil de l'élève pour personnaliser ses futures interactions.

CONVERSATION :
{conversation_transcript}

TÂCHE :
- Si l'élève mentionne son nom, son niveau d'études, ou ses préférences → utilise `update_user_profile`
- Si l'élève exprime des difficultés dans une matière → ajoute-la aux `matieres_difficiles`
- Si l'élève dit aimer une matière → ajoute-la aux `matieres_preferees`
- Pour chaque sujet académique abordé → utilise `log_study_session` avec la matière et le sujet précis
- Si l'élève préfère des explications détaillées avec exemples → `mode_prefere: "Détaillé"`
- Si l'élève demande juste les réponses directes → `mode_prefere: "Rapide"`

IMPORTANT :
- N'invente AUCUNE information
- N'appelle les fonctions QUE si les informations sont explicitement présentes
- Un sujet est "étudié" s'il y a eu des explications ou exercices, pas juste une mention
"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4.1-mini",  # Utiliser explicitement votre modèle
                messages=[
                    {"role": "system", "content": "Tu es un analyseur intelligent de conversations éducatives."},
                    {"role": "user", "content": consolidation_prompt}
                ],
                tools=MEMORY_FUNCTIONS,
                tool_choice="auto",
                timeout=60
            )

            tool_calls = response.choices[0].message.tool_calls

            if not tool_calls:
                logger.info(f"Aucune information à consolider pour user_id {user_id}.")
                return

            # Exécuter les appels de fonction
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                logger.debug(f"Function call détecté: {function_name} avec args: {arguments}")

                if function_name == "update_user_profile":
                    _update_memory_profile(user_id, arguments)
                elif function_name == "log_study_session":
                    _log_study_session(user_id, arguments)

            # Mettre à jour les métadonnées (streak, nb_interactions)
            from app import app as _app
            with _app.app_context():
                memory = UserMemory.query.filter_by(user_id=user_id).first()
                if memory:
                    _update_streak(memory)
                    memory.nb_interactions = (memory.nb_interactions or 0) + 1
                    db.session.commit()
                    logger.info(f"🧠 Consolidation réussie pour user_id {user_id} (streak: {memory.streak_jours} jours)")

            return  # Succès, sortir de la boucle de retry

        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"❌ Consolidation échouée après {max_retries} tentatives pour user_id {user_id}: {e}", exc_info=True)
                return
            else:
                wait_time = 2 ** attempt  # Backoff exponentiel: 1s, 2s, 4s
                logger.warning(f"Tentative {attempt + 1}/{max_retries} échouée pour user {user_id}, retry dans {wait_time}s...")
                time.sleep(wait_time)


# ============================================================================
# TÂCHE PLANIFIÉE (SCHEDULER)
# ============================================================================

def run_consolidation_task():
    """
    Tâche planifiée qui recherche les conversations inactives sur les 3 plateformes
    et déclenche leur consolidation.
    """
    logger.info("🔄 SCHEDULER: Démarrage de la tâche de consolidation...")

    try:
        with app.app_context():
            # Seuil d'inactivité : 10 minutes pour avoir une marge de sécurité
            inactive_since = datetime.utcnow() - timedelta(minutes=60)
            logger.debug(f"SCHEDULER: Recherche des conversations inactives avant {inactive_since.strftime('%Y-%m-%d %H:%M:%S')} UTC")

            consolidations_count = 0
            max_consolidations_per_run = 3000

            # ===== CONSOLIDATION WEB =====
            try:
                query_web = Conversation.query.filter(
                    Conversation.updated_at < inactive_since,
                    Conversation.user_id.isnot(None)
                ).order_by(Conversation.updated_at.desc())
                web_convs_count = query_web.count()
                logger.debug(f"SCHEDULER (Web): {web_convs_count} conversation(s) potentielle(s) trouvée(s).")

                if web_convs_count > 0:
                    web_convs = query_web.limit(max_consolidations_per_run).all()
                    for conv in web_convs:
                        logger.debug(f"SCHEDULER (Web): Traitement de la conv ID {conv.id}, updated_at: {conv.updated_at}")
                        # ... (le reste de la logique reste identique)
                        # Vérifier si la conversation a été mise à jour depuis la dernière consolidation
                        consolidation_record = ConsolidatedConversation.query.filter_by(
                            platform='web',
                            conversation_id=str(conv.id)
                        ).first()

                        if consolidation_record and consolidation_record.consolidated_at >= conv.updated_at:
                            logger.debug(f"SCHEDULER (Web): Conv {conv.id} non modifiée depuis la dernière consolidation, ignorée.")
                            continue
                        messages = Message.query.filter_by(conversation_id=conv.id).order_by(Message.created_at).all()
                        if not messages:
                            continue
                        transcript = "\n".join([f"{'Élève' if msg.role == 'user' else 'Exô'}: {msg.content}" for msg in messages])
                        logger.info(f"📝 Web: Consolidation conv {conv.id} (user {conv.user_id})")
                        consolidate_memory_for_user(conv.user_id, transcript)
                        # Mettre à jour ou créer le tampon de consolidation
                        if consolidation_record:
                            consolidation_record.consolidated_at = datetime.utcnow()
                        else:
                            db.session.add(ConsolidatedConversation(
                                platform='web',
                                conversation_id=str(conv.id)
                            ))
                        db.session.commit()
                        consolidations_count += 1
                        if consolidations_count >= max_consolidations_per_run:
                            break
            except Exception as web_error:
                logger.error(f"Erreur consolidation Web: {web_error}", exc_info=True)

            # ===== CONSOLIDATION TELEGRAM =====
            try:
                query_tg = TelegramConversation.query.filter(
                    TelegramConversation.updated_at < inactive_since,
                    TelegramConversation.telegram_user_id.isnot(None)
                ).order_by(TelegramConversation.updated_at.desc())
                tg_convs_count = query_tg.count()
                logger.debug(f"SCHEDULER (Telegram): {tg_convs_count} conversation(s) potentielle(s) trouvée(s).")

                if tg_convs_count > 0:
                    tg_convs = query_tg.limit(max_consolidations_per_run - consolidations_count).all()
                    for tg_conv in tg_convs:
                        logger.debug(f"SCHEDULER (Telegram): Traitement de la conv ID {tg_conv.id}, updated_at: {tg_conv.updated_at}")
                        consolidation_record = ConsolidatedConversation.query.filter_by(platform='telegram', conversation_id=str(tg_conv.id)).first()
                        if consolidation_record and consolidation_record.consolidated_at >= tg_conv.updated_at:
                            logger.debug(f"SCHEDULER (Telegram): Conv {tg_conv.id} non modifiée depuis la dernière consolidation, ignorée.")
                            continue
                        user_phone_id = f"telegram_{tg_conv.telegram_user_id}"
                        web_user = User.query.filter_by(phone_number=user_phone_id).first()
                        if not web_user:
                            logger.warning(f"SCHEDULER (Telegram): User web non trouvé pour telegram_id {tg_conv.telegram_user_id}, ignoré.")
                            continue
                        messages = TelegramMessage.query.filter_by(conversation_id=tg_conv.id).order_by(TelegramMessage.created_at).all()
                        if not messages:
                            continue
                        transcript = "\n".join([f"{'Élève' if msg.role == 'user' else 'Exô'}: {msg.content}" for msg in messages])
                        logger.info(f"📱 Telegram: Consolidation conv {tg_conv.id} (user {web_user.id})")
                        consolidate_memory_for_user(web_user.id, transcript)
                        # Mettre à jour ou créer le tampon de consolidation
                        if consolidation_record:
                            consolidation_record.consolidated_at = datetime.utcnow()
                        else:
                            db.session.add(ConsolidatedConversation(
                                platform='telegram',
                                conversation_id=str(tg_conv.id)
                            ))
                        db.session.commit()
                        consolidations_count += 1
                        if consolidations_count >= max_consolidations_per_run:
                            break
            except Exception as tg_error:
                logger.error(f"Erreur consolidation Telegram: {tg_error}", exc_info=True)

            # ===== CONSOLIDATION WHATSAPP =====
            try:
                # Étape 1: Compter sans le tri pour éviter l'erreur
                query_wa_for_count = db.session.query(WhatsAppMessage.thread_id).filter(
                    WhatsAppMessage.timestamp < inactive_since,
                    WhatsAppMessage.thread_id.isnot(None)
                ).distinct()
                wa_threads_count = query_wa_for_count.count()
                logger.debug(f"SCHEDULER (WhatsApp): {wa_threads_count} thread(s) potentiel(s) trouvé(s).")

                if wa_threads_count > 0:
                    # Étape 2: Récupérer les threads avec le tri
                    # Nous ne pouvons pas trier directement, donc nous prenons les derniers threads traités.
                    # Ce n'est pas parfait mais ça évite le crash.
                    wa_threads = query_wa_for_count.limit(max_consolidations_per_run - consolidations_count).all()
                    for (thread_id,) in wa_threads:
                        logger.debug(f"SCHEDULER (WhatsApp): Traitement du thread ID {thread_id[:12]}...")
                        # Le reste de votre logique pour WhatsApp reste identique ici
                        last_message = WhatsAppMessage.query.filter_by(thread_id=thread_id).order_by(WhatsAppMessage.timestamp.desc()).first()
                        if not last_message:
                            continue

                        consolidation_record = ConsolidatedConversation.query.filter_by(platform='whatsapp', conversation_id=thread_id).first()
                        if consolidation_record and consolidation_record.consolidated_at >= last_message.timestamp:
                            logger.debug(f"SCHEDULER (WhatsApp): Thread {thread_id[:12]} non modifié depuis la dernière consolidation, ignoré.")
                            continue

                        first_msg = WhatsAppMessage.query.filter_by(thread_id=thread_id, direction='inbound').order_by(WhatsAppMessage.timestamp).first()
                        if not first_msg:
                            continue
                        user_phone_id = f"whatsapp_{first_msg.from_number}"
                        web_user = User.query.filter_by(phone_number=user_phone_id).first()
                        if not web_user:
                            continue
                        messages = WhatsAppMessage.query.filter_by(thread_id=thread_id).order_by(WhatsAppMessage.timestamp).all()
                        if not messages:
                            continue
                        transcript = "\n".join([f"{'Élève' if msg.direction == 'inbound' else 'Exô'}: {msg.content}" for msg in messages])
                        logger.info(f"💬 WhatsApp: Consolidation thread {thread_id[:8]}... (user {web_user.id})")
                        consolidate_memory_for_user(web_user.id, transcript)

                        if consolidation_record:
                            consolidation_record.consolidated_at = datetime.utcnow()
                        else:
                            db.session.add(ConsolidatedConversation(
                                platform='whatsapp',
                                conversation_id=thread_id
                            ))
                        db.session.commit()
                        consolidations_count += 1
                        if consolidations_count >= max_consolidations_per_run:
                            break
            except Exception as wa_error:
                logger.error(f"Erreur consolidation WhatsApp: {wa_error}", exc_info=True)

            logger.info(f"✅ SCHEDULER: Tâche terminée. {consolidations_count} consolidation(s) effectuée(s).")

    except Exception as e:
        logger.error(f"❌ SCHEDULER: Erreur critique dans run_consolidation_task: {e}", exc_info=True)