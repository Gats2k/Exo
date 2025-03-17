// Socket.IO connection
const socket = io();

// Chat message handling
function sendMessage(message, imageData = null) {
    const data = {
        message: message,
        image: imageData
    };
    socket.emit('send_message', data);
}

// Handle incoming messages
socket.on('receive_message', function(data) {
    appendMessage('assistant', data.message);
    scrollToBottom();
});

// Listen for AI model changes from admin dashboard
socket.on('ai_model_changed', function(data) {
    console.log('AI model changed to:', data.model);

    // Show notification to user
    const modelNames = {
        'openai': 'OpenAI GPT',
        'deepseek': 'DeepSeek Chat'
    };

    const notification = document.createElement('div');
    notification.className = 'model-change-notification';
    notification.innerHTML = `
        <div class="notification-content">
            <i class="bi bi-arrow-repeat"></i>
            Le modèle d'IA a été changé pour ${modelNames[data.model]}
            <span class="notification-time">${data.timestamp}</span>
        </div>
    `;

    document.querySelector('.chat-messages').appendChild(notification);

    // Auto-scroll to the notification
    notification.scrollIntoView({ behavior: 'smooth' });

    // Add a system message indicating the context is preserved
    const systemMessage = document.createElement('div');
    systemMessage.className = 'message system-message';
    systemMessage.innerHTML = `
        <div class="message-content">
            Le modèle d'IA a été changé. La conversation continuera avec le nouveau modèle en gardant le contexte précédent.
        </div>
    `;
    document.querySelector('.chat-messages').appendChild(systemMessage);

    // Auto-scroll to the system message
    systemMessage.scrollIntoView({ behavior: 'smooth' });

    // Remove notification after 5 seconds
    setTimeout(() => {
        notification.remove();
    }, 5000);
});

// Helper functions
function appendMessage(role, content, imageUrl = null) {
    const messagesContainer = document.querySelector('.chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}-message`;

    if (imageUrl) {
        messageDiv.innerHTML = `
            <div class="message-content">
                <img src="${imageUrl}" alt="Uploaded image" class="chat-image">
                <p>${content}</p>
            </div>
        `;
    } else {
        messageDiv.innerHTML = `
            <div class="message-content">
                <p>${content}</p>
            </div>
        `;
    }

    messagesContainer.appendChild(messageDiv);
}

function scrollToBottom() {
    const messagesContainer = document.querySelector('.chat-messages');
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}