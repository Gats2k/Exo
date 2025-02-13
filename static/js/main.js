document.addEventListener('DOMContentLoaded', function() {
    // Initialize Socket.IO
    const socket = io();

    // Sidebar functionality
    const sidebar = document.querySelector('.sidebar');
    const hoverArea = document.querySelector('.hover-area');
    const mortarboardIcon = document.querySelector('.bi-mortarboard');
    const iconButton = document.querySelector('.icon-button');
    let sidebarTimeout;

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

    document.addEventListener('click', function(e) {
        if (!sidebar.contains(e.target) && !iconButton.contains(e.target)) {
            sidebar.classList.remove('visible');
            updateIcon(false);
        }
    });

    // Handle message input
    const input = document.querySelector('.input-container input');
    const sendBtn = document.querySelector('.send-btn');
    const lineBreakBtn = document.querySelector('.line-break-btn');

    // Add line break button handler
    if (lineBreakBtn) {
        lineBreakBtn.addEventListener('click', function() {
            input.value = input.value + '\n';
            input.focus();
        });
    }

    // Handle message input with Shift+Enter support
    input.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            if (e.shiftKey) {
                // Prevent the default form submission
                e.preventDefault();
                // Insert a new line at the cursor position
                const start = this.selectionStart;
                const end = this.selectionEnd;
                this.value = this.value.substring(0, start) + '\n' + this.value.substring(end);
                // Move cursor after the inserted newline
                this.selectionStart = this.selectionEnd = start + 1;
            } else {
                // Regular Enter key sends the message
                e.preventDefault();
                sendMessage();
            }
        }
    });

    function addLoadingIndicator() {
        const chatMessages = document.querySelector('.chat-messages');
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

    function sendMessage() {
        const message = input.value.trim();
        if (message) {
            // Add user message to chat
            const chatMessages = document.querySelector('.chat-messages');
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message user';
            messageDiv.innerHTML = `
                <div class="message-content">
                    ${message}
                </div>
            `;
            chatMessages.appendChild(messageDiv);

            // Add loading indicator
            addLoadingIndicator();

            // Send message through socket
            socket.emit('send_message', { message: message });

            // Clear input
            input.value = '';

            // Auto scroll to bottom
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

    // Handle assistant responses
    socket.on('receive_message', function(data) {
        // Remove loading indicator
        removeLoadingIndicator();

        const chatMessages = document.querySelector('.chat-messages');
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant';
        messageDiv.innerHTML = `
            <div class="message-content">
                ${data.message}
            </div>
        `;
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });

    // Send message on button click
    sendBtn.addEventListener('click', sendMessage);


    // Handle action buttons
    const actionButtons = document.querySelectorAll('.action-btn');
    actionButtons.forEach(button => {
        button.addEventListener('click', function() {
            button.classList.toggle('active');
        });
    });
});