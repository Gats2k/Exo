document.addEventListener('DOMContentLoaded', function() {
    // Initialize Socket.IO with reconnection options
    const socket = io({
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000,
    });

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
    let isConnected = false;

    // Socket connection handling
    socket.on('connect', () => {
        console.log('Connected to server');
        isConnected = true;
    });

    socket.on('disconnect', () => {
        console.log('Disconnected from server');
        isConnected = false;
    });

    socket.on('connect_error', (error) => {
        console.error('Connection error:', error);
    });

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
        if (!isConnected) {
            console.log('Attempting to reconnect...');
            socket.connect();
            return;
        }

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
            }, (error) => {
                if (error) {
                    console.error('Send message error:', error);
                    removeLoadingIndicator();
                    const errorDiv = document.createElement('div');
                    errorDiv.className = 'message error';
                    errorDiv.innerHTML = `
                        <div class="message-content">
                            Error sending message. Please try again.
                        </div>
                    `;
                    chatMessages.appendChild(errorDiv);
                }
            });

            // Clear input and image
            input.value = '';
            removeImage();
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

    // Add the message receiving handler
    socket.on('receive_message', function(data) {
        removeLoadingIndicator();
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant';
        messageDiv.innerHTML = `
            <div class="message-content">
                ${data.message.replace(/\n/g, '<br>')}
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
});