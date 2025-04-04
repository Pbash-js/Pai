# llm/processor.py

import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union, Tuple
# << -- Remove TimeProcessor import if Notion handles time/date properties -->>
# from services.timeprocessor import TimeProcessor
import aiofiles
import asyncio
# <<-- Use google.generativeai instead of google.genai -->>
import google.genai as genai
from google.genai import types
# <<-- End google.generativeai import -->>
import logging
# <<-- Adjust config import path if necessary -->>
from config import GEMINI_API_KEY, LLM_MODEL, LLM_TEMPERATURE
# <<-- End config import adjustment -->>
import re

# llm/processor.py
import logging
from config import GEMINI_API_KEY, LLM_MODEL, LLM_TEMPERATURE
import re # Import re for parse_date_range fallback

logger = logging.getLogger(__name__)

# --- Define ALL Function Schemas ---
FUNCTION_SCHEMAS = [
    # --- Existing Schemas (Keep Them - ensure they are correct) ---
    {
        "name": "setReminder",
        "description": "Sets a reminder using the bot's internal reminder system.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Reminder message"},
                "time": {"type": "string", "description": "Time for the reminder (HH:MM format)"},
                "date": {"type": "string", "description": "Date for the reminder (YYYY-MM-DD format)"},
                "repeat": {"type": "string", "description": "Repeat frequency (e.g., 'daily', 'weekly', 'none')"}
            },
            "required": ["message", "time", "date"]
        }
    },
    {
        "name": "getReminder",
        "description": "Gets upcoming reminders from the bot's internal system.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_range": {"type": "string", "description": "Date range (e.g., 'today', 'next 3 days', 'this week')"}
            }
        }
    },
    {
        "name": "scheduleEvent",
        "description": "Schedules a calendar event using the bot's internal calendar system.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the event"},
                "date": {"type": "string", "description": "Date (YYYY-MM-DD)"},
                "time": {"type": "string", "description": "Time (HH:MM)"},
                "location": {"type": "string", "description": "Location (optional)"},
                "participants": {"type": "array", "items": {"type": "string"}, "description": "List of participant names (optional)"}
            },
            "required": ["title", "date", "time"]
        }
    },
    {
        "name": "getUpcomingEvents",
        "description": "Retrieves upcoming events from the bot's internal calendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_range": {"type": "string", "description": "Date range (e.g., 'today', 'next 7 days')"}
            }
        }
    },
    {
        "name": "cancelEvent",
        "description": "Cancels a scheduled event from the bot's internal calendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_title": {"type": "string", "description": "Title of the event to cancel"}
            },
            "required": ["event_title"]
        }
    },
    # --- Notion Functions ---
    {
        "name": "createNotionNote",
        "description": "Creates a new note page in Notion under a specified parent page.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The title for the new Notion note page."},
                "content": {"type": "string", "description": "The main text content for the note."},
                "parent_page_title": {"type": "string", "description": "The exact title of the existing Notion page where the new note should be created inside."}
            },
            "required": ["title", "content", "parent_page_title"]
        }
    },
    {
        "name": "createNotionTable",
        "description": "Creates a new table (database) in Notion inside a specified parent page. Define columns using the properties parameter.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The title for the new Notion table (database)."},
                "parent_page_title": {"type": "string", "description": "The exact title of the existing Notion page where the new table should be created inside."},
                # << --- START CORRECTION --- >>
                "properties_schema": {
                    "type": "object",
                    "description": """Defines the columns (properties) for the Notion table. Keys are the desired column names. Values MUST be objects matching the Notion API property schema for the desired type.
Examples of VALID VALUES for this object:
- Text column 'Item': {"Item": {"text": {}}}
- Number column 'Amount': {"Amount": {"number": {"format": "dollar"}}}
- Date column 'Due Date': {"Due Date": {"date": {}}}
- Select column 'Status': {"Status": {"select": {"options": [{"name": "To Do"}, {"name": "In Progress"}, {"name": "Done"}]}}}
- Multi-select column 'Tags': {"Tags": {"multi_select": {"options": [{"name": "Urgent"}, {"name": "Work"}]}}}
- Checkbox column 'Completed': {"Completed": {"checkbox": {}}}
NOTE: Do NOT include a 'Title' property definition here; the main 'title' parameter handles the table's primary title column automatically."""
                    # REMOVED the invalid 'additionalProperties' structure. The description now guides the LLM.
                }
                # << --- END CORRECTION --- >>
            },
            "required": ["title", "parent_page_title", "properties_schema"]
        }
    },
    {
        "name": "addNotionTableRow",
        "description": "Adds a new row (page) to an existing Notion table (database).",
        "parameters": {
            "type": "object",
            "properties": {
                "database_title": {"type": "string", "description": "The exact title of the Notion table (database) to add the row to."},
                "entry_data": {
                    "type": "object",
                    "description": "The data for the new row. Keys should be the exact column names (properties) of the table. Values are the data to insert for that column.",
                    # Simple type for values - the Notion Service will format them
                    #"additionalProperties": {"type": "string"}
                 }
            },
            "required": ["database_title", "entry_data"]
        }
    }
]

