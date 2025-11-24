/**
 * Module d'enregistrement audio pour les pages de matières - Exô
 * Gère l'enregistrement, le timer, et la sauvegarde
 */

class SubjectAudioRecorder {
    constructor(subject) {
        this.subject = subject;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.stream = null;
        this.startTime = null;
        this.timerInterval = null;

        // Éléments DOM
        this.recordButton = document.getElementById('recordButton');
        this.stopButton = document.getElementById('stopButton');
        this.saveButton = document.getElementById('saveButton');
        this.cancelButton = document.getElementById('cancelButton');
        this.timer = document.getElementById('timer');
        this.actionButtons = document.getElementById('actionButtons');
        this.saveSection = document.getElementById('saveSection');
        this.statusMessage = document.getElementById('statusMessage');

        this.init();
    }

    init() {
        // Attacher les événements
        if (this.recordButton) {
            this.recordButton.addEventListener('click', () => this.startRecording());
        }

        if (this.stopButton) {
            this.stopButton.addEventListener('click', () => this.stopRecording());
        }

        if (this.saveButton) {
            this.saveButton.addEventListener('click', () => this.saveRecording());
        }

        if (this.cancelButton) {
            this.cancelButton.addEventListener('click', () => this.cancelRecording());
        }

        console.log(`🎙️ SubjectAudioRecorder initialisé pour: ${this.subject}`);
    }

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
            this.startTime = Date.now();

            // Démarrer le timer
            this.startTimer();

            // Mettre à jour l'UI
            this.recordButton.style.display = 'none';
            this.actionButtons.style.display = 'flex';
            this.recordButton.classList.add('recording');

            console.log('✅ Enregistrement démarré');
            this.showStatus('Enregistrement en cours...', 'info');

        } catch (error) {
            console.error('❌ Erreur lors du démarrage de l\'enregistrement:', error);
            this.showStatus('Impossible d\'accéder au microphone. Vérifiez les permissions.', 'error');
        }
    }

    stopRecording() {
        if (this.mediaRecorder && this.isRecording) {
            console.log('⏹️ Arrêt de l\'enregistrement...');
            this.mediaRecorder.stop();
            this.isRecording = false;

            // Arrêter le timer
            this.stopTimer();

            // Arrêter le stream
            if (this.stream) {
                this.stream.getTracks().forEach(track => track.stop());
            }

            this.showStatus('Enregistrement terminé', 'success');
        }
    }

    onRecordingComplete() {
        // Créer un blob audio à partir des chunks
        this.audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });

        console.log(`📦 Audio enregistré: ${(this.audioBlob.size / 1024).toFixed(2)} KB`);

        // Afficher la section de sauvegarde
        this.actionButtons.style.display = 'none';
        this.saveSection.style.display = 'block';

        // Mettre à jour les infos audio
        const audioInfo = document.getElementById('audioInfo');
        if (audioInfo) {
            const duration = this.timer.textContent;
            audioInfo.textContent = `Audio enregistré (${duration})`;
        }
    }

    async saveRecording() {
        if (!this.audioBlob) {
            this.showStatus('Aucun enregistrement à sauvegarder', 'error');
            return;
        }

        try {
            this.showStatus('Sauvegarde en cours...', 'info');

            const formData = new FormData();
            formData.append('audio', this.audioBlob, 'recording.webm');
            formData.append('subject', this.subject);

            console.log(`📤 Envoi de l'audio au serveur pour ${this.subject}...`);

            const response = await fetch('/api/save-audio', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                console.log('✅ Audio sauvegardé avec succès');
                this.showStatus('✅ Cours enregistré avec succès !', 'success');

                // Réinitialiser après 2 secondes
                setTimeout(() => {
                    this.reset();
                }, 2000);
            } else {
                console.error('❌ Erreur serveur:', result.error);
                this.showStatus(result.error || 'Erreur lors de la sauvegarde', 'error');
            }

        } catch (error) {
            console.error('❌ Erreur lors de la sauvegarde:', error);
            this.showStatus('Erreur lors de l\'envoi de l\'audio', 'error');
        }
    }

    cancelRecording() {
        console.log('🗑️ Annulation de l\'enregistrement');
        this.audioBlob = null;
        this.audioChunks = [];
        this.reset();
        this.showStatus('Enregistrement annulé', 'info');
    }

    reset() {
        // Réinitialiser l'UI
        this.recordButton.style.display = 'flex';
        this.recordButton.classList.remove('recording');
        this.actionButtons.style.display = 'none';
        this.saveSection.style.display = 'none';
        this.timer.textContent = '00:00';
        this.audioBlob = null;
        this.audioChunks = [];

        // Cacher le message de statut après 3 secondes
        setTimeout(() => {
            this.statusMessage.textContent = '';
            this.statusMessage.className = 'status-message';
        }, 3000);
    }

    startTimer() {
        this.timerInterval = setInterval(() => {
            const elapsed = Date.now() - this.startTime;
            const minutes = Math.floor(elapsed / 60000);
            const seconds = Math.floor((elapsed % 60000) / 1000);
            this.timer.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
        }, 1000);
    }

    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    }

    showStatus(message, type) {
        this.statusMessage.textContent = message;
        this.statusMessage.className = `status-message ${type}`;
    }
}

// Instance globale
let subjectRecorder = null;

/**
 * Initialise l'enregistreur audio pour une matière
 * @param {string} subject - Nom de la matière (Mathématiques, Physique, etc.)
 */
function initAudioRecorder(subject) {
    if (!subject) {
        console.error('❌ Matière non spécifiée pour initAudioRecorder');
        return;
    }

    console.log(`🎯 Initialisation de l'enregistreur pour: ${subject}`);
    subjectRecorder = new SubjectAudioRecorder(subject);
}

// Export pour utilisation globale
window.initAudioRecorder = initAudioRecorder;
