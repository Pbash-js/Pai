import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union
from services.timeprocessor import TimeProcessor

import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration
from typing import Tuple

from config import GEMINI_API_KEY, LLM_MODEL, LLM_TEMPERATURE

# Configure the Gemini API
genai.configure(api_key=GEMINI_API_KEY)


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
    FunctionDeclaration(
        name=schema["name"],
        description=schema["description"],
        parameters=schema["parameters"]
    )
    for schema in FUNCTION_SCHEMAS
]

SYSTEM_PROMPT = SYSTEM_PROMPT = """
You are a helpful WhatsApp assistant that helps users manage their reminders and calendar events. 
Your responses should be conversational, warm, and concise - avoid long corporate or robotic responses.

When a user wants to set a reminder or schedule an event:
1. Understand their intent and extract relevant details from their natural language
2. If details like time or date are missing, make reasonable assumptions based on context
3. Confirm what you've understood in a friendly, casual way

Instead of saying: 'I have scheduled your event titled 'Meeting with John' for 2023-04-15 at 14:00.'
Say something like: 'Got it! I've added your meeting with John this Saturday at 2pm.'

Instead of saying: 'I have set a reminder for you to 'take medication' on 2023-04-14 at 09:00.'
Say something like: 'I'll remind you to take your medication tomorrow morning at 9am.'

Use conversational language and avoid technical terms. You can use emoji occasionally to appear more friendly.
Keep your responses brief and to the point - usually 1-3 sentences is ideal.

Be helpful by suggesting related actions when appropriate, but avoid overwhelming the user with too many options.
"""


class LLMProcessor:
    def __init__(self):
        self.model = genai.GenerativeModel(
            model_name=LLM_MODEL,
            generation_config={"temperature": LLM_TEMPERATURE}
        )
        self.time_processor = TimeProcessor()
        self.system_prompt = SYSTEM_PROMPT
    
    def process_message(self, user_message: str, conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Process a user message and return the bot's response along with any function calls.
        
        Args:
            user_message: The user's message
            conversation_history: List of previous messages in the conversation
            
        Returns:
            Dict containing response text and function calls if any
        """
        # Format conversation history for Gemini
        formatted_history = []
        for msg in conversation_history:
            role = "user" if msg["role"] == "user" else "model"
            formatted_history.append({"role": role, "parts": [{"text": msg["content"]}]})
        
        # Create chat session
        chat = self.model.start_chat(history=formatted_history)
        
        # Send user message with function declarations
        response = chat.send_message(
            user_message,
            tools=[{"function_declarations": FUNCTION_DECLARATIONS}]
        )
        
        # Process response
        result = {
            "response_text": response.text,
            "function_calls": []
        }
        
        # Check if there are function calls in the response
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                content = candidate.content
                if hasattr(content, 'parts') and content.parts:
                    for part in content.parts:
                        if hasattr(part, 'function_call') and part.function_call:
                            function_call = part.function_call
                            result["function_calls"].append({
                                "name": function_call.name,
                                "args": json.loads(function_call.args)
                            })
        
        return result
    
    def parse_date_range(self, date_range: str) -> int:
        """Convert a date range string to number of days."""
        if "day" in date_range.lower():
            if "today" in date_range.lower():
                return 0
            elif "tomorrow" in date_range.lower():
                return 1
            else:
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