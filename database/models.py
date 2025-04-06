# models.py

from datetime import datetime
from enum import Enum
from typing import List, Optional

# <<-- Add Text import if not already present -->>
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Enum as SQLEnum, Text
# <<-- End Add Text import -->>
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# Import the Base from the new async init
# <<-- Make sure this import works for your project structure -->>
from . import Base # Assuming Base is defined in __init__.py
#from database.base import Base # Common alternative structure
# <<-- End Base import adjustment -->>


class RepeatFrequency(str, Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    # Assuming phone_number stores Telegram ID as string
    phone_number = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active = Column(DateTime(timezone=True), onupdate=func.now())

    email = Column(String, nullable=True) # Added email field if missing before
    name = Column(String, nullable=True) # Added name field if missing before

    # << --- START Notion Integration --- >>
    # Store Notion OAuth access token
    notion_access_token = Column(Text, nullable=True)
    # Store Notion Bot ID associated with the token
    notion_bot_id = Column(String, nullable=True)
    # Store Notion Workspace Name (optional, for info)
    notion_workspace_name = Column(String, nullable=True)
    duplicated_template_id = Column(String, nullable=True) # <-- ADD THIS FIELD
        # --- NEW FIELDS for Notion Dashboard ---
    notion_dashboard_page_id = Column(String, nullable=True, index=True) # ID of the "MyPai Dashboard" page
    notion_reminders_db_id = Column(String, nullable=True)
    notion_notes_db_id = Column(String, nullable=True)
    notion_events_db_id = Column(String, nullable=True)
    notion_setup_complete = Column(Boolean, default=False) # Flag to prevent rerunning setup
    # --- END NEW FIELDS ---

    # << --- END Notion Integration --- >>

    # Relationships
    reminders = relationship("Reminder", back_populates="user", cascade="all, delete-orphan")
    calendar_events = relationship("CalendarEvent", back_populates="user", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="user", cascade="all, delete-orphan")
    # << -- Add relationship to Session if it wasn't linked before -->>
    session = relationship("Session", back_populates="user", uselist=False, cascade="all, delete-orphan")
    # << -- End Session relationship -- >>


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False) # Add nullable=False
    message = Column(String, nullable=False)
    scheduled_time = Column(DateTime, nullable=False)
    is_recurring = Column(Boolean, default=False)
    repeat_frequency = Column(SQLEnum(RepeatFrequency), default=RepeatFrequency.NONE)
    repeat_interval = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="reminders")


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False) # Add nullable=False
    title = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)
    location = Column(String)
    participants = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="calendar_events")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False) # Add unique=True, nullable=False
    conversation_history = Column(Text, default='[]') # Add default
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # << -- Add relationship back to User -- >>
    user = relationship("User", back_populates="session")
    # << -- End User relationship -- >>


class NoteType(Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio" 
    VIDEO = "video"
    MIXED = "mixed"

class Note(Base):
    """Model for user notes."""
    __tablename__ = "notes"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=True)
    note_type = Column(SQLEnum(NoteType), default=NoteType.TEXT)
    tags = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    notion_url = Column(String(255), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="notes")
    media_attachments = relationship("MediaAttachment", back_populates="note", cascade="all, delete-orphan")

class MediaAttachment(Base):
    """Model for media attachments to notes."""
    __tablename__ = "media_attachments"
    
    id = Column(Integer, primary_key=True, index=True)
    note_id = Column(Integer, ForeignKey("notes.id", ondelete="CASCADE"))
    media_type = Column(String(50), nullable=False)  # MIME type
    filepath = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    note = relationship("Note", back_populates="media_attachments")

# Add relationship to User model
# This would go in the User class definition:
# notes = relationship("Note", back_populates="user", cascade="all, delete-orphan")