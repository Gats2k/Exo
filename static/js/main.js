document.addEventListener('DOMContentLoaded', function() {
    // Initialize Socket.IO
    const socket = io();

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


    function toggleDropdown(id) {
        const dropdown = document.getElementById(`dropdown-${id}`);
        const allDropdowns = document.querySelectorAll('.dropdown-menu');

        // Close all other dropdowns
        allDropdowns.forEach(menu => {
            if (menu !== dropdown && menu.classList.contains('show')) {
                menu.classList.remove('show');
            }
        });

        dropdown.classList.toggle('show');
    }

    function renameConversation(id, event) {
        event.preventDefault();
        const newTitle = prompt('Nouveau nom de la conversation:');
        if (newTitle) {
            socket.emit('rename_conversation', { id: id, title: newTitle });
        }
    }

    function deleteConversation(id, event) {
        event.preventDefault();
        if (confirm('Êtes-vous sûr de vouloir supprimer cette conversation ?')) {
            socket.emit('delete_conversation', { id: id });
        }
    }

    // Close dropdowns when clicking outside
    document.addEventListener('click', function(event) {
        if (!event.target.closest('.dropdown')) {
            document.querySelectorAll('.dropdown-menu').forEach(menu => {
                menu.classList.remove('show');
            });
        }
    });
});