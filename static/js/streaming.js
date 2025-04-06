document.addEventListener('DOMContentLoaded', function() {
    // DOM Elements
    const promptInput = document.getElementById('promptInput');
    const submitBtn = document.getElementById('submitBtn');
    const stopBtn = document.getElementById('stopBtn');
    const responseContainer = document.getElementById('responseContainer');
    const statusIndicator = document.getElementById('statusIndicator');
    const statusText = document.getElementById('statusText');
    const errorMessage = document.getElementById('errorMessage');
    const errorText = document.getElementById('errorText');
    const retryBtn = document.getElementById('retryBtn');
    const recoverBtn = document.getElementById('recoverBtn');
    const copyBtn = document.getElementById('copyBtn');
    const lastHeartbeat = document.getElementById('lastHeartbeat');
    const connectionStatus = document.getElementById('connectionStatus');
    const connectionDetails = document.getElementById('connectionDetails');
    const connStatusBadge = document.getElementById('connStatusBadge');
    const reconnectAttempts = document.getElementById('reconnectAttempts');
    const lastActive = document.getElementById('lastActive');
    const recoveryRate = document.getElementById('recoveryRate');

    // State management
    let currentPrompt = '';
    let currentRequestId = '';
    let isStreaming = false;
    let streamController = null;
    let fullResponse = '';
    let heartbeatInterval = null;
    let lastHeartbeatTime = null;
    let reconnectionCount = 0;
    let recoveryAttempts = 0;
    let successfulRecoveries = 0;
    let streamingCursor = null;
    let lastServerResponse = Date.now();
    let streamResponseDetectionTimer = null;

    // Configuration
    const HEARTBEAT_INTERVAL = 3000; // 3 seconds
    const CONNECTION_TIMEOUT = 10000; // 10 seconds
    const MAX_RECONNECTION_ATTEMPTS = 3;

    // Event listeners
    submitBtn.addEventListener('click', handleSubmit);
    stopBtn.addEventListener('click', stopStreaming);
    retryBtn.addEventListener('click', retryRequest);
    recoverBtn.addEventListener('click', recoverFullResponse);
    copyBtn.addEventListener('click', copyResponse);
    promptInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && e.ctrlKey) {
            handleSubmit();
        }
    });

    // Main function to handle form submission
    function handleSubmit() {
        const prompt = promptInput.value.trim();
        if (!prompt) {
            showError('Please enter a prompt.');
            return;
        }

        currentPrompt = prompt;
        fullResponse = '';
        startStreaming(prompt);
    }

    // Function to start streaming from the API
    function startStreaming(prompt) {
        if (isStreaming) {
            stopStreaming();
        }

        // Reset UI
        resetUI();
        isStreaming = true;
        updateUIForStreaming(true);

        // Create AbortController for the fetch request
        streamController = new AbortController();
        const signal = streamController.signal;

        // Start streaming request
        fetch('/api/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt }),
            signal
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.error || 'Failed to get a response from the server');
                });
            }
            // Setup heartbeat monitoring
            setupHeartbeatMonitoring();
            // Read the stream
            const reader = response.body.getReader();
            return readStream(reader);
        })
        .catch(error => {
            // Only show error if we didn't abort intentionally
            if (signal.aborted) return;
            
            handleStreamingError(error);
        });
    }

    // Function to read the streaming response
    function readStream(reader) {
        const decoder = new TextDecoder();
        
        function processStream({ done, value }) {
            if (done) {
                finishStreaming(false);
                return;
            }

            // Process the chunk
            const chunk = decoder.decode(value, { stream: true });
            processChunk(chunk);
            
            // Continue reading
            return reader.read().then(processStream);
        }

        return reader.read().then(processStream);
    }

    // Process a chunk of the SSE stream
    function processChunk(chunk) {
        // Update last server response time
        lastServerResponse = Date.now();
        
        // Split the chunk into individual SSE messages
        const lines = chunk.split('\n\n');
        
        for (const line of lines) {
            if (!line || !line.startsWith('data: ')) continue;
            
            try {
                const jsonStr = line.substring(6);
                const data = JSON.parse(jsonStr);
                
                // Handle different types of messages
                switch (data.type) {
                    case 'request_id':
                        currentRequestId = data.id;
                        logActivity('Request ID received: ' + currentRequestId);
                        break;
                        
                    case 'content':
                        handleContentChunk(data.content);
                        break;
                        
                    case 'heartbeat':
                        handleHeartbeat(data.timestamp);
                        break;
                        
                    case 'done':
                        finishStreaming(false);
                        break;
                        
                    case 'error':
                        throw new Error(data.error);
                }
            } catch (error) {
                // If it's not valid JSON or has other issues, log but don't break the stream
                console.error('Error processing chunk:', error);
            }
        }
    }

    // Handle content chunks in the stream
    function handleContentChunk(content) {
        fullResponse += content;
        
        // Update the response container
        if (responseContainer.classList.contains('loading')) {
            responseContainer.classList.remove('loading');
            responseContainer.innerHTML = '';
        }
        
        // Append new content
        responseContainer.innerHTML += content;
        
        // Add streaming cursor
        if (!streamingCursor) {
            streamingCursor = document.createElement('span');
            streamingCursor.className = 'streaming-cursor';
            responseContainer.appendChild(streamingCursor);
        }
        
        // Auto-scroll to bottom
        responseContainer.scrollTop = responseContainer.scrollHeight;
    }

    // Handle heartbeat messages
    function handleHeartbeat(timestamp) {
        lastHeartbeatTime = new Date(timestamp);
        updateHeartbeatUI();
        
        // Reset the connectivity check timer since we received a heartbeat
        resetStreamResponseDetectionTimer();
    }

    // Update UI elements for heartbeat status
    function updateHeartbeatUI() {
        if (lastHeartbeatTime) {
            lastHeartbeat.textContent = lastHeartbeatTime.toLocaleTimeString();
            connectionStatus.textContent = 'Connected';
            connectionStatus.className = 'text-success';
            connStatusBadge.className = 'badge bg-success';
            connStatusBadge.textContent = 'Connected';
        }
    }

    // Setup heartbeat monitoring
    function setupHeartbeatMonitoring() {
        // Clear existing intervals
        if (heartbeatInterval) {
            clearInterval(heartbeatInterval);
        }
        
        // Start monitoring heartbeats
        heartbeatInterval = setInterval(() => {
            // Check server connectivity
            fetch('/api/heartbeat')
                .then(response => {
                    if (response.ok) return response.json();
                    throw new Error('Server heartbeat failed');
                })
                .then(data => {
                    handleHeartbeat(data.timestamp);
                })
                .catch(error => {
                    console.error('Heartbeat error:', error);
                    markConnectionProblem();
                });
            
            // Check if we've received any response from the server recently
            if (isStreaming && (Date.now() - lastServerResponse > CONNECTION_TIMEOUT)) {
                handleConnectionTimeout();
            }
        }, HEARTBEAT_INTERVAL);
        
        // Setup initial stream response detection timer
        resetStreamResponseDetectionTimer();
        
        // Show connection details
        connectionDetails.classList.remove('d-none');
    }

    // Reset the stream response detection timer
    function resetStreamResponseDetectionTimer() {
        if (streamResponseDetectionTimer) {
            clearTimeout(streamResponseDetectionTimer);
        }
        
        streamResponseDetectionTimer = setTimeout(() => {
            if (isStreaming) {
                handleConnectionTimeout();
            }
        }, CONNECTION_TIMEOUT);
    }

    // Handle connection timeout
    function handleConnectionTimeout() {
        if (!isStreaming) return;
        
        markConnectionProblem();
        
        // Check if we should try to reconnect or give up
        if (reconnectionCount < MAX_RECONNECTION_ATTEMPTS) {
            attemptReconnection();
        } else {
            handleStreamingError(new Error('Connection lost after multiple reconnection attempts'));
        }
    }

    // Mark UI elements to show connection problem
    function markConnectionProblem() {
        connectionStatus.textContent = 'Disconnected';
        connectionStatus.className = 'text-danger';
        connStatusBadge.className = 'badge bg-danger';
        connStatusBadge.textContent = 'Disconnected';
        
        // Show warning in status indicator
        statusText.textContent = 'Connection problem detected...';
        statusIndicator.className = 'alert alert-warning';
    }

    // Attempt to reconnect to the stream
    function attemptReconnection() {
        reconnectionCount++;
        reconnectAttempts.textContent = reconnectionCount;
        
        statusText.textContent = `Reconnecting (attempt ${reconnectionCount}/${MAX_RECONNECTION_ATTEMPTS})...`;
        logActivity(`Attempting reconnection ${reconnectionCount}/${MAX_RECONNECTION_ATTEMPTS}`);
        
        // Stop current stream first
        if (streamController) {
            streamController.abort();
            streamController = null;
        }
        
        // Wait briefly before reconnecting
        setTimeout(() => {
            if (isStreaming) {
                startStreaming(currentPrompt);
            }
        }, 1000);
    }

    // Handle streaming errors
    function handleStreamingError(error) {
        console.error('Streaming error:', error);
        
        // Update UI to show error
        showError(error.message || 'Connection error occurred');
        
        // Clean up streaming state
        finishStreaming(true);
    }

    // Stop streaming
    function stopStreaming() {
        if (!isStreaming) return;
        
        if (streamController) {
            streamController.abort();
            streamController = null;
        }
        
        finishStreaming(false);
    }

    // Finish streaming and update UI
    function finishStreaming(isError) {
        // Clean up streaming state
        isStreaming = false;
        
        // Remove streaming cursor
        if (streamingCursor) {
            streamingCursor.remove();
            streamingCursor = null;
        }
        
        // Update UI elements
        updateUIForStreaming(false);
        
        // Clean up intervals and timers
        if (heartbeatInterval) {
            clearInterval(heartbeatInterval);
            heartbeatInterval = null;
        }
        
        if (streamResponseDetectionTimer) {
            clearTimeout(streamResponseDetectionTimer);
            streamResponseDetectionTimer = null;
        }
        
        // Hide status indicator if no error
        if (!isError) {
            statusIndicator.classList.add('d-none');
            connectionDetails.classList.add('d-none');
        }
        
        // Enable copy button if we have a response
        if (fullResponse.trim() !== '') {
            copyBtn.disabled = false;
        }
        
        // Log completion
        lastActive.textContent = new Date().toLocaleTimeString();
    }

    // Retry the current request
    function retryRequest() {
        reconnectionCount = 0;
        errorMessage.classList.add('d-none');
        startStreaming(currentPrompt);
    }

    // Recover full response when streaming fails
    function recoverFullResponse() {
        recoveryAttempts++;
        
        // Show recovery status
        statusIndicator.classList.remove('d-none');
        statusText.textContent = 'Attempting to recover full response...';
        statusIndicator.className = 'alert alert-warning';
        responseContainer.classList.add('recovery-pulse');
        
        // Request complete response from server
        fetch('/api/complete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                prompt: currentPrompt,
                request_id: currentRequestId
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to recover response');
            }
            return response.json();
        })
        .then(data => {
            // Update with recovered response
            fullResponse = data.response;
            responseContainer.innerHTML = fullResponse;
            responseContainer.classList.remove('recovery-pulse');
            
            // Update UI
            copyBtn.disabled = false;
            errorMessage.classList.add('d-none');
            statusIndicator.className = 'alert alert-success';
            statusText.textContent = 'Response recovered successfully!';
            
            // Update recovery stats
            successfulRecoveries++;
            updateRecoveryStats();
            
            // Hide status after a delay
            setTimeout(() => {
                statusIndicator.classList.add('d-none');
            }, 3000);
        })
        .catch(error => {
            responseContainer.classList.remove('recovery-pulse');
            showError('Recovery failed: ' + error.message);
            updateRecoveryStats();
        });
    }

    // Update recovery statistics
    function updateRecoveryStats() {
        if (recoveryAttempts > 0) {
            const rate = Math.round((successfulRecoveries / recoveryAttempts) * 100);
            recoveryRate.textContent = `${rate}% (${successfulRecoveries}/${recoveryAttempts})`;
        }
    }

    // Copy response to clipboard
    function copyResponse() {
        if (fullResponse) {
            navigator.clipboard.writeText(fullResponse)
                .then(() => {
                    const originalText = copyBtn.innerHTML;
                    copyBtn.innerHTML = '<i class="fas fa-check me-1"></i>Copied!';
                    setTimeout(() => {
                        copyBtn.innerHTML = originalText;
                    }, 2000);
                })
                .catch(err => {
                    console.error('Failed to copy text: ', err);
                });
        }
    }

    // Show error message
    function showError(message) {
        errorText.textContent = message;
        errorMessage.classList.remove('d-none');
        statusIndicator.classList.add('d-none');
    }

    // Reset UI elements
    function resetUI() {
        responseContainer.innerHTML = '<div class="text-center text-muted">Loading response...</div>';
        responseContainer.classList.add('loading');
        errorMessage.classList.add('d-none');
        statusIndicator.classList.remove('d-none');
        statusText.textContent = 'Connecting to OpenAI...';
        statusIndicator.className = 'alert alert-info';
        copyBtn.disabled = true;
    }

    // Update UI elements for streaming state
    function updateUIForStreaming(isActive) {
        submitBtn.disabled = isActive;
        stopBtn.disabled = !isActive;
        promptInput.disabled = isActive;
    }

    // Utility function to log activity
    function logActivity(message) {
        console.log(`[${new Date().toLocaleTimeString()}] ${message}`);
    }
});
