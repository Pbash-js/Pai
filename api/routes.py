# routes.py

import logging
from typing import Dict, Any, List, Optional # Add List, Optional
import requests
from fastapi import FastAPI,APIRouter, Depends, Request, Response, responses,status 
from sqlalchemy.ext.asyncio import AsyncSession
import time
from database import get_db, crud
from llm.processor import LLMProcessor
from services.reminder import ReminderService
from services.calendar import CalendarService
# << --- START Notion Integration --- >>
from services.notion import NotionService # Import Notion Service
# << --- END Notion Integration --- >>
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
# <<-- Adjust import path if necessary -->>
from api.schemas import TelegramWebhookPayload
# <<-- End import path adjustment -->>
import os
import asyncio
import json
# <<-- Remove TimeProcessor if not used directly here -->>
# from services.timeprocessor import TimeProcessor
# <<-- End remove TimeProcessor -->>
import random

# Import OAuth library
from authlib.integrations.starlette_client import OAuth

logger = logging.getLogger(__name__)

# --- Config & Initializations ---
API_PREFIX = "/api"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN environment variable not set!")
    # raise ValueError("TELEGRAM_BOT_TOKEN is required") # Or exit
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "PaiMyBot") # Use this later

# --- Add Template ID Config ---
NOTION_TEMPLATE_ID = os.getenv("NOTION_TEMPLATE_ID")
if not NOTION_TEMPLATE_ID:
    # Log a warning or raise an error if template duplication is truly mandatory
    logger.warning("NOTION_TEMPLATE_ID environment variable not set. Template duplication cannot be offered/enforced.")
# --- End Template ID Config ---



# --- OAuth Setup ---
oauth = OAuth()

# Google OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name='google',
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/tasks' # Add scopes needed
            # Add other Google scopes if you implement Google Calendar/Tasks API calls
            }
    )
else:
    logger.warning("Google Client ID or Secret not configured. Google OAuth disabled.")

# << --- START Notion Integration --- >>
# Notion OAuth
NOTION_CLIENT_ID = os.getenv("NOTION_CLIENT_ID")
NOTION_CLIENT_SECRET = os.getenv("NOTION_CLIENT_SECRET")
if NOTION_CLIENT_ID and NOTION_CLIENT_SECRET:
    oauth.register(
        name='notion',
        client_id=NOTION_CLIENT_ID,
        client_secret=NOTION_CLIENT_SECRET,
        authorize_url='https://api.notion.com/v1/oauth/authorize',
        access_token_url='https://api.notion.com/v1/oauth/token',
        # Notion uses HTTP Basic Auth for token endpoint, authlib handles this
        client_kwargs=None,
        # userinfo_endpoint='https://api.notion.com/v1/users/me', # Optional: fetch user info if needed
        # authorize_params={'owner': 'user'} # Important: To get user token
    )
else:
    logger.warning("Notion Client ID or Secret not configured. Notion OAuth disabled.")
# << --- END Notion Integration --- >>

# --- Services & Utilities ---
# Remove TimeProcessor if LLM handles time extraction directly via function params
# time_processor = TimeProcessor()
llm_processor = LLMProcessor() # Initialize LLM Processor

friendly_phrases = [
    "Got it! 👍", "All set! ✅", "Done! 😊", "No worries, I've handled that! ✨",
    "Okay, consider it done!", "Roger that!", "Affirmative! ✅"
]

router = APIRouter()

# --- Helper Functions ---

def get_ngrok_url():
    """Fetches the public HTTPS URL from the local ngrok API."""
    try:
        response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
        response.raise_for_status() # Raise exception for bad status codes
        data = response.json()
        https_tunnel = next((t for t in data.get('tunnels', []) if t.get('proto') == 'https'), None)
        if https_tunnel and https_tunnel.get('public_url'):
            url = https_tunnel['public_url']
            logger.info(f"Using Ngrok HTTPS URL: {url}")
            return url
        else:
            logger.error("Could not find HTTPS tunnel in ngrok API response.")
            return None
    except requests.exceptions.ConnectionError:
        logger.error("Could not connect to ngrok API (is ngrok running on port 4040?).")
        return None
    except Exception as e:
        logger.error(f"Error fetching ngrok URL: {e}", exc_info=True)
        return None

