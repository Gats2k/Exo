document.addEventListener('DOMContentLoaded', function() {
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
