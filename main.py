
import eventlet
eventlet.monkey_patch()

from flask import jsonify
from app import app, socketio
import logging

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'}), 200


logger.info("Main application starting - Telegram bot will be managed by separate process")

if __name__ == "__main__":
    # Run the Flask-SocketIO application
    logger.info("Starting Flask-SocketIO server on port 5000...")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False, log_output=True)