# --- Generate Tool Configuration ---
try:
    FUNCTION_DECLARATIONS = [
        types.FunctionDeclaration(
            name=schema["name"],
            description=schema["description"],
            # Use **schema['parameters'] which works if the dict matches Schema structure
            parameters=types.Schema(**schema['parameters'])
        )
        for schema in FUNCTION_SCHEMAS
    ]

    TOOLS = types.Tool(function_declarations=FUNCTION_DECLARATIONS)
    logger.info("Successfully created Gemini Tool configuration.")
except Exception as e:
    # Log the specific schema causing the error if possible
    problematic_schema_name = "Unknown"
    for schema in FUNCTION_SCHEMAS:
        try:
            types.Schema(**schema['parameters'])
        except Exception as schema_e:
            problematic_schema_name = schema.get("name", "Unknown")
            logger.error(f"Validation failed for schema: {problematic_schema_name}")
            logger.error(f"Schema details: {schema['parameters']}")
            logger.error(f"Specific validation error: {schema_e}")
            break # Stop after first error

    logger.error(f"Error creating Gemini Tool configuration (likely in schema '{problematic_schema_name}'): {e}", exc_info=True)
    TOOLS = None

# --- System Prompt ---
def get_dynamic_system_prompt():
    # ... (Your existing prompt generation logic) ...
    # Make sure the prompt explains the Notion column schema format clearly.
    current_date = datetime.now().strftime('%Y-%m-%d')
    current_time = datetime.now().strftime('%H:%M')
    # Include the examples from the schema description in the main prompt if helpful
    return f"""
You are a helpful Telegram assistant named Pai, created by Pragmatech.
You help users manage reminders, events, and notes, leveraging Notion for notes and tables.

CONTEXT:
- Today's date: {current_date}
- Current time: {current_time}

INSTRUCTIONS:
1.  **Understand Intent:** Determine if the user wants a simple reminder/event (use internal functions like `setReminder`, `scheduleEvent`) OR if they want to save a note, create a list/table, or track something (use Notion functions like `createNotionNote`, `createNotionTable`, `addNotionTableRow`).
2.  **Extract Details:** Get specific information (what, when, where, who, column names, data for tables, parent page for Notion items).
3.  **Assume Reasonably:** If date/time is missing for internal reminders/events, use today or ask. For Notion, the structure or parent location is crucial - ask if unclear.
4.  **Confirm Casually:** Respond conversationally before executing. Use emoji occasionally. Keep responses brief (1-3 sentences).
5.  **Function Usage:**
    *   **ALWAYS** try to use a function tool if the request matches a defined capability.
    *   Format function calls with EXACT required parameters (Dates: YYYY-MM-DD, Times: HH:MM).
    *   For Notion functions (`createNotionNote`, `createNotionTable`, `addNotionTableRow`), you MUST determine the `parent_page_title` (for notes/tables) or `database_title` (for table rows). Ask the user if you're unsure where to put it.
    *   For `createNotionTable`, the `properties_schema` parameter MUST be an object where keys are column names and values follow the Notion API structure (e.g., `{{"Status": {{"select": {{"options": [{{"name": "To Do"}}]}}}}, "Due Date": {{"date": {{}}}}}}`). Do NOT define the 'Title' column here.
    *   For `addNotionTableRow`, ensure `entry_data` keys match the table's column names.
    *   Only use the functions provided. Include user-friendly text alongside function calls.

EXAMPLES:
User: "Remind me to buy milk tomorrow at 8am"
Model: "Sure! I'll remind you to buy milk tomorrow at 8 AM. 🥛"
Function call: `setReminder`(...)

User: "Schedule lunch with Sarah next Wed at 1pm at The Cafe"
Model: "Got it! Lunch with Sarah scheduled for next Wednesday at 1 PM at The Cafe. 📅"
Function call: `scheduleEvent`(...)

User: "Save this idea as a note in my 'Project X Ideas' page: AI feedback analysis."
Model: "Okay, saving that idea to your 'Project X Ideas' page in Notion!"
Function call: `createNotionNote`(...)

User: "Create a table on 'Finances' page to track expenses: Date, Item, Category (Select), Amount (Number)"
Model: "Sure, creating Expenses table on 'Finances' page in Notion with columns: Date, Item, Category, Amount."
Function call: `createNotionTable` (title="Expenses", parent_page_title="Finances", properties_schema={{"Date": {{"date": {{}}}}, "Item": {{"rich_text": {{}}}}, "Category": {{"select": {{"options": []}}}}, "Amount": {{"number": {{"format": "dollar"}}}}}}) # LLM provides schema

User: "Add to 'Groceries' table: Item=Apples, Quantity=5"
Model: "Okay, adding Apples (Quantity: 5) to your Groceries table in Notion."
Function call: `addNotionTableRow` (database_title="Groceries", entry_data={{"Item": "Apples", "Quantity": "5"}})
"""


