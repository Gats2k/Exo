#!/usr/bin/env python3
# Script pour le déploiement avec Gunicorn
# Il tente d'abord le mode Eventlet, puis le mode standard si nécessaire

import os
import subprocess
import sys
import time
import signal

# Variable globale pour le processus Gunicorn
gunicorn_process = None

def signal_handler(sig, frame):
    """Gestionnaire de signal pour arrêter proprement Gunicorn"""
    global gunicorn_process
    if gunicorn_process:
        print("Arrêt de Gunicorn...")
        gunicorn_process.terminate()
    sys.exit(0)

def run_with_eventlet():
    """Exécute l'application avec Gunicorn et Eventlet"""
    global gunicorn_process
    
    os.environ['PYTHONUNBUFFERED'] = '1'  # Assure que les logs sont écrits immédiatement
    os.environ['EVENTLET_NO_GREENDNS'] = '1'  # Évite certains problèmes avec eventlet
    
    try:
        # Lance Gunicorn avec la class worker Eventlet
        cmd = [
            "gunicorn",
            "--worker-class", "eventlet",
            "--workers", "1",
            "--bind", "0.0.0.0:5000",
            "--log-level", "debug",
            "--keep-alive", "60",
            "--timeout", "300",
            "--access-logfile", "-",
            "--error-logfile", "-",
            "--forwarded-allow-ips", "*",
            "wsgi:application"
        ]
        
        print(f"Tentative de lancement avec Eventlet: {' '.join(cmd)}")
        gunicorn_process = subprocess.Popen(cmd)
        
        # Attendre quelques secondes pour voir si le processus reste actif
        time.sleep(5)
        
        # Vérifier si le processus est toujours en cours d'exécution
        if gunicorn_process.poll() is None:
            print("Gunicorn avec Eventlet fonctionne correctement")
            return True
        else:
            print("Échec du lancement avec Eventlet, code de sortie:", gunicorn_process.returncode)
            return False
    except Exception as e:
        print(f"Erreur lors du lancement de Gunicorn avec Eventlet: {e}")
        return False

def run_with_standard():
    """Exécute l'application avec Gunicorn standard (sans eventlet)"""
    global gunicorn_process
    
    os.environ['PYTHONUNBUFFERED'] = '1'
    os.environ['GUNICORN_DEPLOYMENT'] = 'standard'  # Indique au wsgi.py d'utiliser le mode standard
    
    try:
        # Lance Gunicorn en mode standard
        cmd = [
            "gunicorn",
            "--workers", "2",
            "--bind", "0.0.0.0:5000",
            "--log-level", "debug",
            "--access-logfile", "-",
            "--error-logfile", "-",
            "--forwarded-allow-ips", "*",
            "wsgi:application"
        ]
        
        print(f"Lancement en mode standard: {' '.join(cmd)}")
        gunicorn_process = subprocess.Popen(cmd)
        
        # Attendre indéfiniment que le processus se termine
        gunicorn_process.wait()
        return True
    except Exception as e:
        print(f"Erreur lors du lancement de Gunicorn standard: {e}")
        return False

if __name__ == "__main__":
    # Configurer le gestionnaire de signal pour SIGINT (Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Essayer d'abord avec eventlet
    if not run_with_eventlet():
        print("Mode eventlet échoué, passage au mode standard")
        
        # Si eventlet échoue, essayer avec le mode standard
        if not run_with_standard():
            print("Échec du déploiement en mode standard également")
            sys.exit(1)
    else:
        # Si eventlet réussit, attendre indéfiniment
        try:
            gunicorn_process.wait()
        except KeyboardInterrupt:
            print("Arrêt du serveur...")
            gunicorn_process.terminate()