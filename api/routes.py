import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from database import get_db, crud
from llm.processor import LLMProcessor
from services.reminder import ReminderService
from services.calendar import CalendarService
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from api.schemas import TelegramWebhookPayload
import os

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)

llm_processor = LLMProcessor()

@router.post("/webhook")
async def webhook(payload: TelegramWebhookPayload, db: Session = Depends(get_db)):
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
        user = crud.get_or_create_user(db, sender_id)

        # Get conversation history
        conversation_history = crud.get_session_history(db, user.id)

        # Add user message to history
        crud.update_session_history(
            db,
            user.id,
            {"role": "user", "content": message_text}
        )

        # Process message with LLM
        llm_response = llm_processor.process_message(message_text, conversation_history)

        # Execute any function calls
        results = []
        for func_call in llm_response.get("function_calls", []):
            result = execute_function_call(db, user.id, func_call)
            results.append(result)

        # Generate response text
        response_text = llm_response["response_text"]

        # If we have function results, append them
        if results:
            for result in results:
                if result.get("status") == "success":
                    continue
                elif result.get("status") == "error":
                    response_text += f"\n\n{result.get('message', 'An error occurred.')}"

        # Add bot response to history
        crud.update_session_history(
            db,
            user.id,
            {"role": "assistant", "content": response_text}
        )

        # Send response back to user
        await telegram_bot.send_message(
            chat_id=sender_id,
            text=escape_markdown(response_text, version=2),  # Escape markdown
            parse_mode=ParseMode.MARKDOWN_V2
        )

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return Response(status_code=500)


def execute_function_call(db: Session, user_id: int, func_call: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a function call from the LLM."""
    function_name = func_call["name"]
    args = func_call["args"]

    reminder_service = ReminderService(db)
    calendar_service = CalendarService(db)

    try:
        if function_name == "setReminder":
            return reminder_service.set_reminder(user_id, args)

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
