# SPEC — Exô (Assistant Éducatif)

## 1. Aperçu du projet
Exô est une plateforme d'assistance éducative multi-plateforme qui fournit des réponses pédagogiques et de l'aide aux élèves via :
- Interface Web (Flask + Socket.IO)
- Bots Telegram et WhatsApp
- Un moteur IA interchangeable (Deepseek, OpenAI Assistants, Qwen, Gemini)

Fonctionnalités clés : gestion des conversations, upload d'images (OCR + vision), suivi mémoire utilisateur (profil pédagogique), gestion d'abonnements/paiement, tâches planifiées pour consolidation et rappels, rendu Markdown des réponses IA, dictée vocale (Speech-to-Text), enregistrement et transcription de cours.


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
- `lesson` : leçons enregistrées (audio, transcriptions, matière, statut de traitement, **images capturées avec OCR**).
- `message_feedback` : feedbacks utilisateur (pouces levés/baissés) sur les réponses IA.


## 3.1. Stockage des données

### 📍 Base de données principale
**Localisation** : `d:\2K\instance\dev.sqlite3`

**Type** : SQLite (fichier local `.sqlite3`)

**Configuration** : Définie dans `app.py` (lignes 59-67). Si aucune variable `DATABASE_URL` n'est fournie, l'application utilise automatiquement `sqlite:///dev.sqlite3` pour le développement local.

**Contenu** :
- **Utilisateurs** : Comptes web, Telegram, WhatsApp avec informations d'authentification
- **Conversations** : Historique complet des échanges avec l'IA (titres, horodatages, contexte)
- **Messages** : Contenu textuel, images envoyées, rôles (user/assistant)
- **Leçons** : Enregistrements audio de cours avec transcriptions originales et versions améliorées par l'IA, organisés par matière (Mathématiques, Physique, Chimie, SVT)
- **Feedbacks** : Évaluations utilisateur (👍/👎) sur les réponses de l'IA
- **Abonnements** : Statuts Premium, transactions, plans tarifaires
- **Mémoire utilisateur** : Profils pédagogiques, sujets récents pour personnalisation

### 📂 Fichiers temporaires et uploads
- **Images utilisateur** : `d:\2K\static\uploads/` (stockage temporaire des images envoyées dans le chat)
- **Images de leçons** : `d:\2K\static\uploads\lessons/` (stockage permanent des captures de cours avec métadonnées OCR en base de données)
- **Audio temporaire** : `C:\Users\omen\AppData\Local\Temp\` (fichiers audio nettoyés automatiquement après transcription)

### 🔄 Migration vers production
**Important** : SQLite est adapté au développement local mais **non recommandé pour la production**. Pour un déploiement avec plusieurs utilisateurs simultanés, migrer vers :
- **PostgreSQL** (recommandé) : Meilleure gestion de la concurrence, performances optimales
- **MySQL/MariaDB** : Alternative viable

La migration est facilitée par Flask-Migrate (Alembic) déjà intégré au projet.


## 4. Variables d'environnement importantes
- IA / modèles :
  - `CURRENT_MODEL` (openai | deepseek | deepseek-reasoner | qwen | gemini)
  - `DEEPSEEK_API_KEY`
  - `OPENAI_API_KEY`
  - `GEMINI_API_KEY`
  - `DASHSCOPE_API_KEY` (Qwen)
  - `DEEPSEEK_INSTRUCTIONS_FILE`, `DEEPSEEK_REASONER_INSTRUCTIONS_FILE`, `QWEN_INSTRUCTIONS_FILE`, `GEMINI_INSTRUCTIONS_FILE`
- OCR :
  - `MATHPIX_APP_ID` : ID de l'application Mathpix pour OCR de formules mathématiques et texte manuscrit
  - `MATHPIX_APP_KEY` : Clé API Mathpix
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
  - `/subjects` : page des matières
  - `/lessons/<subject>` : liste des leçons par matière (mathematics, physics, chemistry, svt)
  - `/lesson/<id>` : détail d'une leçon avec transcription
  - `/privacy-policy`
- API :
  - `/api/audio/upload` : upload et traitement audio complet (transcription + amélioration IA)
  - `/api/transcribe-only` : transcription simple pour dictée vocale (sans sauvegarde)
  - `/api/save-audio` : enregistrement de cours avec sélection de matière
  - `/api/lessons/<subject>` : récupération des leçons par matière
  - `/api/lesson/<id>` : récupération d'une leçon spécifique
  - `/api/lesson/<id>` (DELETE) : suppression d'une leçon
  - `/api/lesson/create-with-image` (POST) : création de leçon à partir d'une image (OCR + analyse IA)
  - `/api/lesson/<id>/add-image` (POST) : ajout d'image à une leçon existante
  - `/api/lesson/<id>/delete-image/<image_id>` (DELETE) : suppression d'une image spécifique
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
- `ai_config.py` : instanciation paresseuse (lazy) des clients IA, préférence Deepseek par défaut si clé présente, purge cache clients lors de `reload_model_settings`, chmod skipped on Windows. Ajout de contextes IA distincts (chat vs lesson) avec instructions spécifiques.
- `telegram_bot.py` : defensive init — skip setup if `TELEGRAM_BOT_TOKEN` absent; controlled by `RUN_TELEGRAM_BOT`.
- `app.py` : fallback `sqlite:///dev.sqlite3` when no DB URI configured. Ajout de `/api/transcribe-only` pour dictée vocale.
- `whatsapp_bot.py`, `memory_consolidator.py` : réduction des imports top-level causeurs de circular import (imports locaux là où nécessaire).
- Ajout de `scripts/test_ai_client.py` pour vérifier localement la création du client IA.
- **Rendu Markdown** (27/11/2025) :
  - Intégration de `marked.js` dans `chat.html` et `lesson_detail.html`
  - Création de `static/css/markdown_styles.css` pour styliser les éléments Markdown (titres, listes, code, blockquotes)
  - Modification de `main.js` : ajout de `formatMessageContent()` utilisant `marked.parse()` pour rendre le Markdown dans les messages
  - Application du rendu Markdown dans les événements `receive_message`, `response_stream`, `conversation_opened` et `checkStalledStream`
