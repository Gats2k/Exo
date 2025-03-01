import os
import logging
import asyncio
from telegram import Update, constants, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
    ConversationHandler, CallbackContext
)
from openai import OpenAI, OpenAIError
from collections import defaultdict
import aiohttp
from pathlib import Path
import uuid
from datetime import datetime
import base64
import requests
from models import User
from database import db

# Add states for registration flow
FIRST_NAME, LAST_NAME, AGE, PHONE_NUMBER, STUDY_LEVEL = range(5)

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize OpenAI client with error handling
try:
    openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    ASSISTANT_ID = os.environ.get("OPENAI_ASSISTANT_ID")
    if not ASSISTANT_ID:
        raise ValueError("OPENAI_ASSISTANT_ID environment variable is not set")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {str(e)}", exc_info=True)
    raise

# Store thread IDs for each user
user_threads = defaultdict(lambda: None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the registration process for new users."""
    user_id = update.effective_user.id

    # Check if user already exists
    user = User.query.filter_by(phone_number=str(user_id)).first()
    if user:
        thread = openai_client.beta.threads.create()
        thread_id = f"telegram_{thread.id}"  # Add telegram prefix
        user_threads[user_id] = thread_id
        await update.message.reply_text(
            'Welcome back! How can I help you today?'
        )
        return ConversationHandler.END

    await update.message.reply_text(
        'Welcome! To get started, I need some information from you.\n'
        'What is your first name?'
    )
    return FIRST_NAME

async def first_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['first_name'] = update.message.text
    await update.message.reply_text('Great! Now, what is your last name?')
    return LAST_NAME

async def last_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['last_name'] = update.message.text
    await update.message.reply_text('What is your age?')
    return AGE

async def age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text)
        if age < 10 or age > 100:
            await update.message.reply_text('Please enter a valid age between 10 and 100.')
            return AGE
        context.user_data['age'] = age
        await update.message.reply_text('Please share your phone number:')
        return PHONE_NUMBER
    except ValueError:
        await update.message.reply_text('Please enter a valid number for your age.')
        return AGE

async def phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    if not phone.replace('+', '').isdigit():
        await update.message.reply_text('Please enter a valid phone number.')
        return PHONE_NUMBER

    context.user_data['phone_number'] = phone

    reply_keyboard = [['Terminal A', 'Terminal C', 'Terminal D']]
    await update.message.reply_text(
        'What is your study level?',
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True
        )
    )
    return STUDY_LEVEL

async def study_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    study_level = update.message.text
    if study_level not in ['Terminal A', 'Terminal C', 'Terminal D']:
        await update.message.reply_text('Please select a valid study level.')
        return STUDY_LEVEL

    context.user_data['study_level'] = study_level

    # Save user to database
    try:
        new_user = User(
            first_name=context.user_data['first_name'],
            last_name=context.user_data['last_name'],
            age=context.user_data['age'],
            phone_number=context.user_data['phone_number'],
            study_level=context.user_data['study_level'],
            grade_goals='average'  # Default value
        )
        new_user.set_password(str(update.effective_user.id))  # Use Telegram ID as password

        db.session.add(new_user)
        db.session.commit()

        # Create OpenAI thread for the user with telegram prefix
        thread = openai_client.beta.threads.create()
        thread_id = f"telegram_{thread.id}"
        user_threads[update.effective_user.id] = thread_id

        await update.message.reply_text(
            'Thank you for registering! You can now start chatting with me.',
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error saving user: {str(e)}")
        await update.message.reply_text(
            'Sorry, there was an error during registration. Please try again.',
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels and ends the conversation."""
    await update.message.reply_text(
        'Registration cancelled.',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def setup_telegram_bot():
    """Initialize and setup the Telegram bot."""
    try:
        logger.info("Starting Telegram bot setup...")

        # Create the Application
        application = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

        # Add registration conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                FIRST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, first_name)],
                LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, last_name)],
                AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age)],
                PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_number)],
                STUDY_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, study_level)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        application.add_handler(conv_handler)

        # Add other handlers
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        ))

        # Add error handler
        application.add_error_handler(error_handler)

        logger.info("Telegram bot setup completed successfully")
        return application

    except Exception as e:
        logger.error(f"Error setting up Telegram bot: {str(e)}", exc_info=True)
        raise

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        'You can send me any message and I will respond using AI!'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages and respond using OpenAI Assistant."""
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    try:
        # Check if user is registered
        user = User.query.filter_by(phone_number=str(user_id)).first()
        if not user:
            await update.message.reply_text(
                "Please register first by using the /start command."
            )
            return

        # Get or create thread ID for this user
        thread_id = user_threads[user_id]
        if not thread_id:
            thread = openai_client.beta.threads.create()
            thread_id = thread.id
            user_threads[user_id] = thread_id
            logger.info(f"Created new thread {thread_id} for user {user_id}")

        # Add the user's message to the thread
        message_text = update.message.text
        logger.info(f"Received message from user {user_id}: {message_text}")

        # Start typing indication
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=constants.ChatAction.TYPING
        )

        openai_client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message_text
        )

        # Run the assistant
        run = openai_client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID
        )

        # Wait for the run to complete while maintaining typing indication
        while True:
            # Refresh typing indicator every 4.5 seconds (Telegram's limit is 5 seconds)
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action=constants.ChatAction.TYPING
            )

            run_status = openai_client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            if run_status.status == 'completed':
                break
            elif run_status.status in ['failed', 'cancelled', 'expired']:
                raise Exception(f"Assistant run failed with status: {run_status.status}")
            await asyncio.sleep(4.5)  # Wait before refreshing typing indicator

        # Get the assistant's response
        messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
        assistant_message = messages.data[0].content[0].text.value
        logger.info(f"Sending response to user {user_id}: {assistant_message}")

        await update.message.reply_text(assistant_message)

    except OpenAIError as openai_error:
        logger.error(f"OpenAI API error: {str(openai_error)}", exc_info=True)
        await update.message.reply_text(
            "I'm having trouble connecting to my AI brain. Please try again in a moment."
        )
    except Exception as e:
        logger.error(f"Error handling message: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "I apologize, but I encountered an error processing your message. Please try again."
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les messages contenant des photos"""
    user_id = update.effective_user.id
    try:
        logger.info(f"Receiving photo from user {user_id}")

        if not update.message or not update.message.photo:
            logger.error("No photo found in the message")
            return

        logger.info(f"Photo details: {update.message.photo[-1]}")

        # Get file URL directly from Telegram
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        file_url = file.file_path  # This is a direct URL to the image on Telegram's servers
        logger.info(f"Got file URL from Telegram: {file_url}")

        # Get or create thread ID for this user
        thread_id = user_threads[user_id]
        if not thread_id:
            thread = openai_client.beta.threads.create()
            thread_id = thread.id
            user_threads[user_id] = thread_id
            logger.info(f"Created new thread {thread_id} for user {user_id}")

        # Start typing indication
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=constants.ChatAction.TYPING
        )

        # Créer le message avec l'image
        message_content = [{
            "type": "image_url",
            "image_url": {
                "url": file_url
            }
        }]

        # Ajouter le texte de la légende si présent
        if update.message.caption:
            logger.info(f"Adding caption: {update.message.caption}")
            message_content.append({
                "type": "text",
                "text": update.message.caption
            })

        # Envoyer à OpenAI
        logger.info(f"Sending message to OpenAI thread {thread_id}")
        openai_client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message_content
        )
        logger.info("Message sent to OpenAI")

        # Run the assistant
        run = openai_client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID
        )
        logger.info("Assistant run created")

        # Wait for completion
        while True:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action=constants.ChatAction.TYPING
            )

            run_status = openai_client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            if run_status.status == 'completed':
                logger.info("Assistant run completed")
                break
            elif run_status.status in ['failed', 'cancelled', 'expired']:
                error_msg = f"Assistant run failed with status: {run_status.status}"
                logger.error(error_msg)
                raise Exception(error_msg)
            await asyncio.sleep(4.5)

        # Get and send response
        messages = openai_client.beta.threads.messages.list(thread_id=thread_id)
        assistant_message = messages.data[0].content[0].text.value
        logger.info(f"Sending response: {assistant_message[:100]}...")
        await update.message.reply_text(assistant_message)

    except Exception as e:
        logger.error(f"Error handling photo: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "I apologize, but I encountered an error processing your image. Please try again."
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.error(f'Update "{update}" caused error "{context.error}"', exc_info=True)

def run_telegram_bot():
    """Run the Telegram bot."""
    try:
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        application = setup_telegram_bot()
        logger.info("Starting Telegram bot polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error running Telegram bot: {str(e)}", exc_info=True)
        raise