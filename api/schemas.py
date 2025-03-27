from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
#changes
from typing import List
#changes

class TelegramWebhookPayload(BaseModel):
    """Schema for incoming Telegram webhook payload"""
    update_id: int
    message: Optional[Dict[str, Any]] = None
    callback_query: Optional[Dict[str, Any]] = None
    #changes
    photo: Optional[List[Dict[str, Any]]] = None
    #changes
    
    class Config:
        schema_extra = {
            "example": {
                "update_id": 12345678,
                "message": {
                    "message_id": 1234,
                    "from": {
                        "id": 123456789,
                        "first_name": "John",
                        "last_name": "Doe",
                        "username": "johndoe"
                    },
                    "chat": {
                        "id": 123456789,
                        "first_name": "John",
                        "last_name": "Doe",
                        "username": "johndoe",
                        "type": "private"
                    },
                    "date": 1609459200,
                    "text": "Hello, world!"
                }
            }
        }


class UserMessage(BaseModel):
    """Schema for a processed user message"""
    sender_id: str
    message_text: str
    timestamp: int


class BotResponse(BaseModel):
    """Schema for bot response"""
    message: str
    function_calls: List[Dict[str, Any]] = []


class ReminderCreate(BaseModel):
    """Schema for creating a reminder"""
    message: str
    time: str  # HH:MM format
    date: str  # YYYY-MM-DD format
    repeat: Optional[str] = None


class RecurringReminderCreate(BaseModel):
    """Schema for creating a recurring reminder"""
    message: str
    interval: str  # e.g., "every 2 hours"
    start_time: Optional[str] = None  # HH:MM format


class CalendarEventCreate(BaseModel):
    """Schema for creating a calendar event"""
    title: str
    date: str  # YYYY-MM-DD format
    time: str  # HH:MM format
    location: Optional[str] = None
    participants: Optional[List[str]] = None


class DateRangeQuery(BaseModel):
    """Schema for querying within a date range"""
    date_range: str  # e.g., "next 7 days"


class EventCancel(BaseModel):
    """Schema for cancelling an event"""
    event_title: str