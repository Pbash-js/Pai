# routes.py

import logging
from typing import Dict, Any
import requests
from fastapi import FastAPI,APIRouter, Depends, Request, Response, responses
from sqlalchemy.ext.asyncio import AsyncSession
import time
from database import get_db, crud
from llm.processor import LLMProcessor
from services.reminder import ReminderService
from services.calendar import CalendarService
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from api.schemas import TelegramWebhookPayload
import os
import asyncio
#changes
import json
from services.timeprocessor import TimeProcessor
import random

# Import OAuth library
from authlib.integrations.starlette_client import OAuth

# Initialize OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
oauth = OAuth()
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)
time_processor = TimeProcessor()
friendly_phrases = [
    "Got it! 👍",
    "All set! ✅",
    "Done! 😊",
    "No worries, I've added it! 📅"
]
##changes

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Define the API prefix centrally ---
API_PREFIX = "/api"
# --------------------------------------

# Initialize Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)

llm_processor = LLMProcessor()

@router.post("/webhook")
async def webhook(payload: TelegramWebhookPayload, db: AsyncSession = Depends(get_db)):
    """Endpoint for receiving Telegram webhook events."""
    try:
        # Convert incoming JSON to Telegram Update object
        update = Update.de_json(payload.dict(), telegram_bot)

        # Check if message exists
        if not update.message or not update.message.text:
            return Response(status_code=200)

        sender_id = update.message.chat.id
        message_text = update.message.text

        # Get or create user
        user = await crud.get_or_create_user(db, sender_id)
        user_id = user.id

        logger.info(f"User details - {user}")

        retry_count = 0
        while not user.google_id and retry_count < 3:
            retry_count += 1
            # If user is not linked to Google, send login link
            logger.info(f"User {user.id} not linked to Google, sending login link.")
            await handle_google_login(sender_id, db)
            user = await crud.get_user_by_id(db, user.id)
            if hasattr(user, 'google_id') and user.google_id:
                # User has logged in, update user details
                break
            else:
                await asyncio.sleep(300)  # Wait for a while before retrying

        if retry_count == 3 and not user.google_id:
            await telegram_bot.send_message(
                chat_id=sender_id,
                text="Please log in to your Google account to use this feature."
            )
            return {"status": "NOT LOGGED IN"}

        # Add this inside your webhook function, before processing the message with LLM
        if message_text.startswith("/start"):
            command_parts = message_text.split()
            if len(command_parts) > 1 and command_parts[1] == "auth_success":
                # User has successfully authenticated
                await telegram_bot.send_message(
                    chat_id=sender_id,
                    text="✅ Your Google account has been successfully linked! You can now use all features."
                )
                return {"status": "success"}


        # Get conversation history
        conversation_history = await crud.get_session_history(db, user.id)

        # Add user message to history
        await crud.update_session_history(
            db,
            user_id,
            {"role": "user", "content": message_text}
        )

        # Process message with LLM
        if update.message.photo:
            # Get largest size photo
            photo_file = update.message.photo[-1].get_file()
            photo_url = photo_file.file_path
            
            # Forward photo URL to LLM processor
            llm_response = await llm_processor.process_multimodal_message(
                message_text, photo_url, conversation_history
            )
        else:
            logger.info(f"Sending message - {message_text}")
            llm_response = await llm_processor.process_message(message_text, conversation_history)
            logger.info(f"Got response from LLM: {llm_response}")

        # Ensure function_calls is a list
        function_calls = llm_response.get("function_calls", [])
        
        # Execute any function calls
        function_results = []
        for func_call in function_calls:
            result = execute_function_call(db, user_id, func_call)
            function_results.append(result)

        # Determine response text
        if function_calls and llm_response["response_text"] == "":
            # Process function results through LLM
            llm_function_response = await llm_processor.process_function_result(
                function_calls, 
                function_results[0] if len(function_results) == 1 else function_results, 
                conversation_history
            )
            response_text = llm_function_response.get("response_text", llm_response.get("response_text", "I'm not sure how to respond."))
        else:
            # Use original LLM response if no function calls
            response_text = llm_response.get("response_text", "I'm not sure how to respond.")

        # Add bot response to history
        await crud.update_session_history(
            db,
            user_id,
            {"role": "assistant", "content": response_text}
        )

        # Send response back to user
        await telegram_bot.send_message(
            chat_id=sender_id,
            text=escape_markdown(response_text, version=2),
            parse_mode=ParseMode.MARKDOWN_V2
        )

        # Return a simple dict that can be easily serialized
        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return Response(content=json.dumps({"error": str(e)}), status_code=500, media_type="application/json")


