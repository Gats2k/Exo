# Utiliser une image Python 3.11 optimisée (slim)
FROM python:3.11-slim

# Empêcher Python de mettre en buffer stdout/stderr (bonne pratique pour les logs)
ENV PYTHONUNBUFFERED True

# Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Copier uniquement requirements.txt pour profiter du cache Docker
COPY requirements.txt .

# Installer les dépendances Python
# --no-cache-dir réduit la taille de l'image
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste du code de l'application dans le répertoire de travail /app
COPY . .

# Définir la variable d'environnement PORT (utilisée par Cloud Run et Gunicorn)
ENV PORT 8080

# Indiquer à Docker que le conteneur écoutera sur le port 8080
EXPOSE 8080

# Commande pour lancer l'application avec Gunicorn et Eventlet (pour Flask-SocketIO)
# --bind :$PORT écoute sur toutes les interfaces sur le port défini par ENV PORT
# --workers 1 est souvent recommandé pour Cloud Run (qui gère la mise à l'échelle)
# --worker-class eventlet est nécessaire pour Flask-SocketIO
# app:app pointe vers la variable 'app' dans le fichier 'app.py'
CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--worker-class", "eventlet", "app:app"]