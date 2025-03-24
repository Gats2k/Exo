#!/usr/bin/env python3
"""
Point d'entrée pour le déploiement qui utilise Flask directement sans SocketIO
pour résoudre les problèmes de sockets non-bloquants avec Gunicorn
"""

import os
import sys
import logging

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration du mode de déploiement
os.environ['DEPLOYMENT_MODE'] = 'true'
os.environ['DISABLE_SOCKETIO'] = 'true'  # Désactive complètement SocketIO en production

try:
    # Importer l'application Flask directement, pas SocketIO
    from app import app
    
    # Désactiver la fonctionnalité SocketIO pour le déploiement
    logger.info("Application chargée en mode déploiement sans SocketIO")
    
    # Cette variable est utilisée par Gunicorn
    application = app
    
except Exception as e:
    logger.error(f"Erreur lors du chargement de l'application: {str(e)}", exc_info=True)
    raise

if __name__ == "__main__":
    # Exécuter directement l'application Flask sans SocketIO
    # Cela est utilisé uniquement pour les tests
    logger.info("Lancement en mode direct (sans SocketIO)")
    app.run(host="0.0.0.0", port=5000, debug=True)