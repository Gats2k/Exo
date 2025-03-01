import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, jsonify, url_for
from flask_socketio import SocketIO, emit
from openai import OpenAI
import os
from dotenv import load_dotenv
import uuid
from werkzeug.utils import secure_filename
import base64
from io import BytesIO
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import shutil

# Charger les variables d'environnement
load_dotenv()

# Configuration
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Configurations pour le nettoyage des images
MAX_UPLOAD_FOLDER_SIZE = 500 * 1024 * 1024  # 500 MB
IMAGE_MAX_AGE_HOURS = 24  # Durée de conservation des images

# Initialize Flask app
app = Flask(name)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Créer le dossier uploads s'il n'existe pas
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize SocketIO
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_base64_image(base64_string):
    # Extraire le type de l'image et les données
    header, encoded = base64_string.split(",", 1)

    # Générer un nom de fichier unique
    filename = f"{uuid.uuid4()}.jpg"

    # Décoder l'image
    img_data = base64.b64decode(encoded)

    # Sauvegarder l'image
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    with open(filepath, "wb") as f:
        f.write(img_data)

    return filename

def cleanup_uploads():
    """Nettoie le dossier uploads des images anciennes et vérifie la taille totale"""
    try:
        # Supprimer les fichiers plus vieux que IMAGE_MAX_AGE_HOURS
        current_time = datetime.now()
        for filename in os.listdir(UPLOAD_FOLDER):
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
            if current_time - file_modified > timedelta(hours=IMAGE_MAX_AGE_HOURS):
                os.remove(filepath)

        # Vérifier la taille totale du dossier
        total_size = sum(os.path.getsize(os.path.join(UPLOAD_FOLDER, f)) 
                        for f in os.listdir(UPLOAD_FOLDER))

        # Si la taille dépasse la limite, supprimer les fichiers les plus anciens
        if total_size > MAX_UPLOAD_FOLDER_SIZE:
            files = [(os.path.join(UPLOAD_FOLDER, f), os.path.getmtime(os.path.join(UPLOAD_FOLDER, f))) 
                    for f in os.listdir(UPLOAD_FOLDER)]
            files.sort(key=lambda x: x[1])  # Trier par date de modification

            for filepath, _ in files:
                os.remove(filepath)
                total_size = sum(os.path.getsize(os.path.join(UPLOAD_FOLDER, f)) 
                               for f in os.listdir(UPLOAD_FOLDER))
                if total_size <= MAX_UPLOAD_FOLDER_SIZE:
                    break

    except Exception as e:
        print(f"Erreur lors du nettoyage des uploads: {str(e)}")

@app.route('/')
def chat():
    history = []
    return render_template('chat.html', history=history, credits=42)

@socketio.on('send_message')
def handle_message(data):
    try:
        # Create thread for conversation
        thread = client.beta.threads.create()

        # Create message content based on whether there's an image or text or both
        message_content = []

        # Add image if present
        if 'image' in data and data['image']:
            # Sauvegarder l'image et obtenir le nom du fichier
            filename = save_base64_image(data['image'])

            # Construire l'URL complète
            image_url = request.url_root.rstrip('/') + url_for('static', filename=f'uploads/{filename}')

            message_content.append({
                "type": "image_url",
                "image_url": {
                    "url": image_url
                }
            })

        # Add text if present
        if 'message' in data and data['message'].strip():
            message_content.append({
                "type": "text",
                "text": data['message']
            })

        # Add message to thread
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=message_content
        )

        # Create a run using the existing assistant
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        )

        # Wait for response
        while True:
            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            if run_status.status == 'completed':
                break
            elif run_status.status == 'failed':
                emit('receive_message', {'message': 'Sorry, there was an error.'})
                return

        # Retrieve the answer
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        assistant_message = messages.data[0].content[0].text.value
        emit('receive_message', {'message': assistant_message})

    except Exception as e:
        emit('receive_message', {'message': f'Error: {str(e)}'})

    if __name__ == '__main__':
        # Configurer le scheduler pour le nettoyage
        scheduler = BackgroundScheduler()
        scheduler.add_job(func=cleanup_uploads, 
                         trigger="interval", 
                         hours=1,  # Exécuter toutes les heures
                         id='cleanup_job')
        scheduler.start()

        try:
            socketio.run(app, host='0.0.0.0', port=5000, debug=True)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()