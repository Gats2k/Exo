window.toggleSubjectsMenu = function(event) {
    event.stopPropagation();
    const navItem = event.currentTarget;
    const dropdown = navItem.querySelector('.subjects-dropdown');
    const chevron = navItem.querySelector('.subjects-chevron');

    // Close all other dropdowns first
    document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
        if (!menu.closest('.nav-item')) {  // Don't close if it's part of the current nav-item
            menu.classList.remove('show');
        }
    });

    // Toggle current dropdown
    dropdown.classList.toggle('show');
    chevron.classList.toggle('rotate');
};

// Define functions in global scope
window.toggleDropdown = function(id, event) {
    event.stopPropagation();
    const dropdown = document.getElementById(`dropdown-${id}`);
    const allDropdowns = document.querySelectorAll('.dropdown-menu');

    allDropdowns.forEach(menu => {
        if (menu !== dropdown && menu.classList.contains('show')) {
            menu.classList.remove('show');
        }
    });

    dropdown.classList.toggle('show');
};

document.addEventListener('DOMContentLoaded', function() {
    // Récupérer les éléments existants
    const sidebar = document.querySelector('.sidebar');
    const mortarboardIcon = document.querySelector('.bi-mortarboard');

    // Fonction pour fermer la sidebar
    const closeSidebar = () => {
        if (window.innerWidth <= 768 && sidebar.classList.contains('visible')) {
            sidebar.classList.remove('visible');
            mortarboardIcon.classList.remove('bi-mortarboard-fill');
            mortarboardIcon.classList.add('bi-mortarboard');
        }
    };

    // Ajouter l'événement de clic sur la zone principale
    const mainArea = document.querySelector('.main-area');
    if (mainArea) {
        mainArea.addEventListener('click', (e) => {
            if (!e.target.closest('.sidebar') && !e.target.closest('.sidebar-toggle')) {
                closeSidebar();
            }
        });
    }
});