class LLMProcessor:
    # ... (keep __init__ method as before, ensuring TOOLS is checked) ...
    def __init__(self):
        # Configure the client
        dynamic_system_prompt = get_dynamic_system_prompt()
        config = types.GenerateContentConfig(tools=[TOOLS], temperature=LLM_TEMPERATURE, system_instruction=dynamic_system_prompt)
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Store the model and config for creating chats in async methods
        self.model = LLM_MODEL
        self.config = config
        
        # Create a semaphore to limit concurrent API calls if needed
        self.semaphore = asyncio.Semaphore(5)  # Adjust the value based on API rate limits
    # ... (keep _convert_history method) ...
    def _convert_history(self, history: List[Dict[str, str]]) -> List[types.Content]:
        gemini_history = []
        current_content = None
        for entry in history:
            role = entry.get("role")
            content_text = entry.get("content", "")

            if role == "user":
                # If previous message was also user, append (shouldn't happen with good history management)
                # Otherwise, start new user content
                current_content = types.Content(parts=[types.Part(text=content_text)], role="user")
                gemini_history.append(current_content)
            elif role == "assistant":
                # Start new model content
                # TODO: Handle potential function calls stored in history correctly
                current_content = types.Content(parts=[types.Part(text=content_text)], role="model")
                gemini_history.append(current_content)
            # Ignore other roles for now
        return gemini_history


    # ... (keep process_message, process_multimodal_message - ensure they use self.model.start_chat) ...
    async def process_message(self, user_message: str, conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:
        logger.info(f"Processing message for LLM: {user_message}")
        async with self.semaphore:
            try:
                # Start chat session with history
                chat = self.client.chats.create(model=self.model, config=self.config)
                response = await asyncio.to_thread(chat.send_message, user_message)

                logger.debug(f"Raw LLM response: {response}")
                return self._process_response(response)
            except Exception as e:
                logger.error(f"Error during LLM communication: {e}", exc_info=True)
                return {"response_text": "Sorry, I encountered an error trying to understand that.", "function_calls": []}

    async def process_multimodal_message(self, user_message: str, image_path: str, conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:
        logger.info(f"Processing multimodal message. Text: {user_message}, Image: {image_path}")
        async with self.semaphore:
            try:
                async with aiofiles.open(image_path, "rb") as image_file:
                    image_data = await image_file.read()
                mime_type = "image/jpeg" # Or determine dynamically
                image_part = types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_data))
                parts = [types.Part(text=user_message), image_part]

                chat = self.client.chats.create(model=self.model, config=self.config)
                response = await asyncio.to_thread(chat.send_message, user_message)


                logger.debug(f"Raw LLM multimodal response: {response}")
                return self._process_response(response)
            except FileNotFoundError:
                 logger.error(f"Image file not found: {image_path}")
                 return {"response_text": "Sorry, I couldn't find the image file.", "function_calls": []}
            except Exception as e:
                 logger.error(f"Error during LLM multimodal communication: {e}", exc_info=True)
                 return {"response_text": "Sorry, I encountered an error processing the image.", "function_calls": []}

    # ... (keep process_function_result - NOTE: Still needs robust chat state handling) ...
    async def process_function_result(
        self,
        function_name: str,
        function_response_data: Dict[str, Any],
        # Option 1: Use Any (Safest if internal type changes)
        chat_session: Optional[Any] = None
        # Option 2: Remove type hint temporarily if preferred
        # chat_session = None
    ) -> Dict[str, Any]:
        """Sends function execution result back to the LLM.
           Ideally, pass the chat_session object obtained from model.start_chat().
        """
        logger.info(f"Sending function result for '{function_name}' back to LLM.")
        if not chat_session:
            logger.warning("No chat session provided to process_function_result. LLM context might be lost.")
            # Fallback: Start a new chat (less ideal as context is lost)
            # Note: This fallback might still lead to suboptimal conversations
            # as the LLM won't remember the function *call* that led to this *response*.
            chat_session = self.model.start_chat(history=[]) # Create a new session object

        async with self.semaphore:
            try:
                function_response_part = types.Part(
                    function_response=types.FunctionResponse(
                        name=function_name,
                        response=function_response_data # Must be serializable dict
                    )
                )
                # Send the result using the provided (or newly created) chat session object
                response = await chat_session.send_message_async(function_response_part)

                logger.debug(f"Raw LLM response after function result: {response}")
                return self._process_response(response) # Process the response
            except Exception as e:
                logger.error(f"Error sending function result to LLM: {e}", exc_info=True)
                return {"response_text": "Sorry, I encountered an error processing the previous action's result.", "function_calls": []}

    # ... (keep _process_response method - already corrected to be synchronous) ...
    def _process_response(self, response: types.GenerateContentResponse) -> Dict[str, Any]:
        response_text = ""
        function_calls = []
        try:
            response_text = response.text # Use the convenient .text attribute
            parts = response.candidates[0].content.parts

            for part in parts if len(parts) > 0 else []:
                if part.function_call:
                    fc = part.function_call
                    # Convert proto Map to dict
                    args_dict = {k: v for k, v in fc.args.items()}
                    function_calls.append({
                        "name": fc.name,
                        "args": args_dict
                    })
                    logger.info(f"LLM requested function call: {fc.name} with args: {args_dict}")
        except (AttributeError, ValueError, TypeError) as e:
            logger.error(f"Error parsing LLM response content: {e}", exc_info=True)
            try:
                response_text = response.text
            except Exception:
                 response_text = "Sorry, I had trouble processing the response."
        if not response_text and function_calls:
            response_text = f"Okay, planning to run: {function_calls[0]['name']}."

        return {
            "response_text": response_text,
            "function_calls": function_calls
        }


    # ... (keep parse_date_range if needed elsewhere, maybe move to utils) ...
    def parse_date_range(self, date_range: str) -> int:
        """Convert a date range string to number of days. (Simplified)"""
        # ... (implementation as before) ...
        date_range = date_range.lower() if date_range else "7 days" # Default
        if "today" in date_range: return 0
        if "tomorrow" in date_range: return 1
        if "week" in date_range: return 7
        if "month" in date_range: return 30
        try:
            match = re.search(r'(\d+)\s+day', date_range)
            if match: return int(match.group(1))
        except (ValueError, TypeError):
            pass
        return 7 # Default