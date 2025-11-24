/**
 * Module d'enregistrement audio pour Exô
 * Version corrigée - Intégration avec Socket.IO
 */

class AudioRecorder {
    constructor() {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.stream = null;
    }

    /**
     * Démarre l'enregistrement audio
     */
    async startRecording() {
        try {
            console.log('🎙️ Demande d\'accès au microphone...');
            
            // Demander l'accès au microphone
            this.stream = await navigator.mediaDevices.getUserMedia({ 
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    sampleRate: 44100
                } 
            });
            
            // Créer le MediaRecorder
            const options = { mimeType: 'audio/webm' };
            
            // Vérifier les types MIME supportés
            if (!MediaRecorder.isTypeSupported(options.mimeType)) {
                console.warn('audio/webm non supporté, utilisation du type par défaut');
                this.mediaRecorder = new MediaRecorder(this.stream);
            } else {
                this.mediaRecorder = new MediaRecorder(this.stream, options);
            }
            
            this.audioChunks = [];
            
            // Événement: données audio disponibles
            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };
            
            // Événement: enregistrement arrêté
            this.mediaRecorder.onstop = () => {
                console.log('🎙️ Enregistrement arrêté');
                this.onRecordingComplete();
            };
            
            // Démarrer l'enregistrement
            this.mediaRecorder.start();
            this.isRecording = true;
            