async def send_auth_link(sender_id: int, service_name: str, auth_url: str, instructions: str):
    """Sends a formatted authentication link message via Telegram."""
    service_name_cap = service_name.capitalize()
    base_text = f"To use {service_name_cap} features, I need to connect to your {service_name_cap} account\\."
    link_text = f"[Click here to log in to {service_name_cap}]({auth_url})"
    full_text = f"{base_text}\n\n{link_text}\n\n{instructions}"

    try:
        await telegram_bot.send_message(
            chat_id=sender_id,
            text=full_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True # Optional: disable link preview
        )
    except Exception as e:
        logger.error(f"Failed to send {service_name_cap} auth link to {sender_id}: {e}")


async def handle_google_login(sender_id: int):
    """Generates Google login URL and sends it to the user."""
    if not GOOGLE_CLIENT_ID: # Check if Google OAuth is configured
        logger.warning("Attempted Google login, but Google OAuth is not configured.")
        await telegram_bot.send_message(sender_id, "Sorry, Google integration is currently unavailable.")
        return

    ngrok_url = get_ngrok_url()
    if not ngrok_url:
        await telegram_bot.send_message(sender_id, "Sorry, there was an error generating the login link. Please try again later.")
        return

    google_auth_url_path = f"{API_PREFIX}/auth/google/login?telegram_id={sender_id}"
    google_auth_url = f"{ngrok_url}{google_auth_url_path}"
    instructions = "⚠️ Important: If you see an Ngrok warning page, click 'Visit Site' to continue\\."
    await send_auth_link(sender_id, "google", google_auth_url, instructions)


# In routes.py -> handle_notion_login
async def handle_notion_login(sender_id: int):
    # ... (checks for NOTION_CLIENT_ID) ...

    ngrok_url = get_ngrok_url()
    if not ngrok_url:
        # ... (handle error) ...
        return

    # THIS is the URL that uses your /auth/notion/login route
    # which properly uses authlib's authorize_redirect
    notion_auth_url_path = f"{API_PREFIX}/auth/notion/login?telegram_id={sender_id}"
    notion_auth_url = f"{ngrok_url}{notion_auth_url_path}"

    instructions = "You'll be asked to authorize access to your Notion workspace\\."

    # --- SEND THIS URL ---
    await send_auth_link(sender_id, "notion", notion_auth_url, instructions)

    # --- REMOVE or COMMENT OUT reading from redirectURI.txt ---
    # webauthurl=""
    # file_path = os.path.join(os.getcwd(), 'redirectURI.txt')
    # try: # Add error handling if you keep it temporarily
    #     with open(file_path, 'r') as file:
    #         line = file.readline()
    #         webauthurl = line.strip()
    # except FileNotFoundError:
    #      logger.error(f"redirectURI.txt not found at {file_path}")
    #      await telegram_bot.send_message(sender_id, "Configuration error: Cannot find redirect URI file.")
    #      return
    # # await send_auth_link(sender_id, "notion", webauthurl, instructions) # Don't send this one

    
# Check if Notion access is required for a given function call
def requires_notion_auth(function_name: Optional[str]) -> bool:
    if not function_name:
        return False
    return function_name.lower().startswith("notion") or function_name in [
        "createNotionNote", "createNotionTable", "addNotionTableRow",
        # Add any other Notion function names here
    ]
# << --- END Notion Integration --- >>


# --- Core Webhook Logic ---

