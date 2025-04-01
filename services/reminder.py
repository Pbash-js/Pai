from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from database import crud
from database.models import RepeatFrequency
from llm.processor import LLMProcessor

#changes
import logging
logger = logging.getLogger(__name__)
#changes

class ReminderService:
    """Service for managing user reminders."""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm_processor = LLMProcessor()
    
    def set_reminder(self, user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Set a new reminder for the user.
        
        Args:
            user_id: User ID
            data: Dictionary with reminder details (message, time, date, repeat)
            
        Returns:
            Dict with status and reminder details
        """
        message = data["message"]
        time_str = data["time"]
        date_str = data["date"]
        repeat = data.get("repeat", "none")
        
        # Parse date and time
        try:
            scheduled_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            return {"status": "error", "message": "Invalid date or time format"}
        
        # Determine if recurring
        is_recurring = repeat.lower() != "none"
        repeat_frequency = RepeatFrequency.NONE
        repeat_interval = 0
        
        if is_recurring:
            if repeat.lower() == "daily":
                repeat_frequency = RepeatFrequency.DAILY
            elif repeat.lower() == "weekly":
                repeat_frequency = RepeatFrequency.WEEKLY
            elif repeat.lower() == "monthly":
                repeat_frequency = RepeatFrequency.MONTHLY
            else:
                # Custom interval
                interval_mins, freq_type = self.llm_processor.parse_time_interval(repeat)
                repeat_frequency = RepeatFrequency(freq_type)
                repeat_interval = interval_mins
        
        # Create reminder
        logger.info("Setting reminder!!!")
        reminder = crud.create_reminder(
            db=self.db,
            user_id=user_id,
            message=message,
            scheduled_time=scheduled_time,
            is_recurring=is_recurring,
            repeat_frequency=repeat_frequency,
            repeat_interval=repeat_interval
        )
        
        return {
            "status": "success",
            "reminder_id": reminder.id,
            "message": message,
            "scheduled_time": scheduled_time.isoformat(),
            "is_recurring": is_recurring,
            "repeat_frequency": repeat_frequency.value
        }
    
    def set_recurring_reminder(self, user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Set a recurring reminder for the user.
        
        Args:
            user_id: User ID
            data: Dictionary with reminder details (message, interval, start_time)
            
        Returns:
            Dict with status and reminder details
        """
        message = data["message"]
        interval = data["interval"]
        start_time = data.get("start_time")
        
        # Parse interval
        interval_mins, freq_type = self.llm_processor.parse_time_interval(interval)
        
        # Parse start time if provided
        scheduled_time = datetime.utcnow()
        if start_time:
            try:
                # If only time is provided, use today's date
                time_obj = datetime.strptime(start_time, "%H:%M").time()
                scheduled_time = datetime.combine(datetime.utcnow().date(), time_obj)
                
                # If the time has already passed today, schedule for tomorrow
                if scheduled_time < datetime.utcnow():
                    scheduled_time += timedelta(days=1)
            except ValueError:
                pass
        
        # Create reminder
        reminder = crud.create_reminder(
            db=self.db,
            user_id=user_id,
            message=message,
            scheduled_time=scheduled_time,
            is_recurring=True,
            repeat_frequency=RepeatFrequency(freq_type),
            repeat_interval=interval_mins
        )
        
        return {
            "status": "success",
            "reminder_id": reminder.id,
            "message": message,
            "scheduled_time": scheduled_time.isoformat(),
            "is_recurring": True,
            "repeat_frequency": freq_type,
            "interval_minutes": interval_mins
        }
    
    def get_upcoming_reminders(self, user_id: int, date_range: str) -> List[Dict[str, Any]]:
        """
        Get upcoming reminders for the user.
        
        Args:
            user_id: User ID
            date_range: String describing the date range (e.g., "next 7 days")
            
        Returns:
            List of reminders as dictionaries
        """
        if not date_range:
            days = 3
        else:
            days = self.llm_processor.parse_date_range(date_range)
        reminders = crud.get_upcoming_reminders(db=self.db, user_id=user_id, days=days)
        
        result = []
        for reminder in reminders:
            result.append({
                "id": reminder.id,
                "message": reminder.message,
                "scheduled_time": reminder.scheduled_time.isoformat(),
                "is_recurring": reminder.is_recurring,
                "repeat_frequency": reminder.repeat_frequency.value if reminder.is_recurring else "none"
            })
        logger.info("Getting reminder!!!")
        
        return result
    
    def process_due_reminders(self) -> List[Dict[str, Any]]:
        """
        Process all due reminders and return notifications to be sent.
        
        Returns:
            List of notifications with user_id, phone_number, and message
        """
        # Get all due reminders
        due_reminders = crud.get_due_reminders(db=self.db)
        
        notifications = []
        for reminder in due_reminders:
            # Get user
            user = crud.get_user_by_id(self.db, reminder.user_id)
            if not user:
                continue
            
            # Create notification
            notifications.append({
                "user_id": user.id,
                "phone_number": user.phone_number,
                "message": f"REMINDER: {reminder.message}"
            })
            
            # Handle recurring reminders
            if reminder.is_recurring:
                # Calculate next occurrence
                if reminder.repeat_frequency == RepeatFrequency.DAILY:
                    next_time = reminder.scheduled_time + timedelta(days=1)
                elif reminder.repeat_frequency == RepeatFrequency.WEEKLY:
                    next_time = reminder.scheduled_time + timedelta(days=7)
                elif reminder.repeat_frequency == RepeatFrequency.MONTHLY:
                    # Approximately add a month (30 days)
                    next_time = reminder.scheduled_time + timedelta(days=30)
                else:  # Custom interval
                    next_time = reminder.scheduled_time + timedelta(minutes=reminder.repeat_interval)
                
                # Update reminder with new time
                crud.update_reminder(
                    db=self.db,
                    reminder_id=reminder.id,
                    scheduled_time=next_time
                )
            else:
                # Mark one-time reminder as inactive
                crud.update_reminder(
                    db=self.db,
                    reminder_id=reminder.id,
                    is_active=False
                )
        
        return notifications