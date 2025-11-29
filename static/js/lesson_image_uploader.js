/**
 * Gestionnaire d'upload d'images pour les leçons
 * Permet de créer une nouvelle leçon ou d'ajouter une image à une leçon existante
 */

class LessonImageUploader {
    constructor(subject) {
        this.subject = subject;
        this.modal = null;
        this.init();
    }

    init() {
        // Créer le bouton "Ajouter une capture"
        this.createCaptureButton();
        // Créer le modal
        this.createModal();
    }

    createCaptureButton() {
        const headerTop = document.querySelector('.header-top');
        if (!headerTop) return;

        const captureBtn = document.createElement('button');
        captureBtn.className = 'record-btn';
        captureBtn.innerHTML = '<i class="bi bi-camera"></i> Ajouter une capture';
        captureBtn.onclick = () => this.openModal();

        // Insérer après le bouton "Enregistrer un cours"
        const recordBtn = headerTop.querySelector('.record-btn');
        if (recordBtn) {
            recordBtn.parentNode.insertBefore(captureBtn, recordBtn.nextSibling);
        }
    }

    createModal() {
        const modalHTML = `
            <div id="imageUploadModal" class="image-modal-overlay" style="display: none;">
                <div class="image-modal">
                    <div class="image-modal-header">
                        <h3>Ajouter une capture de cours</h3>
                        <button class="close-modal-btn" onclick="lessonImageUploader.closeModal()">&times;</button>
                    </div>
                    <div class="image-modal-body">
                        <!-- Sélection du fichier -->
                        <div class="upload-section">
                            <label for="imageInput" class="upload-label">
                                <i class="bi bi-cloud-upload"></i>
                                <span>Cliquez pour sélectionner une image</span>
                                <input type="file" id="imageInput" accept="image/*" style="display: none;" onchange="lessonImageUploader.handleFileSelect(event)">
                            </label>
                        </div>

                        <!-- Prévisualisation -->
                        <div id="imagePreview" class="image-preview" style="display: none;">
                            <img id="previewImg" src="" alt="Aperçu">
                        </div>

                        <!-- Options -->
                        <div id="uploadOptions" class="upload-options" style="display: none;">
                            <h4>Que voulez-vous faire ?</h4>
                            <div class="option-buttons">
                                <button class="option-btn" onclick="lessonImageUploader.createNewLesson()">
                                    <i class="bi bi-plus-circle"></i>
                                    Créer une nouvelle leçon
                                </button>
                                <button class="option-btn" onclick="lessonImageUploader.showLessonSelector()">
                                    <i class="bi bi-folder-plus"></i>
                                    Ajouter à une leçon existante
                                </button>
                            </div>
                        </div>

                        <!-- Sélecteur de leçons -->
                        <div id="lessonSelector" class="lesson-selector" style="display: none;">
                            <h4>Sélectionnez une leçon</h4>
                            <select id="lessonSelect" class="lesson-select">
                                <option value="">Chargement...</option>
                            </select>
                            <button class="submit-btn" onclick="lessonImageUploader.addToExistingLesson()">
                                Ajouter l'image
                            </button>
                        </div>

                        <!-- Résultat OCR -->
                        <div id="ocrResult" class="ocr-result" style="display: none;">
                            <h4>Texte extrait (OCR)</h4>
                            <div id="ocrText" class="ocr-text"></div>
                        </div>

                        <!-- Statut -->
                        <div id="uploadStatus" class="upload-status"></div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHTML);
        this.modal = document.getElementById('imageUploadModal');
    }

    openModal() {
        this.modal.style.display = 'flex';
        this.resetModal();
    }

    closeModal() {
        this.modal.style.display = 'none';
        this.resetModal();
    }

    resetModal() {
        document.getElementById('imageInput').value = '';
        document.getElementById('imagePreview').style.display = 'none';
        document.getElementById('uploadOptions').style.display = 'none';
        document.getElementById('lessonSelector').style.display = 'none';
        document.getElementById('ocrResult').style.display = 'none';
        document.getElementById('uploadStatus').textContent = '';
        this.selectedFile = null;
    }

    handleFileSelect(event) {
        const file = event.target.files[0];
        if (!file) return;

        this.selectedFile = file;

        // Afficher la prévisualisation
        const reader = new FileReader();
        reader.onload = (e) => {
            document.getElementById('previewImg').src = e.target.result;
            document.getElementById('imagePreview').style.display = 'block';
            document.getElementById('uploadOptions').style.display = 'block';
        };
        reader.readAsDataURL(file);
    }

    async createNewLesson() {
        if (!this.selectedFile) return;

        this.showStatus('Création de la leçon en cours...', 'info');

        const formData = new FormData();
        formData.append('image', this.selectedFile);
        formData.append('subject', this.subject);

        try {
            const response = await fetch('/api/lesson/create-with-image', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                this.showStatus('✅ Leçon créée avec succès !', 'success');
                this.displayOCR(result.ocr_text);

                // Recharger la liste des leçons après 2 secondes
                setTimeout(() => {
                    window.location.reload();
                }, 2000);
            } else {
                this.showStatus(`❌ Erreur: ${result.error}`, 'error');
            }
        } catch (error) {
            this.showStatus(`❌ Erreur réseau: ${error.message}`, 'error');
        }
    }

    async showLessonSelector() {
        document.getElementById('lessonSelector').style.display = 'block';

        // Charger les leçons
        try {
            const subjectMap = {
                'Mathématiques': 'mathematics',
                'Physique': 'physics',
                'Chimie': 'chemistry',
                'SVT': 'svt'
            };
            const subjectSlug = subjectMap[this.subject] || 'mathematics';

            const response = await fetch(`/api/lessons/${subjectSlug}`);
            const data = await response.json();

            const select = document.getElementById('lessonSelect');
            select.innerHTML = '<option value="">-- Sélectionnez une leçon --</option>';

            if (data.success && data.lessons) {
                data.lessons.forEach(lesson => {
                    const option = document.createElement('option');
                    option.value = lesson.id;
                    const preview = lesson.improved_transcript ?
                        lesson.improved_transcript.substring(0, 50) + '...' :
                        `Leçon du ${new Date(lesson.created_at).toLocaleDateString()}`;
                    option.textContent = preview;
                    select.appendChild(option);
                });
            }
        } catch (error) {
            this.showStatus(`❌ Erreur chargement leçons: ${error.message}`, 'error');
        }
    }

    async addToExistingLesson() {
        const lessonId = document.getElementById('lessonSelect').value;
        if (!lessonId || !this.selectedFile) {
            this.showStatus('⚠️ Veuillez sélectionner une leçon', 'warning');
            return;
        }

        this.showStatus('Ajout de l\'image en cours...', 'info');

        const formData = new FormData();
        formData.append('image', this.selectedFile);

        try {
            const response = await fetch(`/api/lesson/${lessonId}/add-image`, {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                this.showStatus('✅ Image ajoutée avec succès !', 'success');
                this.displayOCR(result.ocr_text);

                setTimeout(() => {
                    window.location.reload();
                }, 2000);
            } else {
                this.showStatus(`❌ Erreur: ${result.error}`, 'error');
            }
        } catch (error) {
            this.showStatus(`❌ Erreur réseau: ${error.message}`, 'error');
        }
    }

    displayOCR(text) {
        const ocrDiv = document.getElementById('ocrResult');
        const ocrText = document.getElementById('ocrText');
        ocrText.textContent = text || 'Aucun texte détecté';
        ocrDiv.style.display = 'block';
    }

    showStatus(message, type) {
        const statusDiv = document.getElementById('uploadStatus');
        statusDiv.textContent = message;
        statusDiv.className = `upload-status ${type}`;
    }
}

// Initialisation automatique
let lessonImageUploader = null;
