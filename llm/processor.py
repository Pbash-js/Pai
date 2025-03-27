##File changed to follow google generative ai example
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union, Tuple
from services.timeprocessor import TimeProcessor
from google import genai
from google.genai import types
import logging
from config import GEMINI_API_KEY, LLM_MODEL, LLM_TEMPERATURE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Define function schemas
FUNCTION_SCHEMAS = [
    {
        "name": "setReminder",
        "description": "Sets a reminder for the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Reminder message"},
                "time": {"type": "string", "description": "Time for the reminder (HH:MM format)"},
                "date": {"type": "string", "description": "Date for the reminder (YYYY-MM-DD format)"},
                "repeat": {"type": "string", "description": "Repeat frequency (e.g., 'daily', 'weekly')"}
            },
            "required": ["message", "time", "date"]
        }
    },
    {
        "name": "getReminder",
        "description": "Gets all upcoming reminders for user.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_range": {"type": "string", "description": "Date range for events (e.g., 'next 7 days')"}
            }
        }
    },
    {
        "name": "scheduleEvent",
        "description": "Schedules a calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the event"},
                "date": {"type": "string", "description": "Date of the event (YYYY-MM-DD format)"},
                "time": {"type": "string", "description": "Time of the event (HH:MM format)"},
                "location": {"type": "string", "description": "Location of the event"},
                "participants": {"type": "array", "items": {"type": "string"}, "description": "List of participants"}
            },
            "required": ["title", "date", "time"]
        }
    },
    {
        "name": "getUpcomingEvents",
        "description": "Retrieves upcoming events for the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_range": {"type": "string", "description": "Date range for events (e.g., 'next 7 days')"}
            }
        }
    },
    {
        "name": "cancelEvent",
        "description": "Cancels a scheduled event.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_title": {"type": "string", "description": "Title of the event to cancel"}
            },
            "required": ["event_title"]
        }
    },
    {
        "name": "setRecurringReminder",
        "description": "Sets a recurring reminder.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Reminder message"},
                "interval": {"type": "string", "description": "Time interval (e.g., 'every 2 hours')"},
                "start_time": {"type": "string", "description": "Start time (HH:MM format)"}
            },
            "required": ["message", "interval"]
        }
    }
]

# Convert to Gemini format
FUNCTION_DECLARATIONS = [
    types.FunctionDeclaration(
        name=schema["name"],
        description=schema["description"],
        parameters=schema["parameters"]
    )
    for schema in FUNCTION_SCHEMAS
]

# Create the tool containing function declarations
TOOLS = types.Tool(
    function_declarations=FUNCTION_DECLARATIONS
)
SYSTEM_PROMPT = """
You are a helpful Telegram assistant named Pai. You are created by a cool company named Pragmatech. You help users manage their day to day activities like reminders, events. 
Your responses should be conversational, warm, and concise - avoid long corporate or robotic responses.

When a user wants you to perform a specific task:
1. Understand their intent and extract relevant details from their natural language
2. If details like time or date are missing, make reasonable assumptions based on context.
3. Confirm what you've understood in a friendly, casual way

Instead of saying: 'I have scheduled your event titled 'Meeting with John' for 2023-04-15 at 14:00.'
Say something like: 'Got it! I've added your meeting with John this Saturday at 2pm.'

Instead of saying: 'I have set a reminder for you to 'take medication' on 2023-04-14 at 09:00.'
Say something like: 'I'll remind you to take your medication tomorrow morning at 9am.'

Use conversational language and avoid technical terms. You can use emoji occasionally to appear more friendly.
Keep your responses brief and to the point - usually 1-3 sentences is ideal.

Be helpful by suggesting related actions when appropriate, but avoid overwhelming the user with too many options.

IMPORTANT: 
 - ALWAYS use the function tools unless no function tools matches the query
 - Extract SPECIFIC details from the message
 - FORMAT function call with EXACT required parameters
 - Date format is YYYY-MM-DD
 - Time format is HH:MM
 - If the user does not specify a date, use todays date.
 - If the user does not specify a time, ask the user for the time.
 - If the user asks for reminders, use the getReminder function.
 - If the user asks to schedule an event, use the scheduleEvent function.
 - If the user asks to cancel an event, use the cancelEvent function.
 - If the user asks to set a reminder, use the setReminder function.
 - If the user asks to set a reoccuring reminder, use the setRecurringReminder function.
 - Only use the functions provided. Do not make up functions.

 EXAMPLE:
 User: "Remind me to eat eggs tomorrow at 10 am"
 REQUIRED ACTION: Call setReminder function with:
 - message: "eat eggs"
 - time: "10:00"
 - date: "2025-03-28"

  EXAMPLE:
 User: "Remind me to check the mail in 5 minutes"
 REQUIRED ACTION: Call setReminder function with:
 - message: "Check mail"
 - time: "10:05"
 - date: "2025-03-28"

 EXAMPLE:
 User: "Schedule meeting with bob next week tuesday at 2pm"
 REQUIRED ACTION: Call scheduleEvent function with:
 - title: "meeting with bob"
 - date: "2025-04-01"
 - time: "14:00"

 EXAMPLE:
 User: "What events do I have upcoming?"
 REQUIRED ACTION: Call getUpcomingEvents function.
"""

