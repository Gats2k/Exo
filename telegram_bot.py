import os
import logging
import asyncio
from telegram import Update, constants
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, 
    filters, ConversationHandler, CallbackContext
)
from openai import OpenAI, OpenAIError
from collections import defaultdict
import aiohttp
from datetime import datetime
from models import User, db
from werkzeug.security import generate_password_hash, check_password_hash

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

# Define conversation states
CHOOSING_AUTH, REGISTERING_FIRST_NAME, REGISTERING_LAST_NAME, REGISTERING_AGE, \
REGISTERING_PHONE, REGISTERING_PASSWORD, LOGIN_PASSWORD = range(7)

# User registration data storage
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initial conversation starter - ask if user wants to register or login"""
    user_id = update.effective_user.id

    # Clear any existing data
    user_data[user_id] = {}

    reply_text = (
        "Welcome to Môjo! 👋\n\n"
        "Are you a new user or do you already have an account?\n\n"
        "Please type:\n"
        "1️⃣ for new registration\n"
        "2️⃣ if you already have an account"
    )

    await update.message.reply_text(reply_text)
    return CHOOSING_AUTH

async def handle_auth_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's choice between registration and login"""
    user_id = update.effective_user.id
    text = update.message.text

    if text == "1":
        await update.message.reply_text("Please enter your first name:")
        return REGISTERING_FIRST_NAME
    elif text == "2":
        await update.message.reply_text("Please enter your phone number to login:")
        return LOGIN_PASSWORD
    else:
        await update.message.reply_text("Please type 1 for registration or 2 for login.")
        return CHOOSING_AUTH

async def register_first_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle first name input"""
    user_id = update.effective_user.id
    user_data[user_id]['first_name'] = update.message.text

    await update.message.reply_text("Great! Now please enter your last name:")
    return REGISTERING_LAST_NAME

async def register_last_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle last name input"""
    user_id = update.effective_user.id
    user_data[user_id]['last_name'] = update.message.text

    await update.message.reply_text("Please enter your age:")
    return REGISTERING_AGE

async def register_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle age input"""
    try:
        age = int(update.message.text)
        if age < 13 or age > 100:
            await update.message.reply_text("Please enter a valid age between 13 and 100:")
            return REGISTERING_AGE

        user_id = update.effective_user.id
        user_data[user_id]['age'] = age

        await update.message.reply_text("Please enter your phone number:")
        return REGISTERING_PHONE
    except ValueError:
        await update.message.reply_text("Please enter a valid number for your age:")
        return REGISTERING_AGE

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone number input"""
    user_id = update.effective_user.id
    phone = update.message.text

    # Check if phone number already exists
    existing_user = User.query.filter_by(phone_number=phone).first()
    if existing_user:
        await update.message.reply_text(
            "This phone number is already registered. Please use a different number:"
        )
        return REGISTERING_PHONE

    user_data[user_id]['phone_number'] = phone
    await update.message.reply_text(
        "Finally, please create a password for your account:"
    )
    return REGISTERING_PASSWORD

async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle password input and complete registration"""
    user_id = update.effective_user.id
    user_data[user_id]['password'] = update.message.text

    try:
        # Create new user
        new_user = User(
            first_name=user_data[user_id]['first_name'],
            last_name=user_data[user_id]['last_name'],
            age=user_data[user_id]['age'],
            phone_number=user_data[user_id]['phone_number'],
            study_level='Terminal A',  # Default value
            grade_goals='Above Average',  # Default value
            telegram_id=str(user_id)
        )
        new_user.set_password(user_data[user_id]['password'])

        db.session.add(new_user)
        db.session.commit()

        # Create a new thread for the user
        thread = openai_client.beta.threads.create()
        user_threads[user_id] = thread.id

        await update.message.reply_text(
            "Registration successful! 🎉\n\n"
            "You can now start chatting with me! How can I help you today?"
        )

        # Clear registration data
        del user_data[user_id]

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error during registration: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "There was an error during registration. Please try again later."
        )
        return ConversationHandler.END

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle login process"""
    user_id = update.effective_user.id
    phone = update.message.text

    # Find user by phone number
    user = User.query.filter_by(phone_number=phone).first()
    if not user:
        await update.message.reply_text(
            "Phone number not found. Please enter a valid phone number:"
        )
        return LOGIN_PASSWORD

    user_data[user_id] = {'user': user}
    await update.message.reply_text("Please enter your password:")
    return LOGIN_PASSWORD

async def verify_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify password and complete login"""
    user_id = update.effective_user.id
    password = update.message.text
    user = user_data[user_id]['user']

    if user.check_password(password):
        # Update telegram_id if not set
        if not user.telegram_id:
            user.telegram_id = str(user_id)
            db.session.commit()

        # Create a new thread for the user
        thread = openai_client.beta.threads.create()
        user_threads[user_id] = thread.id

        await update.message.reply_text(
            "Login successful! 🎉\n\n"
            "You can now start chatting with me! How can I help you today?"
        )

        # Clear login data
        del user_data[user_id]

        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "Incorrect password. Please try again:"
        )
        return LOGIN_PASSWORD

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation"""
    user_id = update.effective_user.id
    if user_id in user_data:
        del user_data[user_id]

    await update.message.reply_text(
        "Operation cancelled. Type /start to begin again."
    )
    return ConversationHandler.END

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

def setup_telegram_bot():
    """Initialize and setup the Telegram bot."""
    try:
        logger.info("Starting Telegram bot setup...")

        # Create the Application
        application = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

        # Create conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                CHOOSING_AUTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth_choice)],
                REGISTERING_FIRST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_first_name)],
                REGISTERING_LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_last_name)],
                REGISTERING_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_age)],
                REGISTERING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)],
                REGISTERING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
                LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_password)], #Corrected to verify_password
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )

        # Add handlers
        application.add_handler(conv_handler)
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


        # Add error handler
        application.add_error_handler(error_handler)

        logger.info("Telegram bot setup completed successfully")
        return application

    except Exception as e:
        logger.error(f"Error setting up Telegram bot: {str(e)}", exc_info=True)
        raise

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