import os
import json
import logging
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from utils.openai_handler import OpenAIHandler

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create the Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")

# Initialize OpenAI API handler
openai_handler = OpenAIHandler()

@app.route('/')
def index():
    """Render the main application page."""
    return render_template('index.html')

@app.route('/api/stream', methods=['POST'])
def stream_response():
    """Stream OpenAI API response to the client."""
    try:
        data = request.json
        prompt = data.get('prompt', '')
        
        if not prompt:
            return jsonify({"error": "Prompt is required"}), 400
        
        # Create server-side streaming response
        return Response(
            stream_with_context(openai_handler.stream_completion(prompt)),
            content_type='text/event-stream'
        )
    except Exception as e:
        logger.error(f"Streaming error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/complete', methods=['POST'])
def complete_response():
    """Get complete response in case streaming fails."""
    try:
        data = request.json
        prompt = data.get('prompt', '')
        
        if not prompt:
            return jsonify({"error": "Prompt is required"}), 400
        
        # Get complete response
        response = openai_handler.get_complete_response(prompt)
        return jsonify({"response": response})
    except Exception as e:
        logger.error(f"Complete response error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/heartbeat', methods=['GET'])
def heartbeat():
    """Endpoint for client heartbeat to check server connectivity."""
    return jsonify({"status": "alive", "timestamp": openai_handler.get_timestamp()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
