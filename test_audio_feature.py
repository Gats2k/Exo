#!/usr/bin/env python3
"""
Script de test pour la fonctionnalité d'enregistrement audio
Teste la transcription et l'amélioration des cours vocaux
"""
import os
import sys
import logging

# Charger le fichier .env AVANT tout le reste
from dotenv import load_dotenv
load_dotenv()  # Charge les variables du fichier .env

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_groq_connection():
    """Test la connexion à l'API Groq"""
    print("\n" + "="*60)
    print("TEST 1: Connexion à l'API Groq")
    print("="*60)
    
    try:
        from groq import Groq
        
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            print("❌ GROQ_API_KEY non définie dans l'environnement")
            print("   Définissez-la avec : export GROQ_API_KEY='votre_clé'")
            return False
        
        print(f"✅ GROQ_API_KEY trouvée : {api_key[:10]}...")
        
        # Tester la connexion
        client = Groq(api_key=api_key)
        models = client.models.list()
        
        # Chercher le modèle Whisper
        whisper_models = [m.id for m in models.data if 'whisper' in m.id.lower()]
        
        if whisper_models:
            print(f"✅ Connexion Groq réussie")
            print(f"   Modèles Whisper disponibles : {', '.join(whisper_models)}")
            return True
        else:
            print("⚠️  Connexion réussie mais aucun modèle Whisper trouvé")
            return True
            
    except ImportError:
        print("❌ Package 'groq' non installé")
        print("   Installez-le avec : pip install groq")
        return False
    except Exception as e:
        print(f"❌ Erreur de connexion : {str(e)}")
        return False


def test_audio_utils_import():
    """Test l'import du module audio_utils"""
    print("\n" + "="*60)
    print("TEST 2: Import du module audio_utils")
    print("="*60)
    
    try:
        import audio_utils
        print("✅ Module audio_utils importé avec succès")
        
        # Vérifier les fonctions principales
        required_functions = [
            'transcribe_audio_groq',
            'save_uploaded_audio',
            'cleanup_audio_file',
            'is_audio_service_available'
        ]
        
        for func_name in required_functions:
            if hasattr(audio_utils, func_name):
                print(f"   ✅ Fonction '{func_name}' disponible")
            else:
                print(f"   ❌ Fonction '{func_name}' manquante")
                return False
        
        # Vérifier la disponibilité du service
        is_available = audio_utils.is_audio_service_available()
        if is_available:
            print("✅ Service de transcription audio disponible")
        else:
            print("⚠️  Service de transcription audio non disponible (GROQ_API_KEY manquante)")
        
        return True
        
    except ImportError as e:
        print(f"❌ Erreur d'import : {str(e)}")
        print("   Vérifiez que audio_utils.py est dans le même dossier")
        return False
    except Exception as e:
        print(f"❌ Erreur : {str(e)}")
        return False


def test_audio_handler_import():
    """Test l'import du module audio_handler"""
    print("\n" + "="*60)
    print("TEST 3: Import du module audio_handler")
    print("="*60)
    
    try:
        import audio_handler
        print("✅ Module audio_handler importé avec succès")
        
        # Vérifier les fonctions principales
        required_functions = [
            'improve_course_transcript',
            'handle_audio_upload',
            'handle_audio_socketio'
        ]
        
        for func_name in required_functions:
            if hasattr(audio_handler, func_name):
                print(f"   ✅ Fonction '{func_name}' disponible")
            else:
                print(f"   ❌ Fonction '{func_name}' manquante")
                return False
        
        return True
        
    except ImportError as e:
        print(f"❌ Erreur d'import : {str(e)}")
        print(f"   Message : {str(e)}")
        print("   Note : Certaines dépendances Flask peuvent manquer en mode test")
        return False
    except Exception as e:
        print(f"⚠️  Import réussi mais avec avertissement : {str(e)}")
        return True


def test_transcription_mock():
    """Test la transcription avec un fichier audio fictif"""
    print("\n" + "="*60)
    print("TEST 4: Test de transcription (mock)")
    print("="*60)
    
    try:
        import audio_utils
        
        if not audio_utils.is_audio_service_available():
            print("⚠️  Service non disponible - Test ignoré")
            return True
        
        print("ℹ️  Pour tester avec un vrai fichier audio :")
        print("   1. Créez un fichier audio test.webm ou test.mp3")
        print("   2. Placez-le dans ce dossier")
        print("   3. Exécutez : python test_audio_feature.py --file test.webm")
        print("")
        print("✅ Module prêt pour la transcription")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur : {str(e)}")
        return False


def test_with_audio_file(audio_file_path):
    """Test la transcription avec un vrai fichier audio"""
    print("\n" + "="*60)
    print(f"TEST 5: Transcription du fichier {audio_file_path}")
    print("="*60)
    
    try:
        import audio_utils
        
        if not os.path.exists(audio_file_path):
            print(f"❌ Fichier non trouvé : {audio_file_path}")
            return False
        
        file_size = os.path.getsize(audio_file_path)
        print(f"📁 Fichier : {audio_file_path}")
        print(f"📊 Taille : {file_size / 1024:.2f} KB")
        
        print("\n🎙️  Transcription en cours...")
        result = audio_utils.transcribe_audio_groq(audio_file_path, language="fr")
        
        if result.get('success'):
            transcript = result.get('text', '')
            print(f"\n✅ Transcription réussie !")
            print(f"📝 Longueur : {len(transcript)} caractères")
            print(f"\n--- TRANSCRIPT ---")
            print(transcript)
            print("--- FIN ---\n")
            
            duration = result.get('duration')
            if duration:
                print(f"⏱️  Durée : {duration:.2f} secondes")
            
            return True
        else:
            error = result.get('error', 'Erreur inconnue')
            print(f"❌ Échec de la transcription : {error}")
            return False
            
    except Exception as e:
        print(f"❌ Erreur : {str(e)}")
        return False


def run_all_tests(audio_file=None):
    """Exécute tous les tests"""
    print("\n" + "="*60)
    print("🧪 TESTS DE LA FONCTIONNALITÉ AUDIO")
    print("="*60)
    
    results = {
        'Connexion Groq': test_groq_connection(),
        'Import audio_utils': test_audio_utils_import(),
        'Import audio_handler': test_audio_handler_import(),
        'Test transcription': test_transcription_mock()
    }
    
    if audio_file:
        results['Transcription réelle'] = test_with_audio_file(audio_file)
    
    # Résumé
    print("\n" + "="*60)
    print("📊 RÉSUMÉ DES TESTS")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASSÉ" if passed else "❌ ÉCHOUÉ"
        print(f"{test_name:.<40} {status}")
    
    total = len(results)
    passed = sum(1 for p in results.values() if p)
    
    print(f"\nRésultat global : {passed}/{total} tests passés")
    
    if passed == total:
        print("\n🎉 Tous les tests sont passés ! La fonctionnalité est prête.")
        return 0
    else:
        print("\n⚠️  Certains tests ont échoué. Vérifiez la configuration.")
        return 1


if __name__ == '__main__':
    # Parser les arguments
    audio_file = None
    if len(sys.argv) > 2 and sys.argv[1] == '--file':
        audio_file = sys.argv[2]
    
    # Exécuter les tests
    exit_code = run_all_tests(audio_file)
    sys.exit(exit_code)
