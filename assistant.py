import os
import asyncio
from openai import OpenAI
from datetime import datetime

class AssistantChat:
    def __init__(self):
        self.client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        self.assistant = None
        self.thread = None

    async def initialize(self):
        try:
            # Create an assistant if not already created
            if self.assistant is None:
                self.assistant = await asyncio.to_thread(
                    self.client.beta.assistants.create,
                    name="Educational Helper",
                    instructions="You are a helpful educational assistant who provides clear and concise responses.",
                    tools=[{"type": "code_interpreter"}],
                    model="gpt-4-turbo-preview"
                )

            # Create a thread if not already created
            if self.thread is None:
                self.thread = await asyncio.to_thread(
                    self.client.beta.threads.create
                )
            return True
        except Exception as e:
            print(f"Initialization error: {e}")
            return False

    async def send_message(self, user_message):
        try:
            if not self.thread or not self.assistant:
                await self.initialize()

            # Add the user's message to the thread
            await asyncio.to_thread(
                self.client.beta.threads.messages.create,
                self.thread.id,
                role="user",
                content=user_message
            )

            # Create a run
            run = await asyncio.to_thread(
                self.client.beta.threads.runs.create,
                self.thread.id,
                assistant_id=self.assistant.id
            )

            # Poll for completion
            response = await self.wait_for_completion(self.thread.id, run.id)

            # Get the latest messages
            messages = await asyncio.to_thread(
                self.client.beta.threads.messages.list,
                self.thread.id
            )

            return messages.data[0].content[0].text.value
        except Exception as e:
            print(f"Error sending message: {e}")
            return "Sorry, there was an error processing your message."

    async def wait_for_completion(self, thread_id, run_id):
        while True:
            try:
                run = await asyncio.to_thread(
                    self.client.beta.threads.runs.retrieve,
                    thread_id,
                    run_id
                )

                if run.status == 'completed':
                    return run
                elif run.status == 'failed':
                    raise Exception('Run failed')

                # Wait before checking again
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Error in wait_for_completion: {e}")
                raise