- **Dictée vocale** (27/11/2025) :
  - Transformation de `chat_audio_recorder.js` : suppression du modal complexe, enregistrement direct au clic sur le bouton micro
  - Ajout de `handle_transcribe_only()` dans `audio_handler.py` : transcription simple sans sauvegarde de leçon
  - Insertion automatique du texte transcrit dans la zone de saisie du chat
  - Ajout d'animations visuelles (pulsation rouge pendant l'enregistrement, spinner pendant la transcription)
- **Système de leçons** :
  - Création du modèle `Lesson` avec support multi-matières
  - Pages de visualisation par matière (`/lessons/<subject>`)
  - Page de détail avec lecture de transcription (`/lesson/<id>`)
  - Fonction `save_lesson_from_audio()` pour traitement complet (transcription Groq + amélioration IA)
  - Redirection intelligente après suppression avec mapping des matières
- **Capture d'images et OCR pour les leçons** (29/11/2025) :
  - **Frontend** :
    - Ajout du bouton "Ajouter une capture" sur toutes les pages de leçons (Mathématiques, Physique, Chimie, SVT)
    - Modal interactif (`lesson_image_uploader.js` + `lesson_image_uploader.css`) permettant :
      - Prévisualisation de l'image avant upload
      - Choix entre "Créer une nouvelle leçon" ou "Ajouter à une leçon existante"
      - Sélection d'une leçon existante via dropdown dynamique
      - Affichage du texte OCR extrait après traitement
    - Galerie d'images dans `lesson_detail.html` :
      - Onglet "Captures" affichant toutes les images associées à une leçon
      - Métadonnées : date d'upload, détection de formules mathématiques, détection de diagrammes
      - Modal de visualisation plein écran avec texte OCR
      - Bouton de suppression par image
  - **Backend** :
    - Intégration de **Mathpix OCR** (`mathpix_utils.py`) pour extraction de texte manuscrit/imprimé
    - Configuration avancée pour détecter : formules mathématiques, tableaux, diagrammes chimiques, schémas biologiques
    - Endpoints API :
      - `/api/lesson/create-with-image` : création de leçon à partir d'une image
      - `/api/lesson/<id>/add-image` : ajout d'image à une leçon existante
      - `/api/lesson/<id>/delete-image/<image_id>` : suppression d'image
    - **Analyse IA automatique** (`ai_utils.generate_lesson_from_ocr()`) :
      - Correction des erreurs OCR
      - Structuration du contenu en Markdown (titres, listes, paragraphes)
      - Formatage des formules scientifiques
      - Ajout d'explications pédagogiques
      - Gestion des cas où l'OCR échoue (message d'erreur explicite)
  - **Modèle de données** :
    - Ajout du champ `images` (JSON) au modèle `Lesson`
    - Structure : `[{"id": "uuid", "url": "/path", "ocr_text": "...", "has_math": bool, "has_diagram": bool, "uploaded_at": "ISO8601"}]`
    - Stockage des images dans `/static/uploads/lessons/`
  - **Variables d'environnement requises** :
    - `MATHPIX_APP_ID` : ID de l'application Mathpix
    - `MATHPIX_APP_KEY` : Clé API Mathpix
    - **Important** : Pas d'espaces autour du `=` dans le `.env`


## 10. Recommandations & prochains travaux
- Sécuriser les variables d'environnement (ne pas commit les clés). Documenter les secrets dans un `ENV_VARS.md`.
- Ajouter des tests unitaires pour `ai_config.get_ai_client()` et `ai_utils.execute_chat_completion()` (mock clients).
- Ajouter des endpoints healthcheck (DB, IA backend ping) pour monitoring.
- Revoir et durcir la logique d'auth/admin (CSRF, protections API admin).
- Optionnel : améliorer la gestion de l'activation/désactivation des bots et masquer les routes webhooks si non activés.


---
_Fichier généré automatiquement par l'assistant — situé à la racine du projet (`SPEC.md`)._
