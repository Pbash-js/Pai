import logging
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from database import get_db, crud
from llm.processor import LLMProcessor
from services.reminder import ReminderService
from services.calendar import CalendarService
from whatsapp.client import WhatsAppClient
from api.schemas import WhatsAppWebhookPayload, UserMessage, BotResponse

logger = logging.getLogger(__name__)

router = APIRouter()
whatsapp_client = WhatsAppClient()
llm_processor = LLMProcessor()


@router.get("/webhook")
async def verify_webhook(request: Request):
    """Handles Facebook Webhook Verification"""
    params = request.query_params  # Dictionary-like object

    hub_mode = params.get("hub.mode")
    hub_challenge = params.get("hub.challenge")
    hub_verify_token = params.get("hub.verify_token")

    VERIFY_TOKEN = "borkar"  # Replace with your actual token

    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return Response(content=hub_challenge, status_code=200)
    return Response(content="Verification failed", status_code=403)

@router.post("/webhook")
async def webhook(payload: WhatsAppWebhookPayload, db: Session = Depends(get_db)):
    """Endpoint for receiving WhatsApp webhook events."""
    try:
        # Verify it's a WhatsApp message
        if payload.object != "whatsapp_business_account":
            return Response(status_code=400)
        
        # Parse the incoming message
        message_data = whatsapp_client.parse_incoming_message(payload.dict())
        if not message_data:
            # Not a text message or couldn't parse
            return Response(status_code=200)
        
        # Process user message
        sender_id = message_data["sender_id"]
        message_text = message_data["message_text"]
        
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
        
        # If we have function results, append them to the response
        if results:
            for result in results:
                if result.get("status") == "success":
                    continue  # LLM already included success message
                elif result.get("status") == "error":
                    response_text += f"\n\n{result.get('message', 'An error occurred.')}"
        
        # Add bot response to history
        crud.update_session_history(
            db, 
            user.id, 
            {"role": "assistant", "content": response_text}
        )
        
        # Send response back to user
        whatsapp_client.send_message(sender_id, response_text)
        
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