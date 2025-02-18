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

window.openConversation = function(id, event) {
    if (!event.target.closest('.dropdown') && !event.target.closest('.title-input')) {
        window.socket.emit('open_conversation', { id: id });
    }
};

document.addEventListener('DOMContentLoaded', function() {
    // Initialize Socket.IO
    const socket = io();
    // Make socket available globally for our conversation functions
    window.socket = socket;

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
            input.style.height = 'auto';
            addLoadingIndicator();

            // Send both message and image to the server
            socket.emit('send_message', {
                message: message,
                image: currentImage
            });

            // Clear input and image
            input.value = '';
            removeImage();
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

    socket.on('receive_message', function(data) {
        removeLoadingIndicator();
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
            moveInputToBottom();
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
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

    input.addEventListener('input', function() {
        if (window.innerWidth <= 768) {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 100) + 'px';
        } else {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        }
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

            // Move input to center if it's the first message
            inputContainer.classList.add('centered');
            responseTime.classList.add('centered');
            welcomeContainer.classList.add('visible');
            suggestionsContainer.classList.add('visible');
            isFirstMessage = true;

            // Clear any existing session
            socket.emit('clear_session');
        });
    }
});