document.addEventListener('DOMContentLoaded', function() {
    // Initialize Socket.IO
    const socket = io();

    // Sidebar functionality
    const sidebar = document.querySelector('.sidebar');
    const hoverArea = document.querySelector('.hover-area');
    const mortarboardIcon = document.querySelector('.bi-mortarboard');
    const iconButton = document.querySelector('.icon-button');
    const inputContainer = document.querySelector('.input-container');
    const responseTime = document.querySelector('.response-time');
    const chatMessages = document.querySelector('.chat-messages');
    let isFirstMessage = true;
    let sidebarTimeout;

    // Check if there are any existing messages
    if (chatMessages.children.length === 0) {
        // No messages yet, center the input
        inputContainer.classList.add('centered');
        responseTime.classList.add('centered');
    } else {
        // Messages exist, position at bottom
        inputContainer.classList.remove('centered');
        responseTime.classList.remove('centered');
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
            isFirstMessage = false;
        }
    }

    function sendMessage() {
        const message = input.value.trim();
        if (message) {
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message user';
            messageDiv.innerHTML = `
                <div class="message-content">
                    ${message.replace(/\n/g, '<br>')}
                </div>
            `;
            chatMessages.appendChild(messageDiv);

            // Move input to bottom after first message is actually sent
            moveInputToBottom();

            input.style.height = 'auto';
            addLoadingIndicator();
            socket.emit('send_message', { message: message });
            input.value = '';
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

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