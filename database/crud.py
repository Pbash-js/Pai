# crud.py

import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
# <<-- Add update import -->>
from sqlalchemy import update, or_, select # Ensure select is imported if needed elsewhere
# <<-- End add update import -->>
from sqlalchemy.future import select

# <<-- Adjust import path if necessary -->>
from .models import User, Reminder, CalendarEvent, Session, RepeatFrequency,Note, MediaAttachment, NoteType
import logging
# <<-- End import path adjustment -->>

logger = logging.getLogger(__name__)

# User operations
async def get_user_by_phone(db: AsyncSession, phone_number: str) -> Optional[User]:
    """Gets user by phone_number (assuming it stores Telegram ID as string)."""
    result = await db.execute(select(User).filter(User.phone_number == phone_number))
    return result.scalars().first()

async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    """Gets user by internal primary key ID."""
    result = await db.execute(select(User).filter(User.id == user_id))
    return result.scalars().first()

async def create_user(db: AsyncSession, phone_number: str) -> User:
    """Creates a new user with phone_number (Telegram ID string)."""
    user = User(phone_number=phone_number)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def update_user_google_info(db: AsyncSession, telegram_id: int, google_info: dict) -> Optional[User]:
    """Update user with Google account information."""
    # Find user by Telegram ID (stored as string in phone_number)
    result = await db.execute(select(User).filter(User.phone_number == str(telegram_id)))
    user = result.scalars().first()
    if user:
        user.google_id = google_info.get("google_id")
        user.email = google_info.get("email")
        user.name = google_info.get("name")
        # IMPORTANT: You should store Google OAuth tokens (access, refresh, expiry)
        # here as well if you plan to call Google APIs like Calendar/Tasks later.
        # Example fields (add these to models.py too):
        # user.google_access_token = google_info.get("access_token")
        # user.google_refresh_token = google_info.get("refresh_token")
        # user.google_token_expires_at = google_info.get("expires_at")
        await db.commit()
        await db.refresh(user) # Refresh to get updated data
        return user
    return None

# << --- START Notion Integration --- >>
async def update_user_notion_info(db: AsyncSession, telegram_id: int, notion_data: dict) -> Optional[User]:
    """Update user with Notion OAuth information."""
    # Find user by Telegram ID (stored as string in phone_number)
    result = await db.execute(select(User).filter(User.phone_number == str(telegram_id)))
    user = result.scalars().first()
    if user:
        user.notion_access_token = notion_data.get("access_token")
        user.notion_bot_id = notion_data.get("bot_id")
        user.notion_workspace_name = notion_data.get("workspace_name")
        user.duplicated_template_id = notion_data.get("duplicated_template_id")
        await db.commit()
        await db.refresh(user)
        return user
    return None

async def get_user_notion_token(db: AsyncSession, user_id: int) -> Optional[str]:
    """Retrieve stored Notion access token for a user by their internal ID."""
    result = await db.execute(
        select(User.notion_access_token).filter(User.id == user_id)
    )
    token = result.scalars().first()
    return token
# << --- END Notion Integration --- >>


async def get_or_create_user(db: AsyncSession, sender_id: int) -> User:
    """Gets or creates a user based on Telegram sender ID."""
    telegram_id_str = str(sender_id) # Store Telegram ID as string
    user = await get_user_by_phone(db, telegram_id_str)
    if not user:
        user = await create_user(db, telegram_id_str)

    # Update last active timestamp
    user.last_active = datetime.utcnow()
    await db.commit()
    await db.refresh(user)
    return user

# # This function seems redundant if update_user_google_info handles it
# async def user_set_google_id(db: AsyncSession, user_id: int, google_id: str) -> Optional[User]:
#     result = await db.execute(select(User).filter(User.id == user_id))
#     user = result.scalars().first()
#     if not user:
#         return None
#     user.google_id = google_id
#     await db.commit()
#     await db.refresh(user)
#     return user

# --- Reminder operations ---
# (Keep existing reminder functions: create_reminder, get_user_reminders, etc.)
# Ensure these functions use await db.commit() and await db.refresh(obj) correctly
async def create_reminder(
    db: AsyncSession,
    user_id: int,
    message: str,
    scheduled_time: datetime,
    is_recurring: bool = False,
    repeat_frequency: RepeatFrequency = RepeatFrequency.NONE,
    repeat_interval: int = 0
) -> Reminder:
    reminder = Reminder(
        user_id=user_id,
        message=message,
        scheduled_time=scheduled_time,
        is_recurring=is_recurring,
        repeat_frequency=repeat_frequency,
        repeat_interval=repeat_interval
    )
    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)
    return reminder

