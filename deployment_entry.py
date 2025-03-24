#!/usr/bin/env python3
"""
Point d'entrée pour le déploiement qui contourne les problèmes de sockets non-bloquants
avec Gunicorn standard
"""

import os
import sys

# Configuration du mode de déploiement
os.environ['DEPLOYMENT_MODE'] = 'true'
os.environ['GUNICORN_DEPLOYMENT'] = 'standard'
os.environ['SOCKETIO_MODE'] = 'threading'  # Forcer le mode threading au lieu d'eventlet

# Importer l'application Flask
from app import app

# Cette variable est utilisée par Gunicorn
application = app

if __name__ == "__main__":
    # Exécuter directement l'application Flask sans SocketIO
    # Cela est utilisé uniquement pour les tests
    print("Lancement en mode direct (sans SocketIO)")
    app.run(host="0.0.0.0", port=5000, debug=True)