config = types.GenerateContentConfig(tools=[TOOLS],temperature=LLM_TEMPERATURE,system_instruction=SYSTEM_PROMPT)

class LLMProcessor:
    def __init__(self):
        # Configure the client
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.chat=self.client.chats.create(model=LLM_MODEL,config=config)
        self.time_processor = TimeProcessor()
        self.system_prompt = SYSTEM_PROMPT

    def process_message(self, user_message: str, conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:        
        # Process current message
        logger.info(f"Sending message to LLM: {user_message}")
        response = self.chat.send_message(user_message)
        logger.info(f"gOT RESPONSE FROM LLM: {response}")
        return self._process_response(response)

    # Replace current implementation with:
    def process_multimodal_message(self, user_message: str, image_url: str, conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:
        
        # Process multimodal message
        with open(image_url, "rb") as image_file:
            image_part = types.Part(file_data=types.FileData(
                mime_type="image/jpeg", 
                data=image_file.read()
            ))
        
        response = self.chat.send_message([
            types.Part(text=user_message),
            image_part
        ])
        
        return self._process_response(response)
    
    def _process_response(self, response) -> Dict[str, Any]:
        result = {
            "response_text": response.text,
            "function_calls": []
        }

        try:
            # Explicitly handle function calls
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and candidate.content:
                    content = candidate.content
                    if hasattr(content, 'parts'):
                        for part in content.parts:
                            if hasattr(part, 'function_call') and part.function_call:
                                function_call = part.function_call
                                try:
                                    # Convert the dictionary to a JSON string
                                    args_json = json.dumps(function_call.args) if function_call.args else "{}"
                                    args = json.loads(args_json)
                                    result["function_calls"].append({
                                        "name": function_call.name,
                                        "args": args
                                    })
                                except (json.JSONDecodeError, TypeError) as e:
                                    logger.error(f"Error parsing function call args: {e}")
            return result

        except Exception as e:
            logger.error(f"Error processing response: {e}", exc_info=True)
            return result
    
    def parse_date_range(self, date_range: str) -> int:
        """Convert a date range string to number of days."""
        if "today" in date_range.lower():
            return 0
        elif "tomorrow" in date_range.lower():
            return 1
        if "day" in date_range.lower():
            # Extract number from strings like "next 7 days"
            try:
                return int(''.join(filter(str.isdigit, date_range)))
            except:
                return 7  # Default to a week
        elif "week" in date_range.lower():
            if "this" in date_range.lower():
                return 7
            else:
                # For "next 2 weeks", etc.
                try:
                    num_weeks = int(''.join(filter(str.isdigit, date_range)))
                    return num_weeks * 7
                except:
                    return 7
        elif "month" in date_range.lower():
            return 30
        else:
            return 7  # Default to a week

    def parse_time_interval(self, interval: str) -> Tuple[int, str]:
        """
        Parse a time interval string like "every 2 hours" and return interval in minutes.
        
        Returns:
            Tuple of (interval_minutes, frequency_type)
        """
        interval = interval.lower()
        if "minute" in interval:
            try:
                minutes = int(''.join(filter(str.isdigit, interval)))
                return minutes, "custom"
            except:
                return 60, "custom"  # Default to 60 minutes
        elif "hour" in interval:
            try:
                hours = int(''.join(filter(str.isdigit, interval)))
                return hours * 60, "custom"
            except:
                return 60, "custom"  # Default to 1 hour
        elif "day" in interval or "daily" in interval:
            return 24 * 60, "daily"
        elif "week" in interval or "weekly" in interval:
            return 7 * 24 * 60, "weekly"
        elif "month" in interval or "monthly" in interval:
            return 30 * 24 * 60, "monthly"
        else:
            # Default to daily if we can't parse
            return 24 * 60, "daily"