async def get_upcoming_reminders(db: AsyncSession, user_id: int, days: int = 7) -> List[Reminder]:
    now = datetime.utcnow()
    end_date = now + timedelta(days=days)
    query = select(Reminder).filter(
        Reminder.user_id == user_id,
        Reminder.scheduled_time >= now,
        Reminder.scheduled_time <= end_date,
        Reminder.is_active == True # Use == True for clarity
    ).order_by(Reminder.scheduled_time)
    result = await db.execute(query)
    return result.scalars().all()

async def get_due_reminders(db: AsyncSession) -> List[Reminder]:
    now = datetime.utcnow()
    query = select(Reminder).filter(
        Reminder.scheduled_time <= now,
        Reminder.is_active == True
    )
    result = await db.execute(query)
    return result.scalars().all()

async def update_reminder(db: AsyncSession, reminder_id: int, **kwargs) -> Optional[Reminder]:
    # Use SQLAlchemy 2.0 style update for potential efficiency
    stmt = update(Reminder).where(Reminder.id == reminder_id).values(**kwargs).returning(Reminder)
    result = await db.execute(stmt)
    updated_reminder = result.scalar_one_or_none()
    if updated_reminder:
        await db.commit()
        # Refreshing might not be needed as returning() gets the updated row
        # await db.refresh(updated_reminder)
        return updated_reminder
    # Fallback or handle case where reminder doesn't exist
    await db.rollback() # Rollback if update failed
    return None


async def delete_reminder(db: AsyncSession, reminder_id: int) -> bool:
    # Soft delete by setting is_active to False
    updated_reminder = await update_reminder(db, reminder_id, is_active=False)
    return updated_reminder is not None


