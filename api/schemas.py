from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime


class WhatsAppWebhookPayload(BaseModel):
    """Schema for incoming WhatsApp webhook payload"""
    object: str
    entry: List[Dict[str, Any]]


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