@router.post("/webhook")
async def webhook(payload: TelegramWebhookPayload, db: AsyncSession = Depends(get_db)):
    """Endpoint for receiving Telegram webhook events."""
    update = None
    sender_id = None
    try:
        update = Update.de_json(payload.dict(exclude_unset=True), telegram_bot)

        if not update.message or (not update.message.text and not update.message.photo):
            logger.info("Received update without message text or photo, ignoring.")
            return Response(status_code=200)

        sender_id = update.message.chat.id
        message_text = update.message.text or "" # Use empty string if no text (photo message)
        user = await crud.get_or_create_user(db, sender_id)
        user_id = user.id # Internal DB user ID

        logger.info(f"Received message from user_id: {user_id} (Telegram ID: {sender_id})")

        # --- Handle /start Command & Auth Success Redirects ---
        if message_text.startswith("/start"):
            parts = message_text.split()
            if len(parts) > 1:
                if parts[1] == "google_auth_success":
                    await telegram_bot.send_message(sender_id, "✅ Your Google account linked successfully!")
                    return {"status": "success", "message": "Google auth success handled"}
                # << --- START Notion Integration --- >>
                elif parts[1] == "notion_auth_success":
                    await telegram_bot.send_message(sender_id, "✅ Your Notion account linked successfully!")
                    return {"status": "success", "message": "Notion auth success handled"}
                # << --- END Notion Integration --- >>
                else:
                    # Handle other /start parameters if needed
                    pass
            else:
                # Generic welcome message for plain /start
                 await telegram_bot.send_message(sender_id, f"Hello {user.name or 'there'}! I'm Pai, your assistant. How can I help?")
                 return {"status": "success", "message": "Start command handled"}
            
        # Check if Notion is linked AND setup is needed
        if user.notion_access_token and not user.notion_setup_complete:
            notion_service = NotionService(db) # Instantiate the service
            logger.info(f"Webhook: Triggering Notion dashboard setup for potentially incomplete setup for user_id {user.id}...")
            # --- FIX: Pass user object, remove assignment ---
            # user.notion_setup_complete = await notion_service.setup_initial_dashboard(user_id) # OLD & WRONG
            await notion_service.setup_initial_dashboard(user) # CORRECTED: Call with user object
            # Refresh user object state after potential update in the service
            await db.refresh(user)
            logger.info(f"Webhook: Dashboard setup attempt finished. User {user.id} notion_setup_complete is now: {user.notion_setup_complete}")
            # --- END FIX ---
        elif not user.notion_access_token:
            # Existing logic to send login link if token is missing
            logger.info(f"User {user.id} not linked, sending login link.")
            await handle_notion_login(sender_id)
            await telegram_bot.send_message(sender_id, "Please link your Notion account using the message above to use Notion features.")
            return {"status": "AUTH_REQUIRED", "service": "notion"}


        logger.info(f"User notion status: {user.notion_setup_complete}")

        if not user.notion_setup_complete:
            notion_service = NotionService(db) # Instantiate the service
            logger.info(f"Triggering Notion dashboard setup for user_id {user_id})...")
            user.notion_setup_complete = await notion_service.setup_initial_dashboard(user_id)

        # --- Process Message with LLM ---
        conversation_history = await crud.get_session_history(db, user_id)
        await crud.update_session_history(db, user_id, {"role": "user", "content": message_text or "[Image Received]"}) # Add user message

        if update.message.photo:
            photo_file_id = update.message.photo[-1].file_id
            # TODO: Download the photo file using telegram_bot.get_file and save temporarily
            # Pass the temporary file path to process_multimodal_message
            # Example (needs proper async file handling):
            # file = await telegram_bot.get_file(photo_file_id)
            # temp_path = f"/tmp/{photo_file_id}.jpg" # Use tempfile module ideally
            # await file.download_to_drive(temp_path)
            # llm_response = await llm_processor.process_multimodal_message(message_text, temp_path, conversation_history)
            # os.remove(temp_path) # Clean up
            logger.warning("Photo processing not fully implemented yet.")
            llm_response = {"response_text": "Sorry, I can't process images yet.", "function_calls": []} # Placeholder
        else:
            llm_response = await llm_processor.process_message(message_text, conversation_history)

        response_text = llm_response.get("response_text", "")
        function_calls = llm_response.get("function_calls", [])

        final_response_text = response_text # Start with initial LLM text

        # --- Execute Function Calls (if any) ---
        if function_calls:
            executed_results = []
            requires_re_auth = None

            for func_call in function_calls:
                func_name = func_call.get("name")
                args = func_call.get("args", {})

                # << --- START Notion Integration --- >>
                # Check Notion Auth requirement
                if requires_notion_auth(func_name) and not user.notion_access_token and NOTION_CLIENT_ID:
                    logger.info(f"User {user_id} needs Notion auth for function {func_name}.")
                    await handle_notion_login(sender_id)
                    # Prepare a message indicating auth is needed, skip execution
                    final_response_text = f"To {func_name.replace('Notion', '').lower()}, I need access to your Notion. Please use the link above to connect."
                    requires_re_auth = "notion"
                    executed_results = [] # Clear any previous results as we stop execution
                    break # Stop processing further function calls for this message
                # << --- END Notion Integration --- >>

                # Execute the function
                # Make execute_function_call async
                result_data = await execute_function_call(db, user_id, func_call)
                executed_results.append({
                    "function_name": func_name,
                    "result": result_data # Store {'status': '...', 'message': '...', ...}
                })

            # --- Process Function Results ---
            if requires_re_auth:
                # Response already set to ask for auth, just skip further processing
                pass
            elif executed_results:
                successful_calls = [res for res in executed_results if res["result"].get("status") == "success"]
                failed_calls = [res for res in executed_results if res["result"].get("status") != "success"]

                # Generate response based on execution results
                if not final_response_text: # If LLM didn't provide text, use function result messages
                    if successful_calls and not failed_calls:
                         final_response_text = successful_calls[0]["result"].get("message", random.choice(friendly_phrases))
                    elif failed_calls:
                         final_response_text = failed_calls[0]["result"].get("message", "Sorry, something went wrong.")
                    else:
                         final_response_text = "Okay." # Should not happen if executed_results exists
                else: # If LLM provided text, maybe append status or use function message
                     if successful_calls and not failed_calls:
                          func_message = successful_calls[0]["result"].get("message")
                          # Replace LLM text if function message is informative, otherwise append friendly phrase
                          if func_message and len(func_message) > 20: # Heuristic for informative message
                               final_response_text = func_message
                          elif final_response_text not in friendly_phrases: # Avoid double "Got it! Got it!"
                               final_response_text += f"\n\n{random.choice(friendly_phrases)}"
                     elif failed_calls:
                          func_message = failed_calls[0]["result"].get("message")
                          final_response_text += f"\n\n⚠️ {func_message or 'I encountered an issue.'}"

                # --- Option: Send results back to LLM for summarization ---
                # This adds latency but can produce more natural responses
                # if len(executed_results) > 0 and (not response_text or requires_re_auth is None):
                #     # Prepare function response parts for LLM
                #     function_responses_for_llm = []
                #     for res in executed_results:
                #         function_responses_for_llm.append(
                #              # Assuming llm_processor can take {name: ..., response: {...}}
                #             {"name": res["function_name"], "response": res["result"]}
                #         )
                #     # TODO: Implement sending list of function responses back
                #     # llm_summary_response = await llm_processor.process_function_results_list(...)
                #     # final_response_text = llm_summary_response.get("response_text", ...)
                #     pass # Placeholder for now


        # --- Final Response ---
        if not final_response_text:
             final_response_text = "Sorry, I'm not sure how to respond to that."
             logger.warning(f"No final response generated for user {user_id}. Original message: '{message_text}' LLM Response: {llm_response}")

        # Add final assistant response to history
        await crud.update_session_history(db, user_id, {"role": "assistant", "content": final_response_text})

        # Send response to user
        await telegram_bot.send_message(
            chat_id=sender_id,
            text=escape_markdown(final_response_text, version=2),
            parse_mode=ParseMode.MARKDOWN_V2
        )

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Unhandled error in webhook for sender {sender_id}: {e}", exc_info=True)
        # Attempt to notify user of generic error if possible
        if sender_id and telegram_bot:
            try:
                await telegram_bot.send_message(sender_id, " apologise, I encountered an unexpected error. Please try again later.")
            except Exception as send_error:
                 logger.error(f"Failed to send error message to user {sender_id}: {send_error}")
        # Return 500 status
        error_content = json.dumps({"error": "Internal Server Error"})
        return Response(content=error_content, status_code=500, media_type="application/json")