# --- Calendar event operations ---
# (Keep existing calendar functions: create_calendar_event, get_upcoming_events, etc.)
# Ensure async commits/refreshes
async def create_calendar_event(
    db: AsyncSession,
    user_id: int,
    title: str,
    start_time: datetime,
    end_time: Optional[datetime] = None,
    location: Optional[str] = None,
    participants: Optional[str] = None # Stored as comma-separated string
) -> CalendarEvent:
    event = CalendarEvent(
        user_id=user_id,
        title=title,
        start_time=start_time,
        end_time=end_time,
        location=location,
        participants=participants
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event

async def get_upcoming_events(db: AsyncSession, user_id: int, days: int = 7) -> List[CalendarEvent]:
    now = datetime.utcnow()
    end_date = now + timedelta(days=days)
    query = select(CalendarEvent).filter(
        CalendarEvent.user_id == user_id,
        CalendarEvent.start_time >= now,
        CalendarEvent.start_time <= end_date,
        CalendarEvent.is_active == True
    ).order_by(CalendarEvent.start_time)
    result = await db.execute(query)
    return result.scalars().all()

# update_calendar_event can be similar to update_reminder using update() stmt
async def update_calendar_event(db: AsyncSession, event_id: int, **kwargs) -> Optional[CalendarEvent]:
    stmt = update(CalendarEvent).where(CalendarEvent.id == event_id).values(**kwargs).returning(CalendarEvent)
    result = await db.execute(stmt)
    updated_event = result.scalar_one_or_none()
    if updated_event:
        await db.commit()
        return updated_event
    await db.rollback()
    return None

async def delete_calendar_event(db: AsyncSession, event_id: int) -> bool:
    # Soft delete
    updated_event = await update_calendar_event(db, event_id, is_active=False)
    return updated_event is not None

async def find_calendar_event_by_title(db: AsyncSession, user_id: int, title: str) -> Optional[CalendarEvent]:
    # Use ilike for case-insensitive search
    query = select(CalendarEvent).filter(
        CalendarEvent.user_id == user_id,
        CalendarEvent.title.ilike(f"%{title}%"), # Case-insensitive containment
        CalendarEvent.is_active == True
    ).order_by(CalendarEvent.start_time) # Order to get the soonest if multiple match
    result = await db.execute(query)
    return result.scalars().first() # Return the first match


# --- Session operations ---
async def get_or_create_session(db: AsyncSession, user_id: int) -> Session:
    result = await db.execute(select(Session).filter(Session.user_id == user_id))
    session = result.scalars().first()
    if not session:
        session = Session(user_id=user_id, conversation_history=json.dumps([]))
        db.add(session)
        await db.commit()
        await db.refresh(session)
    return session


async def update_session_history(db: AsyncSession, user_id: int, new_message: Dict[str, Any]) -> Session:
    session = await get_or_create_session(db, user_id)

    try:
        history = json.loads(session.conversation_history or '[]') # Handle None or empty string
    except json.JSONDecodeError:
        history = [] # Reset if invalid JSON

    history.append(new_message)

    # Keep only the last N messages (e.g., 20 for more context)
    max_history = 20
    if len(history) > max_history:
        history = history[-max_history:]

    # Update session using update statement
    stmt = update(Session).where(Session.user_id == user_id).values(
        conversation_history=json.dumps(history),
        updated_at=datetime.utcnow() # Use UTC now
    ).returning(Session) # Return the updated session object

    result = await db.execute(stmt)
    updated_session = result.scalar_one() # Use scalar_one since we expect one row
    await db.commit()
    # await db.refresh(updated_session) # Not needed with returning()

    return updated_session


async def get_session_history(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
    session = await get_or_create_session(db, user_id)
    try:
        return json.loads(session.conversation_history or '[]')
    except json.JSONDecodeError:
        return [] # Return empty list if invalid JSON
    
async def update_user_notion_dashboard_info(
    db: AsyncSession,
    user_id: int, # Use internal user ID
    dashboard_id: Optional[str],
    reminders_db_id: Optional[str],
    notes_db_id: Optional[str],
    events_db_id: Optional[str],
    setup_complete: bool
) -> Optional[User]:
    """Updates the Notion dashboard/DB IDs and setup status for a user by internal ID."""
    try:
        current_time = datetime.now().astimezone(tz=None) # Get current UTC time
        # Define values WITHOUT updated_at first
        values_to_set = {
            "notion_dashboard_page_id": dashboard_id,
            "notion_reminders_db_id": reminders_db_id,
            "notion_notes_db_id": notes_db_id,
            "notion_events_db_id": events_db_id,
            "notion_setup_complete": setup_complete,
            # "updated_at": current_time # Use calculated time
        }

        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(**values_to_set) # Pass dict including timestamp
            .returning(User)
        )
        result = await db.execute(stmt)
        await db.commit()
        updated_user = result.scalar_one_or_none()
        if updated_user:
            logger.info(f"Updated Notion dashboard info for user_id {user_id}. Setup complete: {setup_complete}")
            return updated_user
        else:
            logger.warning(f"Attempted to update Notion dashboard info, but user_id {user_id} not found.")
            return None
    except Exception as e:
        await db.rollback()
        # Log the specific error type and message
        logger.error(f"Database error ({type(e).__name__}) updating Notion dashboard info for user_id {user_id}: {e}", exc_info=True)
        return None
    

# Make sure get_user uses internal ID if needed by update_user_notion_dashboard_info
async def get_user(db: AsyncSession, user_id: int) -> Optional[User]:
    """Gets a user by their internal database ID."""
    result = await db.execute(select(User).filter(User.id == user_id))
    return result.scalar_one_or_none()



def create_note(db: Session, user_id: int, title: str, content: str, 
                note_type: NoteType = NoteType.TEXT, tags: str = None,
                notion_url: str = None) -> Note:
    """
    Create a new note.
    
    Args:
        db: Database session
        user_id: User ID
        title: Note title
        content: Note content
        note_type: Type of note
        tags: Comma-separated tags
        notion_url: URL to Notion page if synced
        
    Returns:
        Created note
    """
    note = Note(
        user_id=user_id,
        title=title,
        content=content,
        note_type=note_type,
        tags=tags,
        notion_url=notion_url
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note

def get_note_by_id(db: Session, note_id: int) -> Optional[Note]:
    """
    Get a note by ID.
    
    Args:
        db: Database session
        note_id: Note ID
        
    Returns:
        Note if found, None otherwise
    """
    return db.query(Note).filter(Note.id == note_id).first()

def get_notes(db: Session, user_id: int, tags: List[str] = None, 
              search_text: str = None, date_from: str = None, 
              date_to: str = None, note_type: str = None,
              limit: int = 100) -> List[Note]:
    """
    Get notes with optional filtering.
    
    Args:
        db: Database session
        user_id: User ID
        tags: List of tags to filter by
        search_text: Text to search in title/content
        date_from: Start date (ISO format)
        date_to: End date (ISO format)
        note_type: Type of note to filter by
        limit: Maximum number of notes to return
        
    Returns:
        List of notes
    """
    query = db.query(Note).filter(Note.user_id == user_id)
    
    # Apply filters
    if tags:
        # Filter for notes that have at least one of the requested tags
        tag_filters = []
        for tag in tags:
            tag_filters.append(Note.tags.like(f"%{tag}%"))
        query = query.filter(or_(*tag_filters))
    
    if search_text:
        query = query.filter(
            or_(
                Note.title.ilike(f"%{search_text}%"),
                Note.content.ilike(f"%{search_text}%")
            )
        )
    
    if date_from:
        try:
            from_date = datetime.fromisoformat(date_from)
            query = query.filter(Note.created_at >= from_date)
        except (ValueError, TypeError):
            pass
    
    if date_to:
        try:
            to_date = datetime.fromisoformat(date_to)
            query = query.filter(Note.created_at <= to_date)
        except (ValueError, TypeError):
            pass
    
    if note_type:
        try:
            note_type_enum = NoteType(note_type)
            query = query.filter(Note.note_type == note_type_enum)
        except (ValueError, TypeError):
            pass
    
    return query.order_by(Note.created_at.desc()).limit(limit).all()

def update_note(db: Session, note_id: int, title: str = None, 
                content: str = None, tags: str = None) -> Optional[Note]:
    """
    Update a note.
    
    Args:
        db: Database session
        note_id: Note ID
        title: New title (optional)
        content: New content (optional)
        tags: New tags (optional)
        
    Returns:
        Updated note if found, None otherwise
    """
    note = get_note_by_id(db, note_id)
    if not note:
        return None
    
    if title is not None:
        note.title = title
    if content is not None:
        note.content = content
    if tags is not None:
        note.tags = tags
    
    note.updated_at = datetime.now()
    db.commit()
    db.refresh(note)
    return note

def update_note_notion_url(db: Session, note_id: int, notion_url: str) -> Optional[Note]:
    """
    Update a note's Notion URL.
    
    Args:
        db: Database session
        note_id: Note ID
        notion_url: Notion page URL
        
    Returns:
        Updated note if found, None otherwise
    """
    note = get_note_by_id(db, note_id)
    if not note:
        return None
    
    note.notion_url = notion_url
    note.updated_at = datetime.now()
    db.commit()
    db.refresh(note)
    return note

def delete_note(db: Session, note_id: int) -> bool:
    """
    Delete a note.
    
    Args:
        db: Database session
        note_id: Note ID
        
    Returns:
        True if deleted, False otherwise
    """
    note = get_note_by_id(db, note_id)
    if not note:
        return False
    
    db.delete(note)
    db.commit()
    return True

# --- Media Attachment CRUD operations ---

def create_media_attachment(db: Session, note_id: int, media_type: str, 
                           filepath: str) -> MediaAttachment:
    """
    Create a new media attachment.
    
    Args:
        db: Database session
        note_id: Note ID
        media_type: MIME type of media
        filepath: Path to media file
        
    Returns:
        Created media attachment
    """
    attachment = MediaAttachment(
        note_id=note_id,
        media_type=media_type,
        filepath=filepath
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment

def get_media_attachments(db: Session, note_id: int) -> List[MediaAttachment]:
    """
    Get all media attachments for a note.
    
    Args:
        db: Database session
        note_id: Note ID
        
    Returns:
        List of media attachments
    """
    return db.query(MediaAttachment).filter(MediaAttachment.note_id == note_id).all()

def delete_media_attachment(db: Session, attachment_id: int) -> bool:
    """
    Delete a media attachment.
    
    Args:
        db: Database session
        attachment_id: Attachment ID
        
    Returns:
        True if deleted, False otherwise
    """
    attachment = db.query(MediaAttachment).filter(MediaAttachment.id == attachment_id).first()
    if not attachment:
        return False
    
    db.delete(attachment)
    db.commit()
    return True