document.addEventListener('DOMContentLoaded', function() {
    // Ajouter le code d'initialisation du menu utilisateur
    const userMenuButton = document.getElementById('userMenuButton');
    const userMenuDropdown = document.getElementById('userMenuDropdown');

    if (userMenuButton && userMenuDropdown) {
        userMenuButton.addEventListener('click', function(e) {
            e.stopPropagation();
            userMenuDropdown.classList.toggle('show');
        });
// Fonction pour vérifier et récupérer les messages dont le streaming s'est arrêté
function checkStalledStream(messageId) {
    const streamInfo = activeStreamMessages[messageId];

    // Si le message n'est plus en mode streaming, ne rien faire
    if (!streamInfo) {
        return;
    }

    console.log(`Attempting to recover stalled message ${messageId}`);

    // Récupérer le message complet depuis le serveur
    fetch(`/api/recover_message/${messageId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.content) {
                // Vérifier si le contenu récupéré est différent de ce que nous avons déjà
                if (data.content !== streamInfo.content) {
                    // Mettre à jour le contenu avec la réponse complète
                    streamInfo.content = data.content;
                    streamInfo.element.innerHTML = data.content.replace(/\n/g, '<br>');
                    console.log(`Stalled message ${messageId} recovered successfully`);

                    // Ajouter une classe pour indiquer que le message a été récupéré
                    streamInfo.element.closest('.message').classList.add('recovered');
                }
            }

            // Même si on n'a pas récupéré de contenu, considérer le streaming comme terminé
            // pour éviter que le message reste en état de chargement indéfiniment
            delete activeStreamMessages[messageId];
        })
        .catch(error => {
            console.error(`Failed to recover stalled message ${messageId}:`, error);

            // En cas d'échec, quand même terminer le streaming pour ne pas bloquer l'interface
            delete activeStreamMessages[messageId];

            // Ajouter une indication visuelle que le message est incomplet
            streamInfo.element.closest('.message').classList.add('incomplete');
            streamInfo.element.innerHTML += '<div class="error-notice">⚠️ Message incomplet, actualisez la page pour réessayer</div>';
        });
}

        // Fermer le menu si on clique ailleurs sur la page
        document.addEventListener('click', function(e) {
            if (!userMenuButton.contains(e.target) && !userMenuDropdown.contains(e.target)) {
                userMenuDropdown.classList.remove('show');
            }
        });
    }
});

window.startRename = function(id, event) {
    event.preventDefault();
    event.stopPropagation();

    const titleElement = document.getElementById(`title-${id}`);
    const editElement = document.getElementById(`edit-${id}`);
    const input = editElement.querySelector('input');

    titleElement.style.display = 'none';
    editElement.style.display = 'block';
    input.value = titleElement.textContent;
    input.focus();

    // Close dropdown
    document.getElementById(`dropdown-${id}`).classList.remove('show');
};

window.handleTitleKeydown = function(event, id) {
    if (event.key === 'Enter') {
        event.preventDefault();
        const input = event.target;
        const newTitle = input.value.trim();

        if (newTitle) {
            window.socket.emit('rename_conversation', { id: id, title: newTitle });

            // Update UI immediately
            const titleElement = document.getElementById(`title-${id}`);
            const editElement = document.getElementById(`edit-${id}`);

            titleElement.textContent = newTitle;
            titleElement.style.display = 'block';
            editElement.style.display = 'none';
        }
    } else if (event.key === 'Escape') {
        const titleElement = document.getElementById(`title-${id}`);
        const editElement = document.getElementById(`edit-${id}`);

        titleElement.style.display = 'block';
        editElement.style.display = 'none';
    }
};

window.deleteConversation = function(id, event) {
    event.preventDefault();
    event.stopPropagation();
    if (confirm('Êtes-vous sûr de vouloir supprimer cette conversation ?')) {
        window.socket.emit('delete_conversation', { id: id });
        // Remove the conversation item immediately from UI
        const item = document.querySelector(`.history-item[onclick*="${id}"]`);
        item.remove();
    }
};

window.openConversation = function(id, event, isTelegram, isWhatsApp) {
    if (!event.target.closest('.dropdown') && !event.target.closest('.title-input')) {
        window.socket.emit('open_conversation', { 
            id: id,
            is_telegram: isTelegram || false,
            is_whatsapp: isWhatsApp || false
        });
    }
};

function setupHeartbeat() {
    // Envoyer un ping toutes les 15 secondes pour maintenir la connexion active
    const heartbeatInterval = setInterval(function() {
        if (socket.connected) {
            socket.emit('heartbeat');
            console.log('Heartbeat envoyé');

            // Actualiser le cookie de session
            fetch('/refresh_session', { 
                method: 'POST',
                credentials: 'same-origin'
            })
            .then(response => {
                if (!response.ok) {
                    console.warn('Échec du rafraîchissement de session, statut:', response.status);
                    // Si le serveur répond avec une erreur, forcer une reconnexion
                    if (response.status === 401 || response.status === 403) {
                        console.log('Session expirée, tentative de restauration...');
                        // Tenter de restaurer la session avec le thread_id stocké localement
                        const storedThreadId = localStorage.getItem('thread_id');
                        if (storedThreadId) {
                            socket.emit('restore_session', { thread_id: storedThreadId });
                        }
                    }
                }
            })
            .catch(error => {
                console.error('Erreur lors du rafraîchissement de session:', error);
            });
        } else {
            console.log('Socket déconnecté, tentative de reconnexion...');
            socket.connect();

            // Après reconnexion, tenter de restaurer le thread actif
            socket.once('connect', function() {
                console.log('Reconnecté, tentative de restauration du thread...');
                const storedThreadId = localStorage.getItem('thread_id');
                if (storedThreadId) {
                    socket.emit('restore_session', { thread_id: storedThreadId });
                }
            });
        }
    }, 15000);

    // Nettoyer l'intervalle quand l'utilisateur quitte la page
    window.addEventListener('beforeunload', function() {
        clearInterval(heartbeatInterval);
    });
}

document.addEventListener('DOMContentLoaded', function() {
    // Détecter si nous sommes sur la page admin ou la page chat
    const isAdminPage = window.location.pathname.includes('/admin');

    // Initialize Socket.IO
    const socket = io();
    // Make socket available globally for our conversation functions
    window.socket = socket;

    // Ajouter après le login réussi dans le code existant
    socket.on('login_success', function(data) {
        // Stocker l'ID utilisateur dans le localStorage
        if (data.user_id) {
            localStorage.setItem('user_id', data.user_id);
        }
    });

    // Gérer la reconnexion pour préserver le contexte
    socket.on('reconnect', function() {
        console.log('Reconnecté au serveur, récupération de la conversation');

        // Si nous avons un thread_id dans la session stockée localement, réutilisons-le
        const storedThreadId = localStorage.getItem('thread_id');
        const storedUserId = localStorage.getItem('user_id');

        if (storedThreadId) {
            // Essayer de restaurer la session avec des informations supplémentaires
            socket.emit('restore_session', { 
                thread_id: storedThreadId,
                user_id: storedUserId
            });

            // Vérifier si la session a été restaurée correctement
            setTimeout(function() {
                // Si après 2 secondes nous n'avons pas reçu de confirmation de restauration,
                // mais que nous avons des messages en cache, essayer d'afficher ces messages
                if (document.querySelector('.chat-messages').children.length === 0) {
                    const cachedMessages = localStorage.getItem('cached_messages');
                    if (cachedMessages) {
                        try {
                            const messages = JSON.parse(cachedMessages);
                            // Afficher les messages en cache pendant que nous attendons la reconnexion
                            displayCachedMessages(messages);
                        } catch (e) {
                            console.error('Erreur lors de la récupération des messages en cache', e);
                        }
                    }
                }
            }, 2000);
        }
    });

    // Stocker les messages dans le localStorage pour les restaurer en cas de déconnexion
    function storeMessagesInCache(messages) {
        try {
            localStorage.setItem('cached_messages', JSON.stringify(messages));
        } catch (e) {
            console.error('Erreur lors du stockage des messages en cache', e);
        }
    }

    // Fonction pour afficher les messages en cache
    function displayCachedMessages(messages) {
        // Afficher les messages en cache dans l'interface
        const chatMessages = document.querySelector('.chat-messages');
        // ... code pour afficher les messages ...
    }

    // Ajouter un écouteur pour la confirmation de restauration de session
    socket.on('conversation_opened', function(data) {
        if (data.success) {
            console.log('Session restaurée avec succès');
        }
    });

    // Configurer le heartbeat pour maintenir la connexion active
    setupHeartbeat();

    // Si nous sommes sur la page admin, sortir immédiatement pour éviter les erreurs
    if (isAdminPage) {
        console.log('Page administrative détectée, désactivation du script de chat');
        return;
    }

    // Get all necessary elements
    const sidebar = document.querySelector('.sidebar');
    const hoverArea = document.querySelector('.hover-area');
    const mortarboardIcon = document.querySelector('.bi-mortarboard');
    const iconButton = document.querySelector('.icon-button');
    const inputContainer = document.querySelector('.input-container');
    const responseTime = document.querySelector('.response-time');
    const chatMessages = document.querySelector('.chat-messages');
    const welcomeContainer = document.querySelector('.welcome-container');
    const suggestionsContainer = document.querySelector('.suggestions-container');
    const cameraInput = document.getElementById('camera-input');
    const imageInput = document.getElementById('image-input');
    const imagePreviewContainer = document.querySelector('.image-preview-container');
    let isFirstMessage = true;
    let sidebarTimeout;
    let currentImage = null;
    let activeStreamMessages = {};
    let pageVisibilityState = 'visible';
    let lastActiveTime = Date.now();

    // Surveiller la visibilité de la page
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'hidden') {
            pageVisibilityState = 'hidden';
            console.log('Page mise en arrière-plan');
        } else {
            pageVisibilityState = 'visible';
            console.log('Page revenue au premier plan');

            // Vérifier si cela fait plus de 5 minutes que la page était inactive
            const inactiveTime = (Date.now() - lastActiveTime) / 1000 / 60;
            if (inactiveTime > 5) {
                console.log(`Page inactive pendant ${inactiveTime.toFixed(2)} minutes, restauration de la conversation...`);

                // Tenter de restaurer la session active
                const storedThreadId = localStorage.getItem('thread_id');
                if (storedThreadId) {
                    socket.emit('restore_session', { thread_id: storedThreadId });
                }
            }

            lastActiveTime = Date.now();
        }
    });

    // Mettre à jour le temps d'activité lors des interactions utilisateur
    ['click', 'keydown', 'scroll', 'mousemove', 'touchstart'].forEach(eventType => {
        document.addEventListener(eventType, function() {
            lastActiveTime = Date.now();
        }, { passive: true });
    });

    // Vérifier périodiquement l'état de la page et du thread
    setInterval(function() {
        // Si la page est visible et le socket est connecté
        if (pageVisibilityState === 'visible' && socket.connected) {
            // Vérifier si un thread_id est stocké localement
            const storedThreadId = localStorage.getItem('thread_id');

            // Vérifier si la session côté serveur a un thread_id actif
            // (Cette vérification se fait lors du heartbeat)

            // Si cela fait plus de 5 minutes depuis la dernière activité
            const inactiveMinutes = (Date.now() - lastActiveTime) / 1000 / 60;
            if (inactiveMinutes > 5 && storedThreadId) {
                console.log(`Vérification proactive du thread après ${inactiveMinutes.toFixed(2)} minutes d'inactivité`);
                socket.emit('restore_session', { thread_id: storedThreadId });
                lastActiveTime = Date.now(); // Réinitialiser pour éviter des vérifications répétées
            }
        }
    }, 300000); // Vérifier toutes les 5 minutes

    // Vérifier que tous les éléments nécessaires existent
    if (!inputContainer || !responseTime || !chatMessages || !welcomeContainer || !suggestionsContainer) {
        console.log('Éléments requis non disponibles, sortie du script');
        return;
    }

    // Check if there are any existing messages
    if (chatMessages.children.length === 0) {
        // No messages yet, center the input and show welcome elements
        inputContainer.classList.add('centered');
        responseTime.classList.add('centered');
        welcomeContainer.classList.add('visible');
        suggestionsContainer.classList.add('visible');
    } else {
        // Messages exist, position at bottom
        inputContainer.classList.remove('centered');
        responseTime.classList.remove('centered');
        welcomeContainer.classList.remove('visible');
        suggestionsContainer.classList.remove('visible');
        isFirstMessage = false;
    }

    const updateIcon = (isVisible) => {
        if (isVisible) {
            mortarboardIcon.classList.remove('bi-mortarboard');
            mortarboardIcon.classList.add('bi-mortarboard-fill');
        } else {
            mortarboardIcon.classList.remove('bi-mortarboard-fill');
            mortarboardIcon.classList.add('bi-mortarboard');
        }
    };

    if (window.innerWidth > 768) {
        hoverArea.addEventListener('mouseenter', () => {
            clearTimeout(sidebarTimeout);
            sidebar.classList.add('visible');
            updateIcon(true);
        });

        sidebar.addEventListener('mouseenter', () => {
            clearTimeout(sidebarTimeout);
        });

        sidebar.addEventListener('mouseleave', () => {
            sidebarTimeout = setTimeout(() => {
                sidebar.classList.remove('visible');
                updateIcon(false);
            }, 300);
        });

        hoverArea.addEventListener('mouseleave', () => {
            if (!sidebar.matches(':hover')) {
                sidebarTimeout = setTimeout(() => {
                    sidebar.classList.remove('visible');
                    updateIcon(false);
                }, 300);
            }
        });
    }

    iconButton.addEventListener('click', (e) => {
        e.stopPropagation();
        const isVisible = sidebar.classList.toggle('visible');
        updateIcon(isVisible);
    });

    const input = document.querySelector('.input-container textarea');
    const sendBtn = document.querySelector('.send-btn');

    function addLoadingIndicator() {
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'message loading';
        loadingDiv.innerHTML = `
            <div class="loading-dots">
                <span></span>
                <span></span>
                <span></span>
            </div>
        `;
        chatMessages.appendChild(loadingDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return loadingDiv;
    }

    function removeLoadingIndicator() {
        const loadingIndicator = document.querySelector('.message.loading');
        if (loadingIndicator) {
            loadingIndicator.remove();
        }
    }

    function moveInputToBottom() {
        if (isFirstMessage) {
            inputContainer.classList.remove('centered');
            responseTime.classList.remove('centered');
            welcomeContainer.classList.remove('visible');
            suggestionsContainer.classList.remove('visible');
            isFirstMessage = false;
        }
    }

    function handleImageUpload(file) {
        if (file) {
            const reader = new FileReader();
            reader.onload = function(e) {
                const base64Image = e.target.result;

                // Ouvrir le modal de recadrage
                openCropModal(base64Image);
            };
            reader.readAsDataURL(file);
        }
    }

    let cropper;
    let originalImage;

    function openCropModal(imageSrc) {
        originalImage = imageSrc;
        const cropModal = document.getElementById('cropModal');
        const cropImage = document.getElementById('cropImage');

        // Définir la source de l'image
        cropImage.src = imageSrc;

        // Configurer les événements du modal avant de l'afficher
        setupCropModalEvents();

        // Afficher le modal
        cropModal.style.display = 'flex';

        // Initialiser Cropper.js après que l'image soit chargée
        cropImage.onload = function() {
            if (cropper) {
                cropper.destroy();
            }

            cropper = new Cropper(cropImage, {
                aspectRatio: NaN, // Libre
                viewMode: 1,      // Restreint le crop à l'intérieur de la zone visible
                dragMode: 'move', // Par défaut déplacer l'image plutôt que faire un crop
                autoCropArea: 0.8,
                restore: false,
                guides: true,
                center: true,
                highlight: false,
                cropBoxMovable: true,
                cropBoxResizable: true,
                toggleDragModeOnDblclick: true,
            });
        };

        console.log('Modal de recadrage ouvert et événements configurés');
    }

    function closeCropModal() {
        const cropModal = document.getElementById('cropModal');
        cropModal.style.display = 'none';

        if (cropper) {
            cropper.destroy();
            cropper = null;
        }

        console.log('Modal de recadrage fermé');
    }

    function applyCrop() {
        if (!cropper) return;

        const canvas = cropper.getCroppedCanvas({
            maxWidth: 1024,
            maxHeight: 1024,
            fillColor: '#000'
        });

        if (canvas) {
            // Convertir le canvas en base64
            const croppedImage = canvas.toDataURL('image/jpeg');
            currentImage = croppedImage;

            // Créer l'aperçu
            imagePreviewContainer.innerHTML = `
                <div class="image-preview">
                    <img src="${croppedImage}" alt="Preview">
                    <button class="remove-image" onclick="removeImage()">×</button>
                </div>
            `;
            imagePreviewContainer.classList.add('visible');

            // Fermer le modal
            closeCropModal();
        }
    }

    // Configuration des événements pour le modal de recadrage - Déplacé hors de DOMContentLoaded
    function setupCropModalEvents() {
        const closeCropBtn = document.getElementById('closeCropBtn');
        const cropBtn = document.getElementById('cropBtn');
        const cancelCropBtn = document.getElementById('cancelCropBtn');

        if (closeCropBtn) {
            closeCropBtn.addEventListener('click', closeCropModal);
            console.log('Event listener ajouté pour closeCropBtn');
        }

        if (cropBtn) {
            cropBtn.addEventListener('click', applyCrop);
            console.log('Event listener ajouté pour cropBtn');
        }

        if (cancelCropBtn) {
            cancelCropBtn.addEventListener('click', closeCropModal);
            console.log('Event listener ajouté pour cancelCropBtn');
        }
    }

    // Rendre la fonction removeImage capable de nettoyer le cropper si nécessaire
    window.removeImage = function() {
        currentImage = null;
        imagePreviewContainer.innerHTML = '';
        imagePreviewContainer.classList.remove('visible');

        if (cropper) {
            cropper.destroy();
            cropper = null;
        }
    };

    cameraInput.addEventListener('change', function(e) {
        if (e.target.files && e.target.files[0]) {
            handleImageUpload(e.target.files[0]);
        }
        // Réinitialiser la valeur de l'input pour permettre de sélectionner le même fichier
        this.value = '';
    });

    imageInput.addEventListener('change', function(e) {
        if (e.target.files && e.target.files[0]) {
            handleImageUpload(e.target.files[0]);
        }
        // Réinitialiser la valeur de l'input pour permettre de sélectionner le même fichier
        this.value = '';
    });

    function sendMessage() {
        const message = input.value.trim();
        if (message || currentImage) {
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message user';

            let content = '';
            if (currentImage) {
                content += `<img src="${currentImage}" style="max-width: 200px; border-radius: 4px; margin-bottom: 8px;"><br>`;
            }
            if (message) {
                content += message.replace(/\n/g, '<br>');
            }

            messageDiv.innerHTML = `
                <div class="message-content">
                    ${content}
                </div>
            `;
            chatMessages.appendChild(messageDiv);

            moveInputToBottom();
            addLoadingIndicator();

            // Send both message and image to the server
            socket.emit('send_message', {
                message: message,
                image: currentImage
            });

            // Clear input and image
            input.value = '';
            removeImage();
            // Réinitialiser la hauteur après un court délai pour éviter les saccades
            setTimeout(() => {
                adjustTextareaHeight(input);
            }, 0);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

    socket.on('receive_message', function(data) {
        removeLoadingIndicator();

        // Vérifier si ce message est déjà géré par le streaming
        if (activeStreamMessages[data.id]) {
            // Si oui, ne pas recréer le message
            return;
        }

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant';
        messageDiv.id = `message-${data.id}`;
        let content = '';
        if (data.image) {
            content += `<img src="${data.image}" style="max-width: 200px; border-radius: 4px; margin-bottom: 8px;"><br>`;
        }
        content += data.message.replace(/\n/g, '<br>');

        // Déterminer si un feedback existe déjà
        const feedbackPositive = data.feedback === 'positive';
        const feedbackNegative = data.feedback === 'negative';

        messageDiv.innerHTML = `
            <div class="message-content">
                ${content}
            </div>
            <div class="message-feedback">
                <button class="feedback-btn thumbs-up ${feedbackPositive ? 'active' : ''}" 
                       data-message-id="${data.id}" data-feedback-type="positive">
                    <i class="bi bi-hand-thumbs-up"></i>
                </button>
                <button class="feedback-btn thumbs-down ${feedbackNegative ? 'active' : ''}" 
                       data-message-id="${data.id}" data-feedback-type="negative">
                    <i class="bi bi-hand-thumbs-down"></i>
                </button>
            </div>
        `;
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        // Après avoir ajouté le message, mettre à jour le cache
        const allMessages = Array.from(chatMessages.children).map(message => {
            // Extraire les détails des messages pour le stockage
            return {
                role: message.classList.contains('user') ? 'user' : 'assistant',
                content: message.querySelector('.message-content').innerHTML,
                id: message.id.replace('message-', '')
            };
        });

        storeMessagesInCache(allMessages);
    });

    // Nouvel événement pour indiquer le début d'un message streamé
    socket.on('message_started', function(data) {
        removeLoadingIndicator();

        // Créer un nouvel élément de message pour le streaming
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant';
        messageDiv.id = `message-${data.message_id}`;

        // Ajouter le conteneur du message avec le contenu initial vide
        messageDiv.innerHTML = `
            <div class="message-content">
                <div id="stream-content-${data.message_id}"></div>
            </div>
            <div class="message-feedback">
                <button class="feedback-btn thumbs-up" 
                       data-message-id="${data.message_id}" data-feedback-type="positive">
                    <i class="bi bi-hand-thumbs-up"></i>
                </button>
                <button class="feedback-btn thumbs-down" 
                       data-message-id="${data.message_id}" data-feedback-type="negative">
                    <i class="bi bi-hand-thumbs-down"></i>
                </button>
            </div>
        `;

        chatMessages.appendChild(messageDiv);

        // Ajouter un indicateur de chargement en attendant le début du stream
        const contentElement = messageDiv.querySelector(`#stream-content-${data.message_id}`);
        contentElement.innerHTML = `
            <div class="stream-loading">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
            </div>
        `;

        // Enregistrer ce message comme étant actif
        activeStreamMessages[data.message_id] = {
            element: contentElement,
            content: ''
        };

        chatMessages.scrollTop = chatMessages.scrollHeight;
    });

    // Nouvel événement pour recevoir les chunks de réponse en streaming
    socket.on('response_stream', function(data) {
        // Vérifier si nous avons le message enregistré
        if (!activeStreamMessages[data.message_id]) {
            console.error('Received stream for unknown message:', data.message_id);
            return;
        }

        const streamInfo = activeStreamMessages[data.message_id];
        const contentElement = streamInfo.element;

        // Réinitialiser le timer de surveillance du streaming
        if (streamInfo.timeoutId) {
            clearTimeout(streamInfo.timeoutId);
        }

        // Si c'est la première fois que nous recevons du contenu, supprimer l'indicateur de chargement
        if (streamInfo.content === '') {
            contentElement.innerHTML = '';
        }

        // Ajouter le nouveau contenu
        if (data.content) {
            streamInfo.content += data.content;
            streamInfo.lastUpdate = Date.now();

            // Mettre à jour l'affichage
            contentElement.innerHTML = streamInfo.content.replace(/\n/g, '<br>');
        }

        // Si c'est le message final, terminer le streaming
        if (data.is_final) {
            // Si un message complet est fourni, l'utiliser
            if (data.full_response) {
                streamInfo.content = data.full_response;
                contentElement.innerHTML = streamInfo.content.replace(/\n/g, '<br>');
            }

            // Nettoyer les informations de streaming
            delete activeStreamMessages[data.message_id];
        } else {
            // Configurer un timer pour détecter les streamings bloqués (10 secondes sans mises à jour)
            streamInfo.timeoutId = setTimeout(function() {
                console.log(`Streaming potentially stalled for message ${data.message_id}, attempting recovery...`);
                checkStalledStream(data.message_id);
            }, 10000);
        }

        // Faire défiler vers le bas pour suivre le contenu
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });

    // Listen for conversation updates
    socket.on('conversation_updated', function(data) {
        if (data.success) {
            // UI already updated in handleTitleKeydown
            console.log('Conversation renamed successfully');
        }
    });

    socket.on('conversation_deleted', function(data) {
        if (data.success) {
            // UI already updated in deleteConversation
            console.log('Conversation deleted successfully');
        }
    });

    socket.on('conversation_opened', function(data) {
        if (data.success) {
            // Clear current messages
            chatMessages.innerHTML = '';

            // Update the conversation title in header with the actual title
            const titleElement = document.querySelector('.conversation-title');
            titleElement.textContent = data.title;

            // Sauvegarder thread_id dans le stockage local
            if (data.conversation_id) {
                localStorage.setItem('thread_id', data.conversation_id);
            }

            // Add each message from the conversation history
            data.messages.forEach(msg => {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${msg.role}`;
                messageDiv.id = `message-${msg.id}`;

                let content = '';
                if (msg.image_url) {
                    content += `<img src="${msg.image_url}" style="max-width: 200px; border-radius: 4px; margin-bottom: 8px;"><br>`;
                }
                content += msg.content.replace(/\n/g, '<br>');

                messageDiv.innerHTML = `
                    <div class="message-content">
                        ${content}
                    </div>
                    ${msg.role === 'assistant' ? `
                    <div class="message-feedback">
                        <button class="feedback-btn thumbs-up ${msg.feedback === 'positive' ? 'active' : ''}" 
                               data-message-id="${msg.id}" data-feedback-type="positive">
                            <i class="bi bi-hand-thumbs-up"></i>
                        </button>
                        <button class="feedback-btn thumbs-down ${msg.feedback === 'negative' ? 'active' : ''}" 
                               data-message-id="${msg.id}" data-feedback-type="negative">
                            <i class="bi bi-hand-thumbs-down"></i>
                        </button>
                    </div>
                    ` : ''}
                `;
                chatMessages.appendChild(messageDiv);
            });

            // Update UI for existing conversation
            moveInputToBottom();
            chatMessages.scrollTop = chatMessages.scrollHeight;

            setTimeout(checkEmptyMessages, 500);
        }
    });

    function checkEmptyMessages() {
        // Recherche les messages vides de l'assistant
        document.querySelectorAll('.message.assistant .message-content').forEach(contentDiv => {
            if (!contentDiv.textContent.trim()) {
                // Obtenir l'ID du message depuis le bouton de feedback
                const messageDiv = contentDiv.closest('.message');
                const feedbackBtn = messageDiv.querySelector('.feedback-btn');

                if (feedbackBtn) {
                    const messageId = feedbackBtn.getAttribute('data-message-id');

                    // Tenter de récupérer le contenu du message
                    fetch(`/api/recover_message/${messageId}`)
                    .then(response => {
                        // Vérifier si la requête a réussi (status 2xx) ET si le contenu JSON indique un succès
                        if (response.ok) {
                            return response.json().then(data => {
                                if (data.success && data.content) {
                                    // Mettre à jour le contenu du message
                                    contentDiv.innerHTML = data.content.replace(/\n/g, '<br>');
                                    messageDiv.classList.remove('recovered-failed'); // Retirer l'échec si réussi
                                    console.log(`Message ${messageId} récupéré avec succès via API.`);
                                } else {
                                    // Succès HTTP mais contenu non trouvé dans le JSON
                                    console.warn(`API /recover_message a retourné success:false pour ${messageId}. Contenu non disponible.`);
                                    contentDiv.innerHTML = '[Contenu non disponible]';
                                    messageDiv.classList.add('recovered-failed'); // Marquer comme échec
                                }
                            });
                        } else {
                            // Gérer les erreurs HTTP (ex: 404 Not Found)
                            console.error(`Erreur HTTP ${response.status} lors de la récupération du message ${messageId}.`);
                            contentDiv.innerHTML = `[Erreur ${response.status}]`;
                            messageDiv.classList.add('recovered-failed'); // Marquer comme échec
                            // Pas besoin de rejeter ici, on gère l'erreur directement
                        }
                    })
                    .catch(error => {
                        // Gérer les erreurs réseau ou de parsing JSON
                        console.error(`Erreur réseau ou parsing lors de la récupération du message ${messageId}:`, error);
                        contentDiv.innerHTML = '[Erreur réseau]';
                        messageDiv.classList.add('recovered-failed'); // Marquer comme échec
                    });
                }
            }
        });
    }

    // Gestionnaire d'événement amélioré pour new_conversation (AVEC LOGS DE DEBUG)
    socket.on('new_conversation', function(data) {
        // --- DEBUT DEBUG ---
        console.log('[DEBUG] Event "new_conversation" RECU. Données:', JSON.stringify(data));
        // --- FIN DEBUG ---

        const recentHistory = document.querySelector('.recent-history');
        const titleElement = document.querySelector('.conversation-title');

        // console.log("Nouvelle conversation reçue:", data); // Log original (peut être redondant avec celui ci-dessus)

        // Update the header title with the new conversation title
        // --- DEBUT DEBUG ---
        console.log(`[DEBUG] Mise à jour titre header avec: "${data.title}"`);
        // --- FIN DEBUG ---
        titleElement.textContent = data.title;

        // Sauvegarder thread_id dans le stockage local
        if (data.id) {
            // --- DEBUT DEBUG ---
            console.log(`[DEBUG] Stockage localStorage thread_id: "${data.id}"`);
            // --- FIN DEBUG ---
            localStorage.setItem('thread_id', data.id);
        }

        // Vérifier si cette conversation existe déjà dans l'historique
        const selectorExistingItem = `.history-item[onclick*="${data.id}"]`;
        // --- DEBUT DEBUG ---
        console.log(`[DEBUG] Recherche existingItem avec sélecteur: "${selectorExistingItem}"`);
        // --- FIN DEBUG ---
        const existingItem = document.querySelector(selectorExistingItem);

        // --- DEBUT DEBUG ---
        if (existingItem) {
            console.log('[DEBUG] existingItem TROUVÉ.', existingItem);
        } else {
            console.warn('[DEBUG] existingItem NON TROUVÉ. Passage à la création.');
        }
        // --- FIN DEBUG ---

        if (existingItem) {
            // Mettre à jour le titre si l'élément existe déjà
            const selectorTitleDiv = `#title-${data.id}`;
            const titleDiv = existingItem.querySelector(selectorTitleDiv);

            if (titleDiv) {
                // Toujours mettre à jour le titre quand on reçoit l'événement
                titleDiv.textContent = data.title;
                console.log(`Mise à jour du titre: → "${data.title}"`);
            }
            return; // Ne pas créer de nouvel élément
        }

        // --- DEBUT DEBUG ---
        console.log('[DEBUG] Création d\'un nouvel historyItem.');
        // --- FIN DEBUG ---
        // Create new history item (si existingItem n'est pas trouvé)
        const historyItem = document.createElement('div');
        historyItem.className = 'history-item';
        const isTelegram = data.is_telegram || false;
        const isWhatsApp = data.is_whatsapp || false;
        historyItem.setAttribute('onclick', `openConversation('${data.id}', event, ${isTelegram}, ${isWhatsApp})`);


        historyItem.innerHTML = `
            <div class="history-content">
                <div class="history-title" id="title-${data.id}">${data.title}</div>
                <div class="history-title-edit" id="edit-${data.id}" style="display: none;">
                    <input type="text" class="title-input" value="${data.title}"
                           onkeydown="handleTitleKeydown(event, '${data.id}')"
                           onclick="event.stopPropagation()">
                </div>
                <div class="history-subject">${data.subject}</div>
            </div>
            <div class="history-actions">
                <div class="time">${data.time}</div>
                <div class="dropdown">
                    <button class="btn-icon" onclick="toggleDropdown('${data.id}', event)">
                        <i class="bi bi-three-dots-vertical"></i>
                    </button>
                    <div id="dropdown-${data.id}" class="dropdown-menu">
                        <a href="#" onclick="startRename('${data.id}', event)">
                            <i class="bi bi-pencil"></i> Renommer
                        </a>
                        <a href="#" onclick="deleteConversation('${data.id}', event)">
                            <i class="bi bi-trash"></i> Supprimer
                        </a>
                    </div>
                </div>
            </div>
        `;

        // Insert at the beginning of the history
        const firstHistoryItem = recentHistory.querySelector('.history-item');
        if (firstHistoryItem) {
            recentHistory.insertBefore(historyItem, firstHistoryItem);
        } else {
            recentHistory.appendChild(historyItem);
        }

        // console.log(`Nouvelle conversation ${data.id} ajoutée à l'historique avec titre "${data.title}"`); // Log original
    });


    sendBtn.addEventListener('click', sendMessage);

    input.addEventListener('keydown', function(e) {
        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);

        if (e.key === 'Enter') {
            if (!isMobile && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        }
    });

    function adjustTextareaHeight(textarea) {
        const maxHeight = window.innerWidth <= 768 ? 100 : 300;
        const minHeight = 36;

        // Si le textarea est vide, appliquer directement la hauteur minimale
        if (!textarea.value) {
            textarea.style.height = minHeight + 'px';
            textarea.style.overflowY = 'hidden';
            return;
        }

        // Sauvegarder la position du curseur
        const selectionStart = textarea.selectionStart;
        const selectionEnd = textarea.selectionEnd;

        // Clone temporairement le texte pour mesurer sa hauteur réelle
        const clone = textarea.cloneNode();
        clone.style.position = 'absolute';
        clone.style.visibility = 'hidden';
        clone.style.height = minHeight + 'px'; // Forcer la hauteur minimale sur le clone
        clone.value = textarea.value;
        document.body.appendChild(clone);

        // Calculer la hauteur nécessaire
        const requiredHeight = Math.max(minHeight, Math.min(clone.scrollHeight, maxHeight));

        // Supprimer le clone
        document.body.removeChild(clone);

        // Appliquer la nouvelle hauteur
        textarea.style.height = requiredHeight + 'px';
        textarea.style.overflowY = requiredHeight === maxHeight ? 'auto' : 'hidden';

        // Restaurer la position du curseur
        textarea.setSelectionRange(selectionStart, selectionEnd);
    }

    input.addEventListener('input', function() {
        adjustTextareaHeight(this);
    });

    const actionButtons = document.querySelectorAll('.action-btn');
    actionButtons.forEach(button => {
        button.addEventListener('click', function() {
            button.classList.toggle('active');
        });
    });


    // Close dropdowns when clicking outside
    document.addEventListener('click', function(event) {
        if (!event.target.closest('.dropdown')) {
            document.querySelectorAll('.dropdown-menu').forEach(menu => {
                menu.classList.remove('show');
            });
        }
        if (!event.target.closest('.nav-item')) {
            document.querySelectorAll('.subjects-dropdown').forEach(dropdown => {
                dropdown.classList.remove('show');
                const chevron = dropdown.parentElement.querySelector('.subjects-chevron');
                if (chevron) {
                    chevron.classList.remove('rotate');
                }
            });
        }
    });

    // Close subjects dropdown when sidebar closes
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                if (!sidebar.classList.contains('visible')) {
                    document.querySelectorAll('.subjects-dropdown').forEach(dropdown => {
                        dropdown.classList.remove('show');
                        const chevron = dropdown.parentElement.querySelector('.subjects-chevron');
                        if (chevron) {
                            chevron.classList.remove('rotate');
                        }
                    });
                }
            }
        });
    });

    observer.observe(sidebar, {
        attributes: true
    });

    // Add handler for new conversation button
    // Add handler for new conversation button
    const newConversationBtn = document.querySelector('.new-conversation-btn');
    if (newConversationBtn) {
        newConversationBtn.addEventListener('click', function() {
            // Clear messages
            chatMessages.innerHTML = '';

            // Reset title
            const titleElement = document.querySelector('.conversation-title');
            titleElement.textContent = "Nouvelle conversation"; // <-- Réinitialisation du titre affiché

            // Reset UI state
            inputContainer.classList.add('centered');
            responseTime.classList.add('centered');
            welcomeContainer.classList.add('visible');
            suggestionsContainer.classList.add('visible');
            isFirstMessage = true;

            // Supprimer le thread_id du stockage local
            localStorage.removeItem('thread_id');

            // Clear any existing session
            socket.emit('clear_session');
        });
    }

    // Listen for session cleared confirmation
    socket.on('session_cleared', function(data) {
        if (data.success) {
            console.log('Session cleared successfully');

            // Si le serveur a créé un nouveau thread_id, le stocker localement
            if (data.new_thread_id) {
                console.log('New thread_id received:', data.new_thread_id);
                // Sauvegarder le nouveau thread_id dans le localStorage
                localStorage.setItem('thread_id', data.new_thread_id);
            }
        } else if (data.error) {
            console.error('Error clearing session:', data.error);
        }
    });

    // Listen for feedback submission confirmation
    socket.on('feedback_submitted', function(data) {
        if (data.success) {
            console.log('Feedback submitted successfully');
            // Le feedback a été enregistré avec succès dans la base de données
            // Il sera maintenant persisté entre les rechargements de page
        }
    });

    // Add event handlers for feedback buttons
    document.addEventListener('click', function(event) {
        const feedbackBtn = event.target.closest('.feedback-btn');
        if (feedbackBtn) {
            event.preventDefault();
            const messageId = feedbackBtn.dataset.messageId;
            const feedbackType = feedbackBtn.dataset.feedbackType;

            // Remove active class from both buttons in this message
            const messageFeedback = feedbackBtn.closest('.message-feedback');
            messageFeedback.querySelectorAll('.feedback-btn').forEach(btn => {
                btn.classList.remove('active');
            });

            // Add active class to the clicked button
            feedbackBtn.classList.add('active');

            // Stocker ce feedback en mémoire (pour retrouver facilement dans quel état est un message)
            // Cela permettra de conserver l'état visuel même pour les nouveaux messages
            if (!window.userFeedbacks) {
                window.userFeedbacks = {};
            }
            window.userFeedbacks[messageId] = feedbackType;

            // Send feedback to server
            socket.emit('submit_feedback', {
                message_id: messageId,
                feedback_type: feedbackType
            });

            // Show visual confirmation
            const confirmation = document.createElement('div');
            confirmation.className = 'feedback-confirmation';
            confirmation.textContent = feedbackType === 'positive' ? 'Merci pour votre appréciation!' : 'Merci pour votre retour!';
            confirmation.style.position = 'absolute';
            confirmation.style.color = feedbackType === 'positive' ? '#4ADE80' : '#F43F5E';
            confirmation.style.fontSize = '0.8rem';
            confirmation.style.opacity = '0';
            confirmation.style.transition = 'opacity 0.3s ease';

            messageFeedback.appendChild(confirmation);

            // Fade in and out
            setTimeout(() => {
                confirmation.style.opacity = '1';
                setTimeout(() => {
                    confirmation.style.opacity = '0';
                    setTimeout(() => {
                        confirmation.remove();
                    }, 300);
                }, 2000);
            }, 10);
        }
    });
});