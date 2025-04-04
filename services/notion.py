# services/notion.py

import logging
import asyncio
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from notion_client import AsyncClient, APIResponseError, APIErrorCode

from database import crud # Import your crud functions

logger = logging.getLogger(__name__)

# --- Helper Functions for Notion Blocks/Properties ---

REMINDERS_DB_SCHEMA = {
    "Date/Time": {"date": {}},
    "Status": {"select": {"options": [{"name": "Pending"}, {"name": "Done"}, {"name": "Snoozed"}]}},
    "Repeat": {"rich_text": {}}, # Simple text for now
    "Notes": {"rich_text": {}}
}

NOTES_DB_SCHEMA = {
    "Created": {"created_time": {}},
    "Tags": {"multi_select": {}},
    "Content Snippet": {"rich_text": {}} # Title property is handled by Notion page title
}

EVENTS_DB_SCHEMA = {
    "Date/Time": {"date": {}},
    "Location": {"rich_text": {}},
    "Participants": {"rich_text": {}}, # Simple text for participant names
    "Status": {"select": {"options": [{"name": "Scheduled"}, {"name": "Cancelled"}, {"name": "Completed"}]}},
    "Description": {"rich_text": {}}
}


def text_block(content: str) -> Dict[str, Any]:
    """Creates a Notion paragraph block with simple text."""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": content}}]
        }
    }

def title_prop(content: str) -> Dict[str, Any]:
    """Creates a Notion title property value."""
    return {"title": [{"type": "text", "text": {"content": content}}]}

def rich_text_prop(content: str) -> Dict[str, Any]:
    """Creates a Notion rich text property value."""
    return {"rich_text": [{"type": "text", "text": {"content": content}}]}

def date_prop(start: str, end: Optional[str] = None, time_zone: Optional[str] = None) -> Dict[str, Any]:
    """Creates a Notion date property value (YYYY-MM-DD or ISO 8601)."""
    date_data = {"start": start}
    if end:
        date_data["end"] = end
    if time_zone:
        date_data["time_zone"] = time_zone
    return {"date": date_data}

# Add more helpers for other property types (select, multi_select, number, etc.) as needed

# --- Notion Service Class ---

class NotionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_client(self, user_id: int) -> Optional[AsyncClient]:
        user = await crud.get_user_by_id(self.db, user_id=user_id) # Get user by internal ID
        if user and user.notion_access_token:
            return AsyncClient(auth=user.notion_access_token)
        logger.warning(f"No Notion access token found for user_id: {user_id}")
        return None
    

    async def find_page_by_title(self, user_id: int, title: str, search_limit=10) -> Optional[str]:
        """Searches for a page by title within accessible pages."""
        client = await self.get_client(user_id)
        if not client:
            return None
        try:
            logger.debug(f"Searching for page with title: '{title}' for user {user_id}")
            response = await client.search(
                query=title,
                filter={"property": "object", "value": "page"},
                sort={"direction": "ascending", "timestamp": "last_edited_time"},
                page_size=search_limit
            )
            for page in response.get("results", []):
                page_title_obj = page.get("properties", {}).get("title", {}).get("title", [])
                if page_title_obj and page_title_obj[0].get("plain_text") == title:
                    logger.info(f"Found existing page '{title}' with ID: {page['id']}")
                    return page["id"]
            logger.info(f"Page with title '{title}' not found in search results.")
            return None
        except APIResponseError as e:
            self._handle_error(e, f"find page by title '{title}'")
            return None
        except Exception as e:
            logger.error(f"Unexpected error finding page by title '{title}' for user {user_id}: {e}", exc_info=True)
            return None

    async def _create_page_internal(self, client: AsyncClient, title: str, parent_info: dict, properties: Optional[dict] = None, children: Optional[list] = None) -> Optional[str]:
        """Internal helper to create a page (can be top-level or nested)."""
        try:
            # --- START FIX: Conditionally build page_data ---
            page_data = {
                # "parent": parent_info, # OLD: Always included parent
                "properties": {
                    "title": {"title": [{"type": "text", "text": {"content": title}}]}
                }
            }
            # ONLY include parent if parent_info is NOT empty
            if parent_info:
                page_data["parent"] = parent_info
            else:
                logger.info(f"Creating '{title}' as a top-level page (omitting parent key).")

            # --- END FIX ---

            if properties:
                page_data["properties"].update(properties)
            if children:
                 page_data["children"] = children

            logger.info(f"Creating Notion page titled '{title}' with data: {page_data}") # Log the actual data being sent
            created_page = await client.pages.create(**page_data)
            page_id = created_page.get("id")
            logger.info(f"Successfully created page '{title}' with ID: {page_id}")
            return page_id
        except APIResponseError as e:
             # Use the modified _handle_error below
             self._handle_error(e, f"create page '{title}'")
             return None
        except Exception as e:
            logger.error(f"Unexpected error creating page '{title}': {e}", exc_info=True)
            return None

    # ... (keep create_top_level_page - it correctly passes parent_info={}) ...
    async def create_top_level_page(self, user_id: int, title: str) -> Optional[str]:
        """Creates a page at the root level of the user's accessible pages."""
        client = await self.get_client(user_id)
        if not client:
            return None
        # Pass empty parent_info; _create_page_internal will now handle omitting the key
        return await self._create_page_internal(client, title, parent_info={})

    # ... (keep _create_database_internal, setup_initial_dashboard etc.) ...

    # --- FIX _handle_error ---
    def _handle_error(self, error: APIResponseError, context: str):
        """Handles and logs Notion API errors."""
        code = error.code # code attribute should exist
        # FIX: Use str(error) to get the printable error message
        message = str(error)
        logger.error(f"Notion API Error (Code: {code}) during '{context}': {message}")

        # Keep specific code checks if useful
        if code == APIErrorCode.ObjectNotFound:
            logger.warning(f"Object not found during '{context}'.")
        elif code == APIErrorCode.Unauthorized:
            logger.error(f"Unauthorized access during '{context}'. Token might be invalid or expired.")
            # Consider notifying the user or triggering re-auth
        elif code == APIErrorCode.RateLimited:
            logger.warning(f"Rate limit hit during '{context}'. Consider backoff.")
        elif code == APIErrorCode.ValidationError:
             logger.error(f"Validation Error during '{context}'. Check payload structure. Details: {message}")
        # Add more specific error handling as needed

    async def _create_database_internal(self, client: AsyncClient, title: str, parent_page_id: str, properties_schema: dict) -> Optional[str]:
         """Internal helper to create a database."""
         try:
             db_data = {
                 "parent": {"type": "page_id", "page_id": parent_page_id},
                 "title": [{"type": "text", "text": {"content": title}}],
                 "properties": properties_schema # Pass the schema directly
             }
             # Add the mandatory 'Title' property if not implicitly handled (depends on API version/client)
             if "title" not in properties_schema and "Title" not in properties_schema:
                 logger.debug(f"Adding default 'Title' property to schema for DB '{title}'")
                 db_data["properties"]["Title"] = {"title": {}} # Default title property

             logger.info(f"Creating Notion database titled '{title}' under page ID: {parent_page_id}")
             created_db = await client.databases.create(**db_data)
             db_id = created_db.get("id")
             logger.info(f"Successfully created database '{title}' with ID: {db_id}")
             return db_id
         except APIResponseError as e:
             # Handle specific error for database already exists? Might be tricky.
             self._handle_error(e, f"create database '{title}'")
             return None
         except Exception as e:
            logger.error(f"Unexpected error creating database '{title}': {e}", exc_info=True)
            return None


    async def setup_initial_dashboard(self, user_id: int) -> bool:
        """
        Sets up the Notion dashboard using the MANDATORY duplicated template page as the parent.
        Creates standard databases if they don't exist.
        """
        user = await crud.get_user(self.db, user_id=user_id)
        if not user:
            logger.error(f"Cannot setup Notion dashboard: User {user_id} not found.")
            return False

        # --- Check setup_complete flag FIRST ---
        # Optional: Also check if duplicated_template_id exists, though it should if we got here
        if user.notion_setup_complete and user.notion_dashboard_page_id:
            logger.info(f"Notion dashboard setup already complete for user {user_id}.")
            return True

        # --- Use duplicated_template_id DIRECTLY as the parent ---
        parent_page_id = user.duplicated_template_id
        if not parent_page_id:
            logger.error(f"Cannot setup Notion dashboard: duplicated_template_id is missing for user {user_id}. Auth flow error?")
            # Mark incomplete if somehow it's missing here
            await crud.update_user_notion_dashboard_info(
                self.db, user_id=user_id, dashboard_id=None, reminders_db_id=None,
                notes_db_id=None, events_db_id=None, setup_complete=False
            )
            return False
        # --- End Parent Determination ---

        client = await self.get_client(user_id)
        if not client:
            logger.error(f"Cannot setup Notion dashboard: No Notion client for user {user_id}.")
            return False

        logger.info(f"Starting initial Notion dashboard setup for user {user_id} using parent (duplicated template): {parent_page_id}")

        dashboard_page_id = None # This will be the SAME as parent_page_id now
        reminders_db_id = None
        notes_db_id = None
        events_db_id = None
        setup_succeeded = False

        try:
            # --- 1. Dashboard Page IS the Parent Page ---
            # We don't need to create a *new* dashboard page, the duplicated template IS the dashboard.
            dashboard_page_id = parent_page_id
            logger.info(f"Using duplicated template page {dashboard_page_id} as the dashboard.")
            # Optional: Rename the duplicated template page?
            # try:
            #    await client.pages.update(page_id=dashboard_page_id, properties={"title": {"title": [{"type": "text", "text": {"content": "MyPai Dashboard"}}]}})
            #    logger.info(f"Renamed duplicated template page to 'MyPai Dashboard'.")
            # except Exception as rename_err:
            #    logger.warning(f"Could not rename duplicated template page: {rename_err}")

            # --- 2. Create Databases within the Dashboard (Template) Page ---
            # Fetch user again to check existing DB IDs
            user = await crud.get_user(self.db, user_id=user_id)

            # Create Reminders DB (if needed)
            if not user.notion_reminders_db_id:
                 reminders_title = "Pai Reminders"
                 logger.info(f"Attempting to create '{reminders_title}' database in dashboard {dashboard_page_id}...")
                 reminders_db_id = await self._create_database_internal(
                     client, reminders_title, dashboard_page_id, REMINDERS_DB_SCHEMA
                 )
                 if not reminders_db_id: logger.warning(f"Failed to create '{reminders_title}' database.")
            else:
                 reminders_db_id = user.notion_reminders_db_id
                 logger.info(f"Reminders DB ID already exists: {reminders_db_id}")

            # Create Notes DB (if needed)
            if not user.notion_notes_db_id:
                 notes_title = "Pai Notes"
                 logger.info(f"Attempting to create '{notes_title}' database in dashboard {dashboard_page_id}...")
                 notes_db_id = await self._create_database_internal(
                     client, notes_title, dashboard_page_id, NOTES_DB_SCHEMA
                 )
                 if not notes_db_id: logger.warning(f"Failed to create '{notes_title}' database.")
            else:
                 notes_db_id = user.notion_notes_db_id
                 logger.info(f"Notes DB ID already exists: {notes_db_id}")

            # Create Events DB (if needed)
            if not user.notion_events_db_id:
                 events_title = "Pai Events"
                 logger.info(f"Attempting to create '{events_title}' database in dashboard {dashboard_page_id}...")
                 events_db_id = await self._create_database_internal(
                     client, events_title, dashboard_page_id, EVENTS_DB_SCHEMA
                 )
                 if not events_db_id: logger.warning(f"Failed to create '{events_title}' database.")
            else:
                 events_db_id = user.notion_events_db_id
                 logger.info(f"Events DB ID already exists: {events_db_id}")

            # --- 3. Update User Record in DB ---
            setup_succeeded = bool(dashboard_page_id) # Should always be true if we got here
            await crud.update_user_notion_dashboard_info(
                self.db,
                user_id=user_id,
                dashboard_id=dashboard_page_id, # Store the template ID as the dashboard ID
                reminders_db_id=reminders_db_id,
                notes_db_id=notes_db_id,
                events_db_id=events_db_id,
                setup_complete=setup_succeeded
            )
            logger.info(f"Notion dashboard setup finished for user {user_id}. Success: {setup_succeeded}. Dashboard Page ID: {dashboard_page_id}")
            return setup_succeeded

        except APIResponseError as e:
             # Handle case where the duplicated template ID is somehow invalid now
             if e.code == APIErrorCode.ObjectNotFound:
                  logger.error(f"Duplicated template page {parent_page_id} not found or accessible for user {user_id}. Permissions changed?")
                  # Mark setup incomplete
                  await crud.update_user_notion_dashboard_info(
                       self.db, user_id=user_id, dashboard_id=None, reminders_db_id=None,
                       notes_db_id=None, events_db_id=None, setup_complete=False
                   )
                  return False
             else:
                  # Handle other API errors during DB creation
                  logger.error(f"API error during Notion dashboard setup for user {user_id}: {e}", exc_info=True)
                  # Store partial progress? Mark incomplete.
                  await crud.update_user_notion_dashboard_info(
                       self.db, user_id=user_id, dashboard_id=dashboard_page_id,
                       reminders_db_id=reminders_db_id, notes_db_id=notes_db_id,
                       events_db_id=events_db_id, setup_complete=False
                   )
                  return False
        except Exception as e:
            logger.error(f"Unexpected error during Notion dashboard setup for user {user_id}: {e}", exc_info=True)
            await crud.update_user_notion_dashboard_info(
                 self.db, user_id=user_id, dashboard_id=dashboard_page_id,
                 reminders_db_id=reminders_db_id, notes_db_id=notes_db_id,
                 events_db_id=events_db_id, setup_complete=False
             )
            return False
    # Add helper for error handling if not already present
    def _handle_error(self, error: APIResponseError, context: str):
        code = error.code
        logger.error(error.body)
        message = error.body if error.body else "No message provided"
        logger.error(f"Notion API Error ({code}) during '{context}': {message}")
        if code == APIErrorCode.ObjectNotFound:
            logger.warning(f"Object not found during '{context}'.")
        elif code == APIErrorCode.Unauthorized:
            logger.error(f"Unauthorized access during '{context}'. Token might be invalid or expired.")
            # Consider notifying the user or triggering re-auth
        elif code == APIErrorCode.RateLimited:
            logger.warning(f"Rate limit hit during '{context}'. Consider backoff.")
        # Add more specific error handling as needed


    async def create_note_page(self, user_id: int, title: str, content: str, parent_page_id: Optional[str] = None) -> Dict[str, Any]:
        """Creates a simple note page in Notion."""
        client = await self._get_client(user_id)
        if not client:
            return {"status": "error", "message": "Notion account not linked or token missing."}

        # --- Determine Parent ---
        # Strategy:
        # 1. If parent_page_id provided, use it.
        # 2. (Optional) Search for a default "Notes" page/database if no parent_id.
        # 3. Fallback: Create in workspace root (might require specific permissions).
        # For simplicity, let's require parent_page_id for now or implement search later.

        if not parent_page_id:
            # You could try searching for a default page/DB here
            # default_notes_page_id = await self.find_page_by_title(user_id, "My Bot Notes")
            # if default_notes_page_id:
            #    parent_page_id = default_notes_page_id
            # else:
                 #return {"status": "error", "message": "Please specify where to save the note (e.g., 'save note to My Project page')."}
            # Let's assume parent_page_id MUST be provided for now by the LLM or user context
            return {"status": "error", "message": "No parent page specified for the note."}


        try:
            logger.info(f"Creating Notion note '{title}' for user {user_id} under parent {parent_page_id}")
            page_data = {
                "parent": {"page_id": parent_page_id},
                "properties": {
                    "title": title_prop(title)
                    # Add other properties like 'Created Date' if desired
                },
                "children": [text_block(content)] # Add content as a paragraph block
            }
            response = await client.pages.create(**page_data)
            page_url = response.get("url", "")
            logger.info(f"Successfully created Notion note for user {user_id}. URL: {page_url}")
            return {"status": "success", "message": f"Note '{title}' created in Notion.", "page_url": page_url}

        except APIResponseError as e:
            logger.error(f"Notion API error creating note for user {user_id}: {e}")
            if e.code == APIErrorCode.ObjectNotFound:
                 return {"status": "error", "message": f"Could not find the parent page/database ({parent_page_id}) in Notion. Does it exist?"}
            elif e.code == APIErrorCode.Unauthorized:
                 return {"status": "error", "message": "I don't have permission to create pages in that part of your Notion. Please check the integration permissions."}
            else:
                 return {"status": "error", "message": f"Notion API error: {e.code}"}
        except Exception as e:
            logger.error(f"Unexpected error creating Notion note for user {user_id}: {e}", exc_info=True)
            return {"status": "error", "message": "An unexpected error occurred while creating the Notion note."}

    async def create_tracking_database(self, user_id: int, title: str, properties_schema: Dict[str, Dict], parent_page_id: str) -> Dict[str, Any]:
        """Creates a new database (table) within a parent page in Notion."""
        client = await self._get_client(user_id)
        if not client:
            return {"status": "error", "message": "Notion account not linked or token missing."}

        if not parent_page_id:
            return {"status": "error", "message": "A parent page ID is required to create a database."}

        # Basic validation of properties_schema (ensure 'title' is not included here)
        if "title" in properties_schema:
             return {"status": "error", "message": "Do not include 'title' in the properties schema; it's handled separately."}
        if not properties_schema:
             return {"status": "error", "message": "Please define at least one property (column) for the table."}


        try:
            logger.info(f"Creating Notion database '{title}' for user {user_id} under parent {parent_page_id}")
            db_data = {
                "parent": {"page_id": parent_page_id, "type": "page_id"},
                "title": [{"type": "text", "text": {"content": title}}],
                "properties": properties_schema # Schema defined by LLM/user
            }
            response = await client.databases.create(**db_data)
            db_url = response.get("url", "")
            db_id = response.get("id")
            logger.info(f"Successfully created Notion database for user {user_id}. URL: {db_url}")
            return {"status": "success", "message": f"Table (database) '{title}' created in Notion.", "database_id": db_id, "database_url": db_url}

        except APIResponseError as e:
            logger.error(f"Notion API error creating database for user {user_id}: {e}")
            # Add specific error handling based on e.code if needed
            return {"status": "error", "message": f"Notion API error creating table: {e.code}"}
        except Exception as e:
            logger.error(f"Unexpected error creating Notion database for user {user_id}: {e}", exc_info=True)
            return {"status": "error", "message": "An unexpected error occurred while creating the Notion table."}


    async def add_entry_to_database(self, user_id: int, database_id: str, entry_data: Dict[str, Any]) -> Dict[str, Any]:
        """Adds a new page (row) to a specific Notion database."""
        client = await self._get_client(user_id)
        if not client:
            return {"status": "error", "message": "Notion account not linked or token missing."}

        if not database_id:
            return {"status": "error", "message": "Database ID is required to add an entry."}
        if not entry_data:
            return {"status": "error", "message": "No data provided for the new entry."}

        # --- Construct Notion Properties ---
        # The entry_data needs to be mapped to the Notion property format.
        # Example: If entry_data is {"Name": "Task 1", "Status": "To Do", "Due Date": "2024-12-31"}
        # This needs to become Notion API properties, e.g.:
        # properties = {
        #    "Name": title_prop("Task 1"), # Assuming "Name" is the Title property
        #    "Status": {"select": {"name": "To Do"}}, # Assuming "Status" is Select
        #    "Due Date": date_prop("2024-12-31") # Assuming "Due Date" is Date
        # }
        # This mapping requires knowing the target database's schema.
        # For now, we'll assume the LLM provides entry_data keys matching the property names
        # and we create simple 'rich_text' properties for non-title keys.
        # A more robust solution would fetch the DB schema first.

        notion_properties = {}
        title_key = None
        # Attempt to find the 'title' property key (often 'Name' or 'Title')
        # This is brittle; ideally, fetch the schema first.
        potential_title_keys = [k for k in entry_data.keys() if k.lower() in ['name', 'title', 'task']]
        if potential_title_keys:
            title_key = potential_title_keys[0]
            notion_properties[title_key] = title_prop(str(entry_data[title_key]))
        else:
             return {"status": "error", "message": "Could not identify the title property for the entry."} # Or make first key the title

        for key, value in entry_data.items():
            if key == title_key:
                continue
            # Simple conversion - assumes rich text. Needs improvement for date, select etc.
            # TODO: Enhance property conversion based on target DB schema or LLM hints
            notion_properties[key] = rich_text_prop(str(value))

        try:
            logger.info(f"Adding entry to Notion database {database_id} for user {user_id}")
            page_data = {
                "parent": {"database_id": database_id},
                "properties": notion_properties
            }
            response = await client.pages.create(**page_data)
            page_url = response.get("url", "")
            logger.info(f"Successfully added entry to database {database_id} for user {user_id}. URL: {page_url}")
            return {"status": "success", "message": "Entry added to the Notion table.", "page_url": page_url}

        except APIResponseError as e:
            logger.error(f"Notion API error adding entry to database {database_id} for user {user_id}: {e}")
            # Add specific error handling based on e.code
            if e.code == APIErrorCode.ObjectNotFound:
                 return {"status": "error", "message": f"Could not find the database ({database_id}) in Notion."}
            elif e.code == APIErrorCode.ValidationError:
                 return {"status": "error", "message": f"Invalid data for the table schema: {e.body.get('message', '')}"}
            else:
                 return {"status": "error", "message": f"Notion API error adding entry: {e.code}"}
        except Exception as e:
            logger.error(f"Unexpected error adding Notion entry for user {user_id}: {e}", exc_info=True)
            return {"status": "error", "message": "An unexpected error occurred while adding the Notion entry."}

    # --- Add other methods as needed ---
    # - find_database_by_title
    # - get_database_schema
    # - query_database
    # - update_page_properties (e.g., to set reminders on date properties)