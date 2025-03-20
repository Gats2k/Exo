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
    document.querySelector('.main-area').addEventListener('click', (e) => {
        if (!e.target.closest('.sidebar') && !e.target.closest('.sidebar-toggle')) {
            closeSidebar();
        }
    });
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
            // Use fetch API instead of socket
            fetch('/api/rename_conversation', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ id: id, title: newTitle })
            })
            .then(response => response.json())
            .then(data => {
                console.log('Rename success:', data);
            })
            .catch(error => {
                console.error('Error renaming conversation:', error);
            });

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
        // Use fetch API instead of socket
        fetch('/api/delete_conversation', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ id: id })
        })
        .then(response => response.json())
        .then(data => {
            console.log('Delete success:', data);
        })
        .catch(error => {
            console.error('Error deleting conversation:', error);
        });
        
        // Remove the conversation item immediately from UI
        const item = document.querySelector(`.history-item[onclick*="${id}"]`);
        item.remove();
    }
};

window.openConversation = function(id, event) {
    if (!event.target.closest('.dropdown') && !event.target.closest('.title-input')) {
        // Use fetch API instead of socket
        fetch('/api/open_conversation', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ id: id })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Clear current messages
                const chatMessages = document.querySelector('.chat-messages');
                chatMessages.innerHTML = '';

                // Update the conversation title in header
                const titleElement = document.querySelector('.conversation-title');
                titleElement.textContent = data.title || "Nouvelle conversation";

                // Add each message from the conversation history
                data.messages.forEach(msg => {
                    const messageDiv = document.createElement('div');
                    messageDiv.className = `message ${msg.role}`;

                    let content = '';
                    if (msg.image_url) {
                        content += `<img src="${msg.image_url}" style="max-width: 200px; border-radius: 4px; margin-bottom: 8px;"><br>`;
                    }
                    content += msg.content.replace(/\n/g, '<br>');

                    messageDiv.innerHTML = `
                        <div class="message-content">
                            ${content}
                        </div>
                    `;
                    chatMessages.appendChild(messageDiv);
                });

                // Update UI for existing conversation
                if (typeof moveInputToBottom === 'function') {
                    moveInputToBottom();
                }
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        })
        .catch(error => {
            console.error('Error opening conversation:', error);
        });
    }
};

document.addEventListener('DOMContentLoaded', function() {
    // No need for Socket.IO anymore, using REST API instead

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
                currentImage = base64Image;

                // Create preview
                imagePreviewContainer.innerHTML = `
                    <div class="image-preview">
                        <img src="${base64Image}" alt="Preview">
                        <button class="remove-image" onclick="removeImage()">×</button>
                    </div>
                `;
                imagePreviewContainer.classList.add('visible');
            };
            reader.readAsDataURL(file);
        }
    }

    window.removeImage = function() {
        currentImage = null;
        imagePreviewContainer.innerHTML = '';
        imagePreviewContainer.classList.remove('visible');
    };

    cameraInput.addEventListener('change', function(e) {
        if (e.target.files && e.target.files[0]) {
            handleImageUpload(e.target.files[0]);
        }
    });

    imageInput.addEventListener('change', function(e) {
        if (e.target.files && e.target.files[0]) {
            handleImageUpload(e.target.files[0]);
        }
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

            // Send both message and image to the server using fetch API
            fetch('/api/send_message', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: message,
                    image: currentImage
                })
            })
            .then(response => response.json())
            .then(data => {
                // Handle response from the server
                removeLoadingIndicator();
                if (data.success) {
                    const messageDiv = document.createElement('div');
                    messageDiv.className = 'message assistant';
                    let content = '';
                    if (data.image) {
                        content += `<img src="${data.image}" style="max-width: 200px; border-radius: 4px; margin-bottom: 8px;"><br>`;
                    }
                    content += data.message.replace(/\n/g, '<br>');

                    messageDiv.innerHTML = `
                        <div class="message-content">
                            ${content}
                        </div>
                    `;
                    chatMessages.appendChild(messageDiv);
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                } else {
                    console.error('Error from server:', data.error);
                    // Display error message to user
                    const errorDiv = document.createElement('div');
                    errorDiv.className = 'message error';
                    errorDiv.innerHTML = `
                        <div class="message-content">
                            Une erreur est survenue. Veuillez réessayer.
                        </div>
                    `;
                    chatMessages.appendChild(errorDiv);
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }
            })
            .catch(error => {
                removeLoadingIndicator();
                console.error('Error sending message:', error);
                // Display error message to user
                const errorDiv = document.createElement('div');
                errorDiv.className = 'message error';
                errorDiv.innerHTML = `
                    <div class="message-content">
                        Une erreur est survenue. Veuillez réessayer.
                    </div>
                `;
                chatMessages.appendChild(errorDiv);
                chatMessages.scrollTop = chatMessages.scrollHeight;
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

    // Fetch conversations on page load
    fetch('/api/conversations')
    .then(response => response.json())
    .then(data => {
        if (data.success && data.conversations) {
            const recentHistory = document.querySelector('.recent-history');
            
            // Clear existing conversations
            recentHistory.innerHTML = '';
            
            // Add each conversation to the sidebar
            data.conversations.forEach(conv => {
                const historyItem = document.createElement('div');
                historyItem.className = 'history-item';
                historyItem.setAttribute('onclick', `openConversation('${conv.id}', event)`);
                
                historyItem.innerHTML = `
                    <div class="history-content">
                        <div class="history-title" id="title-${conv.id}">${conv.title || "Sans titre"}</div>
                        <div class="history-title-edit" id="edit-${conv.id}" style="display: none;">
                            <input type="text" class="title-input" value="${conv.title || "Sans titre"}" 
                                onkeydown="handleTitleKeydown(event, '${conv.id}')"
                                onclick="event.stopPropagation()">
                        </div>
                        <div class="history-subject">${conv.subject || ""}</div>
                    </div>
                    <div class="history-actions">
                        <div class="time">${conv.time || ""}</div>
                        <div class="dropdown">
                            <button class="btn-icon" onclick="toggleDropdown('${conv.id}', event)">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <div id="dropdown-${conv.id}" class="dropdown-menu">
                                <a href="#" onclick="startRename('${conv.id}', event)">
                                    <i class="bi bi-pencil"></i> Renommer
                                </a>
                                <a href="#" onclick="deleteConversation('${conv.id}', event)">
                                    <i class="bi bi-trash"></i> Supprimer
                                </a>
                            </div>
                        </div>
                    </div>
                `;
                
                recentHistory.appendChild(historyItem);
            });
        }
    })
    .catch(error => {
        console.error('Error fetching conversations:', error);
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
    const newConversationBtn = document.querySelector('.new-conversation-btn');
    if (newConversationBtn) {
        newConversationBtn.addEventListener('click', function() {
            // Clear messages
            chatMessages.innerHTML = '';

            // Reset title
            const titleElement = document.querySelector('.conversation-title');
            titleElement.textContent = "Nouvelle conversation";

            // Reset UI state
            inputContainer.classList.add('centered');
            responseTime.classList.add('centered');
            welcomeContainer.classList.add('visible');
            suggestionsContainer.classList.add('visible');
            isFirstMessage = true;

            // Clear any existing session using fetch API
            fetch('/api/clear_session', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log('Session cleared successfully');
                }
            })
            .catch(error => {
                console.error('Error clearing session:', error);
            });
        });
    }
});