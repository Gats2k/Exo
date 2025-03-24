#!/usr/bin/env python3
# Script pour le déploiement avec Gunicorn et Eventlet

import os
import subprocess
import sys

def run_with_gunicorn():
    """Exécute l'application avec Gunicorn et Eventlet"""
    os.environ['PYTHONUNBUFFERED'] = '1'  # Assure que les logs sont écrits immédiatement
    
    # Définir des configurations supplémentaires pour éviter les problèmes de sockets
    os.environ['EVENTLET_NO_GREENDNS'] = '1'
    
    try:
        # Lance Gunicorn avec la class worker Eventlet et des configurations optimisées
        cmd = [
            "gunicorn",
            "--worker-class", "eventlet",
            "--workers", "1",
            "--bind", "0.0.0.0:5000",
            "--log-level", "debug",
            "--keep-alive", "60",
            "--timeout", "300",
            "--access-logfile", "-",  # logs directement vers stdout
            "--error-logfile", "-",   # logs d'erreur vers stderr
            "--preload",              # précharger l'application
            "--forwarded-allow-ips", "*",  # Supporte les proxys pour les en-têtes X-Forwarded-*
            "wsgi:application"
        ]
        
        print(f"Lancement de la commande: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
    except Exception as e:
        print(f"Erreur lors du lancement de Gunicorn: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Démarre l'application avec Gunicorn
    run_with_gunicorn()