def get_ngrok_url():
    try:
        # Ensure you are running ngrok on the same port your FastAPI app uses (e.g., 8000)
        # If your main.py runs on port 8000, ngrok command should be: ngrok http 8000
        response = requests.get("http://127.0.0.1:4040/api/tunnels")
        data = response.json()
        # Find the HTTPS tunnel
        https_tunnel = next((t for t in data.get('tunnels', []) if t.get('proto') == 'https'), None)
        if https_tunnel:
            url = https_tunnel['public_url']
            print(f"Using Ngrok HTTPS URL: {url}")
            return url
        else:
            logger.error("Could not find HTTPS tunnel in ngrok API response.")
            return None # Or raise an error
    except requests.exceptions.ConnectionError:
        logger.error("Could not connect to ngrok API. Is ngrok running?")
        return None # Or raise an error
    except Exception as e:
        logger.error(f"Error fetching ngrok URL: {e}")
        return None # Or raise an error


async def handle_google_login(sender_id: int, db: AsyncSession):
    ngrok_url = get_ngrok_url()
    if not ngrok_url:
        await telegram_bot.send_message(
            chat_id=sender_id,
            text="Sorry, there was an error generating the login link. Please try again later."
        )
        return

    # --- Add the API_PREFIX here ---
    google_oauth_url = f"{ngrok_url}{API_PREFIX}/auth/login?telegram_id={sender_id}"
    # -------------------------------

    await telegram_bot.send_message(
        chat_id=sender_id,
        text=f"To use this bot, I need to connect to your Google account\\.\n\n[Click here to log in]({google_oauth_url})\n\n⚠️ Important: When you click the link, you'll see an Ngrok warning page\\. You MUST click 'Visit Site' to continue to Google login\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

def execute_function_call(db: AsyncSession, user_id: int, func_call: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a function call from the LLM."""
    function_name = func_call["name"]
    args = func_call["args"]

    reminder_service = ReminderService(db)
    calendar_service = CalendarService(db)
    logger.info(f"Executing function {function_name}")
    try:
        # changes Preprocess natural date/time inputs
        if function_name in ["setReminder", "scheduleEvent", "setRecurringReminder"]:
            natural_time = time_processor.parse_natural_time(args.get("message", "") + " " + args.get("title", ""))
            if natural_time["date"]:
                args["date"] = natural_time["date"]
            if natural_time["time"]:
                args["time"] = natural_time["time"]
            if natural_time["recurrence"]:
                args["repeat"] = natural_time["recurrence"]
        # changes

        if function_name == "setReminder":
            return reminder_service.set_reminder(user_id, args)
        #changes
        if function_name == "getReminder":
            return reminder_service.get_upcoming_reminders(user_id, args)
        #changes
        elif function_name == "scheduleEvent":
            return calendar_service.schedule_event(user_id, args)

        elif function_name == "getUpcomingEvents":
            date_range = args.get("date_range", "next 7 days")
            events = calendar_service.get_upcoming_events(user_id, date_range)
            reminders = reminder_service.get_upcoming_reminders(user_id, date_range)

            return {
                "status": "success",
                "events": events,
                "reminders": reminders
            }

        elif function_name == "cancelEvent":
            return calendar_service.cancel_event(user_id, args)

        elif function_name == "setRecurringReminder":
            return reminder_service.set_recurring_reminder(user_id, args)

        else:
            return {
                "status": "error",
                "message": f"Unknown function: {function_name}"
            }

    except Exception as e:
        logger.error(f"Error executing {function_name}: {e}")
        return {
            "status": "error",
            "message": f"Error executing {function_name}: {str(e)}"
        }

@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

@router.get("/auth/login")
async def login(request: Request, telegram_id: str):
    ngrok_url = get_ngrok_url()
    if not ngrok_url:
         return responses.JSONResponse({"error": "Could not determine redirect URI"}, status_code=500)

    # --- Add the API_PREFIX here ---
    redirect_uri = f"{ngrok_url}{API_PREFIX}/auth/callback"
    # -------------------------------

    logger.info(f"Redirecting user {telegram_id} to Google OAuth. Callback URL: {redirect_uri}")
    return await oauth.google.authorize_redirect(
        request,
        redirect_uri,
        state=telegram_id  # Pass the Telegram ID as state
    )

@router.get("/auth/callback")
async def auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    logger.info(f"CALLBACK RECEIVED: {request.url}")
    try:
        token = await oauth.google.authorize_access_token(request)
        logger.info(f"TOKEN AUTHORIZED (keys): {token.keys()}") # Log keys, not full token
    except Exception as e:
        logger.error(f"Error during authorize_access_token: {e}", exc_info=True)
        return responses.JSONResponse({"error": "Failed to authorize access token"}, status_code=400)

    user_info = token.get('userinfo')
    if not user_info:
        logger.error("Userinfo not found in token response.")
        # Optionally, attempt to fetch userinfo manually if needed and configured
        # resp = await oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo', token=token)
        # user_info = resp.json()
        # if not user_info:
        #     return responses.RedirectResponse(f'{API_PREFIX}/auth/login') # Send back to login
        return responses.JSONResponse({"error": "Failed to get user info"}, status_code=400)


    # Get the Telegram ID from state
    state = request.query_params.get('state')
    logger.info(f"State received from callback: {state}")

    # Store user session and link to Telegram ID
    if state and state.isdigit():
        # Convert to integer
        telegram_id = int(state)
        # Update the user in database with Google info
        try:
            updated_user = await crud.update_user_google_info(db, telegram_id, {
                "google_id": user_info.get("sub"), # Use 'sub' for Google ID
                "email": user_info.get("email"),
                "name": user_info.get("name"),
                # Store tokens securely if needed for future API calls
                # "access_token": token.get("access_token"),
                # "refresh_token": token.get("refresh_token"),
                # "expires_at": token.get("expires_at")
            })
            if updated_user:
                 logger.info(f"Successfully linked Google account for Telegram ID: {telegram_id}, User details: {user_info.get('email')}")
            else:
                 logger.warning(f"Attempted to link Google account, but no user found for Telegram ID: {telegram_id}")
                 # Handle case where user might not exist yet in your DB for that telegram_id
                 # Maybe create the user here if get_or_create_user wasn't called before login flow initiated
                 return responses.JSONResponse({"error": "User not found for Telegram ID"}, status_code=404)


        except Exception as e:
             logger.error(f"Error updating user google info for telegram_id {telegram_id}: {e}", exc_info=True)
             return responses.JSONResponse({"error": "Database error during user update"}, status_code=500)


        # Use the deep linking with proper bot username
        # !!!! IMPORTANT: Replace 'your_bot' with your actual bot username !!!!
        bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "PaiMyBot") # Get from env or default
        if bot_username == "your_bot":
            logger.warning("TELEGRAM_BOT_USERNAME environment variable not set. Using default 'your_bot'. Please set it.")

        deep_link_url = f'https://t.me/{bot_username}?start=auth_success'
        logger.info(f"Redirecting user to Telegram deep link: {deep_link_url}")
        return responses.RedirectResponse(deep_link_url)
    else:
        logger.error(f"Invalid or missing state (telegram_id) in callback: {state}")
        return responses.JSONResponse({"error": "Invalid or missing Telegram ID in state parameter"}, status_code=400)

# --- Make sure you have placeholders for the functions called by webhook ---
# Add dummy functions if they don't exist or ensure they are correctly imported/defined
def dummy_function(*args, **kwargs):
    logger.warning(f"Called dummy function with args: {args}, kwargs: {kwargs}")
    return {"status": "executed dummy function"}

# Ensure execute_function_call handles all cases or defaults safely
# (The original execute_function_call looked mostly fine, just ensure all referenced services/methods exist)
# --------------------------------------------------------------------------