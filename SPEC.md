# SPEC — Exô (Assistant Éducatif)

## 1. Aperçu du projet
Exô est une plateforme d'assistance éducative multi-plateforme qui fournit des réponses pédagogiques et de l'aide aux élèves via :
- Interface Web (Flask + Socket.IO)
- Bots Telegram et WhatsApp
- Un moteur IA interchangeable (Deepseek, OpenAI Assistants, Qwen, Gemini)

Fonctionnalités clés : gestion des conversations, upload d'images (OCR + vision), suivi mémoire utilisateur (profil pédagogique), gestion d'abonnements/paiement, tâches planifiées pour consolidation et rappels.


## 2. Architecture & composants
- Web server : `Flask` (entry point `app.py`).
- Temps réel : `Flask-SocketIO` + `eventlet`.
- Base de données : `Flask-SQLAlchemy` (support Postgres / SQLite). Migrations via `Flask-Migrate`.
- Bots :
  - Telegram : `python-telegram-bot` (async), module `telegram_bot.py`.
  - WhatsApp : webhooks, module `whatsapp_bot.py`.
- IA : centralisé dans `ai_config.py`, appels via `ai_utils.py` et usage dans `chat_services.py`.
- Tasks : `APScheduler` (jobs schedulés listés dans `app.py`).


## 3. Schéma de données (résumé)
Tables principales (dans `models.py`) :
- `user` : utilisateurs web (auth, phone, rôle admin).
- `conversation` / `message` : historique des conversations côté Web.
- `telegram_user`, `telegram_conversation`, `telegram_message` : entités Telegram.
- `whatsapp_messages` : log WhatsApp (thread_id flexible).
- `plan`, `subscription`, `transaction` : paiements / abonnements.
- `user_usage` : comptage messages / warnings journaliers.
- `user_memory` : données de profil et derniers sujets (utilisé par consolidation).
- `consolidated_conversation` : trace des consolidations déjà faites.


## 4. Variables d'environnement importantes
- IA / modèles :
  - `CURRENT_MODEL` (openai | deepseek | deepseek-reasoner | qwen | gemini)
  - `DEEPSEEK_API_KEY`
  - `OPENAI_API_KEY`
  - `GEMINI_API_KEY`
  - `DASHSCOPE_API_KEY` (Qwen)
  - `DEEPSEEK_INSTRUCTIONS_FILE`, `DEEPSEEK_REASONER_INSTRUCTIONS_FILE`, `QWEN_INSTRUCTIONS_FILE`, `GEMINI_INSTRUCTIONS_FILE`
- Telegram : `TELEGRAM_BOT_TOKEN`, `RUN_TELEGRAM_BOT` (true/false)
- WhatsApp / payments : `WHATSAPP_API_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `EASYTRANSFERT_API_KEY`, `IPN_BASE_URL`, `WAVE_BUSINESS_NAME_ID`
- Web / DB : `DATABASE_URL` (ou `SQLALCHEMY_DATABASE_URI`), `FLASK_SECRET_KEY`
- Admin : `ADMIN_PHONE`, `ADMIN_PASSWORD`
- Autres : `OPENAI_ASSISTANT_ID`, `CONTEXT_MESSAGE_LIMIT`

**Remarque** : pour le développement local, si `DATABASE_URL` est absent, l'application tombera en back‑fallback sur `sqlite:///dev.sqlite3` (comportement ajouté pour faciliter le démarrage local).


## 5. Endpoints / Routes principaux
- Web UI :
  - `/` : chat (nécessite auth)
  - `/login`, `/register` : auth
  - `/admin`, `/admin/settings/model` : admin & changement modèle
  - `/privacy-policy`
- Bots / Webhooks :
  - `/telegram_webhook` : webhook Telegram
  - `/whatsapp/webhook` : verify (GET) et receive (POST)
- Payment : blueprint `payment_bp` (mounté depuis `payment_routes.py`)
- Socket.IO events : `send_message`, `rename_conversation`, `open_conversation`, `heartbeat`, `restore_session`, etc.


## 6. Flux IA & traitement
- `ai_config.py` centralise la sélection du backend IA.
- `ai_utils.py` prépare les messages (fusion, corrections), gère appels Chat Completions, streaming et upload d'images.
- `chat_services.py` orchestre la logique: lecture mémoire, limites d'usage, choix du modèle, envoi vers API et stockage des réponses.
- La logique supporte deux modes : OpenAI Assistants (threads & runs) et modèles compatibles Chat Completions (Deepseek, Qwen, Gemini) via `chat.completions`.


## 7. Démarrage local (PowerShell)
1. Installer dépendances :
```powershell
python -m pip install -r requirements.txt
```
2. Créer un `.env` minimal (exemple) :
```powershell
# .env
CURRENT_MODEL=deepseek
DEEPSEEK_API_KEY=sk-...
FLASK_SECRET_KEY=change-me
```
3. Lancer l'application :
```powershell
python app.py
```
- Si `TELEGRAM_BOT_TOKEN` absent, le bot Telegram sera ignoré (log warning). Si `DATABASE_URL` absent, SQLite sera utilisé pour le dev.


## 8. Tests & vérifications rapides
- Test création client IA (script fourni) : `python scripts/test_ai_client.py`.
- Vérifier que l'app démarre sans clés OpenAI/Qwen/Gemini si `DEEPSEEK_API_KEY` est présent.


## 9. Changements récents effectués (par rapport à l'état initial)
- `ai_config.py` : instanciation paresseuse (lazy) des clients IA, préférence Deepseek par défaut si clé présente, purge cache clients lors de `reload_model_settings`, chmod skipped on Windows.
- `telegram_bot.py` : defensive init — skip setup if `TELEGRAM_BOT_TOKEN` absent; controlled by `RUN_TELEGRAM_BOT`.
- `app.py` : fallback `sqlite:///dev.sqlite3` when no DB URI configured.
- `whatsapp_bot.py`, `memory_consolidator.py` : réduction des imports top-level causeurs de circular import (imports locaux là où nécessaire).
- Ajout de `scripts/test_ai_client.py` pour vérifier localement la création du client IA.


## 10. Recommandations & prochains travaux
- Sécuriser les variables d'environnement (ne pas commit les clés). Documenter les secrets dans un `ENV_VARS.md`.
- Ajouter des tests unitaires pour `ai_config.get_ai_client()` et `ai_utils.execute_chat_completion()` (mock clients).
- Ajouter des endpoints healthcheck (DB, IA backend ping) pour monitoring.
- Revoir et durcir la logique d'auth/admin (CSRF, protections API admin).
- Optionnel : améliorer la gestion de l'activation/désactivation des bots et masquer les routes webhooks si non activés.


---
_Fichier généré automatiquement par l'assistant — situé à la racine du projet (`SPEC.md`)._
