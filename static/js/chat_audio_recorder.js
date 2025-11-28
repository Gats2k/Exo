/**
 * Module d'enregistrement audio pour le chat - Exô
 * Mode Dictée Simple : Enregistre et transcrit directement dans la zone de saisie
 */

class ChatAudioRecorder {
    constructor() {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.stream = null;

        // Éléments DOM
        this.audioRecordBtn = document.getElementById('audioRecordBtn');
        this.chatInput = document.querySelector('.input-container textarea');

        // Icônes
        this.micIcon = '<i class="bi bi-mic"></i>';
        this.stopIcon = '<i class="bi bi-stop-fill" style="color: #EF4444;"></i>';
        this.loadingIcon = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';

        this.init();
    }

    init() {
        console.log('🎙️ ChatAudioRecorder (Mode Dictée) initialisé');

        if (this.audioRecordBtn) {
            // Supprimer les anciens écouteurs (si possible, sinon le remplacement du fichier suffit)
            const newBtn = this.audioRecordBtn.cloneNode(true);
            this.audioRecordBtn.parentNode.replaceChild(newBtn, this.audioRecordBtn);
            this.audioRecordBtn = newBtn;

            this.audioRecordBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggleRecording();
            });
        }
    }

    async toggleRecording() {
        if (this.isRecording) {
            this.stopRecording();
        } else {
            await this.startRecording();
        }
    }

    async startRecording() {
        try {
            console.log('🎙️ Démarrage de la dictée...');

            // Demander l'accès au microphone
            this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            this.mediaRecorder = new MediaRecorder(this.stream);
            this.audioChunks = [];

            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };

            this.mediaRecorder.onstop = () => {
                this.transcribeAudio();
            };

            this.mediaRecorder.start();
            this.isRecording = true;
            this.updateButtonState('recording');
            console.log('✅ Enregistrement en cours');

        } catch (error) {
            console.error('❌ Erreur micro:', error);
            alert('Impossible d\'accéder au microphone.');
        }
    }

    stopRecording() {
        if (this.mediaRecorder && this.isRecording) {
            console.log('⏹️ Arrêt de l\'enregistrement...');
            this.mediaRecorder.stop();
            this.isRecording = false;

            // Arrêter le stream
            if (this.stream) {
                this.stream.getTracks().forEach(track => track.stop());
            }

            this.updateButtonState('loading');
        }
    }

    async transcribeAudio() {
        const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('audio', audioBlob, 'dictation.webm');

        try {
            console.log('📤 Envoi pour transcription...');

            const response = await fetch('/api/transcribe-only', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                console.log('✅ Transcription reçue:', result.transcript);
                this.insertText(result.transcript);
            } else {
                console.error('❌ Erreur transcription:', result.error);
                alert('Erreur de transcription: ' + result.error);
            }

        } catch (error) {
            console.error('❌ Erreur réseau:', error);
            alert('Erreur lors de l\'envoi de l\'audio.');
        } finally {
            this.updateButtonState('idle');
        }
    }

    insertText(text) {
        if (!this.chatInput) return;

        const startPos = this.chatInput.selectionStart;
        const endPos = this.chatInput.selectionEnd;
        const currentValue = this.chatInput.value;

        // Insérer le texte à la position du curseur ou à la fin
        const newValue = currentValue.substring(0, startPos) +
            (currentValue.length > 0 && startPos > 0 ? ' ' : '') +
            text +
            currentValue.substring(endPos);

        this.chatInput.value = newValue;

        // Mettre à jour la hauteur du textarea
        this.chatInput.style.height = 'auto';
        this.chatInput.style.height = (this.chatInput.scrollHeight) + 'px';

        // Focus et placer le curseur à la fin du texte inséré
        this.chatInput.focus();
        const newCursorPos = startPos + text.length + (currentValue.length > 0 && startPos > 0 ? 1 : 0);
        this.chatInput.setSelectionRange(newCursorPos, newCursorPos);
    }

    updateButtonState(state) {
        if (!this.audioRecordBtn) return;

        switch (state) {
            case 'recording':
                this.audioRecordBtn.innerHTML = this.stopIcon;
                this.audioRecordBtn.classList.add('recording-active');
                this.audioRecordBtn.style.animation = 'pulse 1.5s infinite';
                break;
            case 'loading':
                this.audioRecordBtn.innerHTML = this.loadingIcon;
                this.audioRecordBtn.classList.remove('recording-active');
                this.audioRecordBtn.style.animation = 'none';
                break;
            case 'idle':
            default:
                this.audioRecordBtn.innerHTML = this.micIcon;
                this.audioRecordBtn.classList.remove('recording-active');
                this.audioRecordBtn.style.animation = 'none';
                break;
        }
    }
}

// Styles CSS pour l'animation de pulsation (à ajouter dynamiquement)
const style = document.createElement('style');
style.textContent = `
    @keyframes pulse {
        0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
        70% { transform: scale(1.1); box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
        100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
    }
    .recording-active {
        color: #EF4444 !important;
        background-color: rgba(239, 68, 68, 0.1) !important;
    }
`;
document.head.appendChild(style);

// Initialisation
function initChatAudioRecorder() {
    window.chatAudioRecorder = new ChatAudioRecorder();
}

window.initChatAudioRecorder = initChatAudioRecorder;