# --- Function Execution Logic ---

async def execute_function_call(db: AsyncSession, user_id: int, func_call: Dict[str, Any]) -> Dict[str, Any]:
    """Executes a function call requested by the LLM. Needs to be async."""
    function_name = func_call.get("name")
    args = func_call.get("args", {})
    logger.info(f"Executing function '{function_name}' for user {user_id} with args: {args}")

    # Instantiate services (Consider using FastAPI dependencies for cleaner injection)
    reminder_service = ReminderService(db)
    calendar_service = CalendarService(db)
    # << --- START Notion Integration --- >>
    notion_service = NotionService(db)
    # << --- END Notion Integration --- >>

    try:
        # --- Internal Bot Functions ---
        if function_name == "setReminder":
            # Assuming service method is now async
            # result = await reminder_service.set_reminder(user_id, args)
             # Simulate success for now, replace with actual async call
            await asyncio.sleep(0.1) # Simulate async work
            result = {"status": "success", "message": f"Reminder '{args.get('message')}' set.", "details": args}
            return result

        elif function_name == "getReminder":
            # result = await reminder_service.get_upcoming_reminders(user_id, args.get("date_range"))
            await asyncio.sleep(0.1)
            reminders = [{"message": "Test reminder", "time": "10:00"}] # Placeholder
            return {"status": "success", "message": f"Found {len(reminders)} reminders.", "reminders": reminders}

        elif function_name == "scheduleEvent":
            # result = await calendar_service.schedule_event(user_id, args)
            await asyncio.sleep(0.1)
            result = {"status": "success", "message": f"Event '{args.get('title')}' scheduled.", "details": args}
            return result

        elif function_name == "getUpcomingEvents":
            # events = await calendar_service.get_upcoming_events(user_id, args.get("date_range"))
            # reminders = await reminder_service.get_upcoming_reminders(user_id, args.get("date_range")) # Maybe combine?
            await asyncio.sleep(0.1)
            events = [{"title": "Test Event", "time": "14:00"}] # Placeholder
            return {"status": "success", "message": f"Found {len(events)} events.", "events": events}

        elif function_name == "cancelEvent":
            # result = await calendar_service.cancel_event(user_id, args)
            await asyncio.sleep(0.1)
            result = {"status": "success", "message": f"Event '{args.get('event_title')}' cancelled."}
            return result

        # << --- START Notion Integration --- >>
        elif function_name == "createNotionNote":
             # Need to find parent_page_id from parent_page_title
             parent_title = args.get("parent_page_title")
             parent_page_id = None
             if parent_title:
                  parent_page_id = await notion_service.find_page_by_title(user_id, parent_title)
                  if not parent_page_id:
                       return {"status": "error", "message": f"Could not find the parent page '{parent_title}' in your Notion."}

             if not parent_page_id: # Still no ID
                  return {"status": "error", "message": "Parent page title was missing or page not found."}

             result = await notion_service.create_note_page(
                 user_id=user_id,
                 title=args.get("title", "Untitled Note"),
                 content=args.get("content", ""),
                 parent_page_id=parent_page_id
             )
             return result

        elif function_name == "createNotionTable":
            parent_title = args.get("parent_page_title")
            parent_page_id = None
            if parent_title:
                parent_page_id = await notion_service.find_page_by_title(user_id, parent_title)
                if not parent_page_id:
                    return {"status": "error", "message": f"Could not find the parent page '{parent_title}' in your Notion."}

            if not parent_page_id:
                return {"status": "error", "message": "Parent page title was missing or page not found."}

            properties_schema = args.get("properties_schema", {})
            # TODO: Add validation/conversion for properties_schema if needed
            result = await notion_service.create_tracking_database(
                user_id=user_id,
                title=args.get("title", "Untitled Table"),
                properties_schema=properties_schema,
                parent_page_id=parent_page_id
            )
            return result

        elif function_name == "addNotionTableRow":
             # Need to find database_id from database_title
             db_title = args.get("database_title")
             database_id = None # TODO: Implement find_database_by_title in NotionService
             if db_title:
                  # database_id = await notion_service.find_database_by_title(user_id, db_title)
                  logger.warning(f"Need to implement find_database_by_title to get ID for '{db_title}'")
                  # Placeholder: Assume LLM might provide ID directly in future or user context has it
                  pass # Remove this pass when find_database_by_title is implemented

             if not database_id: # Replace with actual check after implementation
                  # For now, try using the title directly if ID is missing (will likely fail API call)
                  database_id = db_title # TEMPORARY - REMOVE LATER
                  # return {"status": "error", "message": f"Could not find the table '{db_title}' in your Notion."}
                  logger.warning(f"Using title '{db_title}' as potential ID - likely needs find_database_by_title implementation.")


             entry_data = args.get("entry_data", {})
             if not database_id:
                  return {"status": "error", "message": "Database title missing or database not found."}


             result = await notion_service.add_entry_to_database(
                 user_id=user_id,
                 database_id=database_id,
                 entry_data=entry_data
             )
             return result
        # << --- END Notion Integration --- >>

        # --- Fallback ---
        else:
            logger.warning(f"Unknown function called: {function_name}")
            return {"status": "error", "message": f"Sorry, I don't know how to perform the action: {function_name}"}

    except Exception as e:
        logger.error(f"Error executing function '{function_name}' for user {user_id}: {e}", exc_info=True)
        return {"status": "error", "message": "Sorry, an internal error occurred while performing that action."}