            console.log('✅ Enregistrement démarré');
            return true;
        } catch (error) {
            console.error('❌ Erreur lors du démarrage de l\'enregistrement:', error);
            this.showError('Impossible d\'accéder au microphone. Vérifiez les permissions.');
            return false;
        }
    }

    /**
     * Arrête l'enregistrement audio
     */
    stopRecording() {
        if (this.mediaRecorder && this.isRecording) {
            console.log('⏹️ Arrêt de l\'enregistrement...');
            this.mediaRecorder.stop();
            this.isRecording = false;
            
            // Arrêter le stream
            if (this.stream) {
                this.stream.getTracks().forEach(track => track.stop());
            }
        }
    }

    /**
     * Appelé lorsque l'enregistrement est terminé
     */
    async onRecordingComplete() {
        try {
            // Créer un blob audio à partir des chunks
            const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
            
            console.log(`📦 Audio enregistré: ${(audioBlob.size / 1024).toFixed(2)} KB`);
            
            // Afficher le statut de traitement
            this.showProcessingStatus('Transcription en cours...');
            
            // Envoyer l'audio au serveur
            await this.uploadAudio(audioBlob);
            
        } catch (error) {
            console.error('❌ Erreur lors du traitement de l\'enregistrement:', error);
            this.showError('Erreur lors du traitement de l\'enregistrement');
        }
    }

    /**
     * Upload l'audio vers le serveur
     */
    async uploadAudio(audioBlob) {
        try {
            const formData = new FormData();
            formData.append('audio', audioBlob, 'recording.webm');
            
            console.log('📤 Envoi de l\'audio au serveur...');
            
            const response = await fetch('/api/audio/upload', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (result.success) {
                console.log('✅ Audio traité avec succès');
                
                // Afficher le résultat dans le chat
                this.displayAudioResult(result);
                
                // Cacher le statut de traitement
                this.hideProcessingStatus();
            } else {
                console.error('❌ Erreur serveur:', result.error);
                this.showError(result.error || 'Erreur lors du traitement');
            }
            
        } catch (error) {
            console.error('❌ Erreur lors de l\'upload:', error);
            this.showError('Erreur lors de l\'envoi de l\'audio');
        }
    }

    /**
     * Affiche le résultat dans le chat en utilisant la structure existante
     */
    displayAudioResult(result) {
        const { improved_text, transcript, warning } = result;
        
        // Cacher l'écran de bienvenue s'il est visible
        const welcomeContainer = document.querySelector('.welcome-container');
        if (welcomeContainer) {
            welcomeContainer.style.display = 'none';
        }
        
        // Cacher les suggestions (Aide aux devoirs, etc.)
        const suggestionsContainer = document.querySelector('.suggestions-container');
        if (suggestionsContainer) {
            suggestionsContainer.style.display = 'none';
        }
        
        // S'assurer que le chat-container est visible
        const chatContainer = document.querySelector('.chat-container');
        if (chatContainer) {
            chatContainer.classList.remove('initially-hidden');
        }
        
        // Récupérer le conteneur des messages
        const messagesContainer = document.querySelector('.chat-messages');
        if (!messagesContainer) {
            console.error('Container de messages introuvable');
            return;
        }
        
        // Ajouter le message utilisateur (audio)
        const userMessageDiv = document.createElement('div');
        userMessageDiv.className = 'message user';
        userMessageDiv.innerHTML = `
            <div class="message-content">
                🎙️ <em>[Cours vocal enregistré]</em>
            </div>
        `;
        messagesContainer.appendChild(userMessageDiv);
        
        // Ajouter le message assistant (cours amélioré)
        const assistantMessageDiv = document.createElement('div');
        assistantMessageDiv.className = 'message assistant';
        
        let content = improved_text || transcript;
        if (warning) {
            content = `<div style="color: #ff9800; margin-bottom: 10px;">⚠️ ${warning}</div>${content}`;
        }
        
        assistantMessageDiv.innerHTML = `
            <div class="message-content">
                ${this.formatMessage(content)}
            </div>
            <div class="message-feedback">
                <button class="feedback-btn thumbs-up" data-feedback-type="positive">
                    <i class="bi bi-hand-thumbs-up"></i>
                </button>
                <button class="feedback-btn thumbs-down" data-feedback-type="negative">
                    <i class="bi bi-hand-thumbs-down"></i>
                </button>
            </div>
        `;
        messagesContainer.appendChild(assistantMessageDiv);
        
        // Scroller vers le bas
        this.scrollToBottom();
    }

    /**
     * Formate le message (convertit les sauts de ligne, etc.)
     */
    formatMessage(text) {
        // Convertir les sauts de ligne en <br>
        return text.replace(/\n/g, '<br>');
    }

    /**
     * Scroll vers le bas du chat
     */
    scrollToBottom() {
        const chatViewport = document.querySelector('.chat-viewport');
        if (chatViewport) {
            setTimeout(() => {
                chatViewport.scrollTop = chatViewport.scrollHeight;
            }, 100);
        }
    }

    /**
     * Affiche un message d'erreur
     */
    showError(message) {
        this.hideProcessingStatus();
        
        // Afficher une notification d'erreur
        const errorDiv = document.createElement('div');
        errorDiv.className = 'audio-error-notification';
        errorDiv.innerHTML = `
            <i class="bi bi-exclamation-triangle"></i>
            <span>${message}</span>
        `;
        
        document.body.appendChild(errorDiv);
        
        setTimeout(() => {
            errorDiv.remove();
        }, 5000);
    }

    /**
     * Affiche le statut de traitement
     */
    showProcessingStatus(message) {
        let statusDiv = document.getElementById('audio-processing-status');
        
        if (!statusDiv) {
            statusDiv = document.createElement('div');
            statusDiv.id = 'audio-processing-status';
            statusDiv.className = 'audio-processing-status';
            document.querySelector('.chat-container').appendChild(statusDiv);
        }
        
        statusDiv.innerHTML = `
            <div class="processing-spinner"></div>
            <span>${message}</span>
        `;
        statusDiv.style.display = 'flex';
    }

    /**
     * Cache le statut de traitement
     */
    hideProcessingStatus() {
        const statusDiv = document.getElementById('audio-processing-status');
        if (statusDiv) {
            statusDiv.style.display = 'none';
        }
    }
}

// Instance globale du recorder
let audioRecorder = null;

/**
 * Initialise l'enregistreur audio
 */
function initAudioRecorder() {
    audioRecorder = new AudioRecorder();
    
    // Bouton d'enregistrement
    const recordButton = document.getElementById('audio-record-btn');
    
    if (recordButton) {
        recordButton.addEventListener('click', toggleRecording);
    }
}

/**
 * Toggle l'enregistrement audio
 */
function toggleRecording() {
    if (!audioRecorder) {
        audioRecorder = new AudioRecorder();
    }
    
    const recordButton = document.getElementById('audio-record-btn');
    
    if (audioRecorder.isRecording) {
        // Arrêter l'enregistrement
        audioRecorder.stopRecording();
        recordButton.classList.remove('recording');
        recordButton.innerHTML = '<i class="bi bi-mic"></i>';
        recordButton.title = 'Enregistrer un cours vocal';
    } else {
        // Démarrer l'enregistrement
        audioRecorder.startRecording().then(success => {
            if (success) {
                recordButton.classList.add('recording');
                recordButton.innerHTML = '<i class="bi bi-stop-circle"></i>';
                recordButton.title = 'Arrêter l\'enregistrement';
            }
        });
    }
}

// Initialiser au chargement de la page
document.addEventListener('DOMContentLoaded', initAudioRecorder);
