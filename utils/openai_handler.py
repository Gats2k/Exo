import os
import time
import json
import logging
from datetime import datetime
from openai import OpenAI
from openai.types.chat import ChatCompletionChunk

logger = logging.getLogger(__name__)

class OpenAIHandler:
    """Handler for OpenAI API interactions with error recovery."""
    
    def __init__(self):
        """Initialize the OpenAI client with API key."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.error("OpenAI API key not found in environment variables")
            raise ValueError("OpenAI API key is required")
        
        self.client = OpenAI(api_key=api_key)
        # the newest OpenAI model is "gpt-4o" which was released May 13, 2024.
        # do not change this unless explicitly requested by the user
        self.model = "gpt-4o"
        self.default_timeout = 60  # Default timeout in seconds
        self.last_request_id = None
        self.request_cache = {}  # Cache for storing complete responses

    def get_timestamp(self):
        """Get current timestamp for heartbeat."""
        return datetime.now().isoformat()

    def stream_completion(self, prompt):
        """Stream OpenAI chat completion response."""
        request_id = str(time.time())
        self.last_request_id = request_id
        
        try:
            # Send SSE with request ID first
            yield f"data: {json.dumps({'type': 'request_id', 'id': request_id})}\n\n"
            
            # Create streaming request to OpenAI
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                timeout=self.default_timeout
            )
            
            complete_response = ""
            
            # Stream chunks to client with heartbeat
            last_heartbeat = time.time()
            for chunk in stream:
                # Send heartbeat every 2 seconds
                current_time = time.time()
                if current_time - last_heartbeat >= 2:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': self.get_timestamp()})}\n\n"
                    last_heartbeat = current_time
                
                # Extract content from chunk
                if chunk.choices and len(chunk.choices) > 0:
                    content = chunk.choices[0].delta.content
                    if content:
                        complete_response += content
                        yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
            
            # Store complete response in cache for recovery
            self.request_cache[request_id] = complete_response
            
            # Send completion signal
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            logger.error(f"Error during streaming: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    def get_complete_response(self, prompt, request_id=None):
        """Get complete response for recovery purposes."""
        # Check if we have the response in cache
        if request_id and request_id in self.request_cache:
            return self.request_cache[request_id]
        
        try:
            # Make a non-streaming request
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                timeout=self.default_timeout
            )
            
            complete_response = response.choices[0].message.content
            
            # Cache the response
            new_request_id = str(time.time())
            self.request_cache[new_request_id] = complete_response
            
            return complete_response
            
        except Exception as e:
            logger.error(f"Error getting complete response: {str(e)}")
            raise