# --- Health Check ---
@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

# --- Google OAuth Routes ---
@router.get("/auth/google/login")
async def google_login_redirect(request: Request, telegram_id: str):
    """Redirects user to Google for authentication."""
    if not GOOGLE_CLIENT_ID:
        return responses.JSONResponse({"error": "Google OAuth not configured"}, status_code=501)

    ngrok_url = get_ngrok_url()
    if not ngrok_url:
         return responses.JSONResponse({"error": "Could not determine redirect URI"}, status_code=500)

    redirect_uri = f"{ngrok_url}{API_PREFIX}/auth/google/callback"
    logger.info(f"Redirecting user {telegram_id} to Google OAuth. Callback: {redirect_uri}")

    # Make sure 'google' matches the name registered in oauth.register
    return await oauth.google.authorize_redirect(request, redirect_uri, state=telegram_id)

@router.get("/auth/google/callback")
async def google_auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handles the callback from Google after authentication."""
    if not GOOGLE_CLIENT_ID:
        return responses.JSONResponse({"error": "Google OAuth not configured"}, status_code=501)

    try:
        token = await oauth.google.authorize_access_token(request)
        logger.info(f"Google token authorized successfully for state: {request.query_params.get('state')}")
    except Exception as e:
        logger.error(f"Google OAuth callback error during token authorization: {e}", exc_info=True)
        return responses.JSONResponse({"error": "Failed to authorize Google access token", "details": str(e)}, status_code=400)

    user_info = token.get('userinfo')
    if not user_info:
        # Try fetching manually if not included (rare for Google with openid scope)
        try:
            resp = await oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo', token=token)
            resp.raise_for_status()
            user_info = resp.json()
        except Exception as e:
             logger.error(f"Failed to fetch Google userinfo manually: {e}", exc_info=True)
             return responses.JSONResponse({"error": "Failed to get Google user info"}, status_code=400)

    state = request.query_params.get('state')
    if not state or not state.isdigit():
        logger.error(f"Invalid or missing state (telegram_id) in Google callback: {state}")
        return responses.JSONResponse({"error": "Invalid state parameter"}, status_code=400)

    telegram_id = int(state)
    try:
        # Prepare data, including tokens if needed later
        google_data = {
            "google_id": user_info.get("sub"),
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            # Add token storage if calling Google APIs later
            # "access_token": token.get("access_token"),
            # "refresh_token": token.get("refresh_token"),
            # "expires_at": datetime.utcnow() + timedelta(seconds=token.get("expires_in", 3600))
        }
        updated_user = await crud.update_user_google_info(db, telegram_id, google_data)

        if not updated_user:
            logger.error(f"Failed to find/update user for Telegram ID {telegram_id} during Google callback.")
            return responses.JSONResponse({"error": "User not found"}, status_code=404)

        logger.info(f"Successfully linked Google account for Telegram ID: {telegram_id}")
        # Redirect back to Telegram bot
        deep_link_url = f'https://t.me/{TELEGRAM_BOT_USERNAME}?start=google_auth_success'
        return responses.RedirectResponse(deep_link_url)

    except Exception as e:
        logger.error(f"Error updating user Google info for telegram_id {telegram_id}: {e}", exc_info=True)
        return responses.JSONResponse({"error": "Database error during user update"}, status_code=500)

# << --- START Notion Integration --- >>
# --- Notion OAuth Routes ---
@router.get("/auth/notion/login")
async def notion_login_redirect(request: Request, telegram_id: str):
    """Redirects user to Notion for authentication."""
    if not NOTION_CLIENT_ID:
        return responses.JSONResponse({"error": "Notion OAuth not configured"}, status_code=501)
    
    if not NOTION_TEMPLATE_ID:
        # If mandatory, return error here if template ID isn't configured
        logger.error("Notion Template ID is not configured, cannot proceed with mandatory duplication flow.")
        return responses.JSONResponse({"error": "Notion integration configuration incomplete (missing template ID)."}, status_code=500)

    ngrok_url = get_ngrok_url()
    if not ngrok_url:
         return responses.JSONResponse({"error": "Could not determine redirect URI"}, status_code=500)

    redirect_uri = f"{ngrok_url}{API_PREFIX}/auth/notion/callback"
    logger.info(f"Redirecting user {telegram_id} to Notion OAuth. Callback: {redirect_uri}")

    # --- FIX: Add a prefix to the state value ---
    state_value = f"tgid_{telegram_id}"
    logger.info(f"Redirecting user {telegram_id} to Notion OAuth. Callback: {redirect_uri}, State: {state_value}, Requesting Duplication of Template: {NOTION_TEMPLATE_ID}")
    # --- End Fix ---

    # Include 'owner=user' to ensure we get a user token
    return await oauth.notion.authorize_redirect(request, redirect_uri, state=state_value, owner='user',template_id=NOTION_TEMPLATE_ID)

@router.get("/auth/notion/callback")
async def notion_auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handles the callback from Notion after authentication and sets up dashboard."""
    if not NOTION_CLIENT_ID:
        return responses.JSONResponse({"error": "Notion OAuth not configured"}, status_code=501)

    telegram_id_int = None # Initialize telegram_id

    try:
        returned_state = request.query_params.get('state')
        if not returned_state:
             logger.error("State parameter missing in Notion callback query parameters.")
             return responses.JSONResponse({"error": "State parameter missing in callback"}, status_code=400)

        # Authorize token (this also verifies state against session)
        token_data = await oauth.notion.authorize_access_token(request)
        logger.info(f"Authlib processed Notion token data: {token_data}")
        logger.info(f"Notion token authorized successfully for state: {returned_state}")
        if isinstance(token_data, dict):
         logger.info(f"Keys in token_data: {token_data.keys()}")
         logger.info(f"Value for 'duplicated_template_id': {token_data.get('duplicated_template_id')}")


                # --- MANDATORY CHECK for Duplicated Template ID ---
        duplicated_template_id = token_data.get("duplicated_template_id")
        if not duplicated_template_id:
            logger.error(f"Mandatory template duplication failed for state {returned_state}. 'duplicated_template_id' missing in token response.")
            # Option 1: Redirect to a specific error message in Telegram
            # error_deep_link = f'https://t.me/{TELEGRAM_BOT_USERNAME}?start=notion_auth_error_no_duplicate'
            # return responses.RedirectResponse(error_deep_link)

            # Option 2: Return an error response directly (browser shows this)
            error_message = ("Notion connection failed: Required template duplication was skipped. "
                             "Please try connecting again and ensure you click 'Duplicate' "
                             "when prompted by Notion to allow Pai to create its dashboard.")
            # You could return HTML for a nicer error page
            return responses.JSONResponse(
                {"error": "Template duplication required", "message": error_message},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        # --- END MANDATORY CHECK ---


        # Parse the telegram_id from the verified state
        if not returned_state.startswith("tgid_"):
            logger.error(f"Invalid state prefix in Notion callback: {returned_state}")
            raise ValueError("Invalid state format received from Notion callback")

        telegram_id_str = returned_state.split("_", 1)[1]
        telegram_id_int = int(telegram_id_str) # Use this for DB operations

    except ValueError as e:
         logger.error(f"Failed to parse telegram_id from state '{returned_state}': {e}")
         return responses.JSONResponse({"error": "Invalid state format received"}, status_code=400)
    except Exception as e: # General authlib/Notion token errors
        logger.error(f"Notion OAuth callback error during token authorization: {e}", exc_info=True)
        details = str(e)
        return responses.JSONResponse({"error": "Failed to authorize Notion access token", "details": details}, status_code=400)

    if telegram_id_int is None:
         logger.error("Telegram ID could not be determined from the callback state.")
         return responses.JSONResponse({"error": "Failed to identify user from callback"}, status_code=400)

    try:

        # --- If check passes, proceed as before ---
        # 1. Prepare data for storage (now guaranteed to have template id)
        notion_user_data = {
            "access_token": token_data.get("access_token"),
            "bot_id": token_data.get("bot_id"),
            "workspace_name": token_data.get("workspace_name"),
            "duplicated_template_id": duplicated_template_id # Use the verified ID
        }

        # --- ADD LOGGING BEFORE UPDATE ---
        logger.info(f"Attempting to update user {telegram_id_int} with Notion data: {notion_user_data}")
        # --- END LOGGING ---
        updated_user = await crud.update_user_notion_info(db, telegram_id_int, notion_user_data)

        # --- ADD LOGGING AFTER UPDATE ---
        if updated_user:
            logger.info(f"CRUD update returned user object. Checking template ID on object: {getattr(updated_user, 'duplicated_template_id', 'Attribute Missing')}")
        else:
            logger.error("CRUD update did not return a user object.")
            return responses.JSONResponse({"error": "Failed to update user data"}, status_code=500)
        # --- END LOGGING ---

        logger.info(f"Successfully linked Notion account for Telegram ID: {telegram_id_int}")

        # --- 3. SETUP NOTION DASHBOARD ---
        notion_service = NotionService(db) # Instantiate the service
        internal_user_id = updated_user.id # Get the internal DB user ID

        logger.info(f"Triggering Notion dashboard setup for user_id {internal_user_id} (Telegram ID: {telegram_id_int})...")
        setup_successful = await notion_service.setup_initial_dashboard(internal_user_id)
        if setup_successful:
             logger.info(f"Notion dashboard setup completed (or was already done) for user_id {internal_user_id}.")
             # Optionally send another message? Or just rely on the standard success redirect.
        else:
             logger.error(f"Notion dashboard setup failed for user_id {internal_user_id}. User may need to retry or check permissions.")
             # Maybe send a specific error message? Be careful not to overwhelm the user.
             # await telegram_bot.send_message(telegram_id_int, "I linked your Notion account, but had trouble setting up the default dashboard. You can still use Notion features.")

        # --- END SETUP ---

        # 4. Redirect back to Telegram bot
        deep_link_url = f'https://t.me/{TELEGRAM_BOT_USERNAME}?start=notion_auth_success'
        return responses.RedirectResponse(deep_link_url)

    except Exception as e:
        # Catch errors during DB update or dashboard setup
        logger.error(f"Error during Notion callback processing (DB update or dashboard setup) for telegram_id {telegram_id_int}: {e}", exc_info=True)
        # Try to inform the user, but the redirect might fail if headers already sent
        # Consider sending a Telegram message here if possible before returning error
        return responses.JSONResponse({"error": "Server error during Notion setup"}, status_code=500)

# --- Dummy function placeholder (remove if not needed) ---
# def dummy_function(*args, **kwargs): ...