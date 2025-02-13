document.addEventListener('DOMContentLoaded', function() {
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

    /* À AJOUTER */
    document.addEventListener('click', function(e) {
        if (!sidebar.contains(e.target) && !iconButton.contains(e.target)) {
            sidebar.classList.remove('visible');
            mortarboardIcon.classList.remove('bi-mortarboard-fill');
            mortarboardIcon.classList.add('bi-mortarboard');
        }
    });

    hoverArea.addEventListener('mouseleave', () => {
        if (!sidebar.matches(':hover')) {
            sidebarTimeout = setTimeout(() => {
                sidebar.classList.remove('visible');
                mortarboardIcon.classList.remove('bi-mortarboard-fill');
                mortarboardIcon.classList.add('bi-mortarboard');
            }, 300);
        }
    });

    // Handle message input
    const input = document.querySelector('.input-container input');
    const sendBtn = document.querySelector('.send-btn');

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

            // Clear input
            input.value = '';

            // Auto scroll to bottom
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

    // Send message on button click
    sendBtn.addEventListener('click', sendMessage);

    // Send message on Enter key
    input.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    // Handle action buttons
    const actionButtons = document.querySelectorAll('.action-btn');
    actionButtons.forEach(button => {
        button.addEventListener('click', function() {
            // Toggle active state
            button.classList.toggle('active');
        });
    });
});