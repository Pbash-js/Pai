from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from database import crud
from llm.processor import LLMProcessor

class CalendarService:
    """Service for managing user calendar events."""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm_processor = LLMProcessor()
    
    def schedule_event(self, user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Schedule a new calendar event for the user.
        
        Args:
            user_id: User ID
            data: Dictionary with event details (title, date, time, location, participants)
            
        Returns:
            Dict with status and event details
        """
        title = data["title"]
        date_str = data["date"]
        time_str = data["time"]
        location = data.get("location", "")
        participants = data.get("participants", [])
        
        # Parse date and time
        try:
            start_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            # Set default end time to 1 hour after start time
            end_time = start_time + timedelta(hours=1)
        except ValueError:
            return {"status": "error", "message": "Invalid date or time format"}
        
        # Create calendar event
        event = crud.create_calendar_event(
            db=self.db,
            user_id=user_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            location=location,
            participants=",".join(participants) if participants else ""
        )
        
        return {
            "status": "success",
            "event_id": event.id,
            "title": title,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "location": location,
            "participants": participants
        }
    
    def get_upcoming_events(self, user_id: int, date_range: str) -> List[Dict[str, Any]]:
        """
        Get upcoming calendar events for the user.
        
        Args:
            user_id: User ID
            date_range: String describing the date range (e.g., "next 7 days")
            
        Returns:
            List of events as dictionaries
        """
        days = self.llm_processor.parse_date_range(date_range)
        events = crud.get_upcoming_events(db=self.db, user_id=user_id, days=days)
        
        result = []
        for event in events:
            participants = event.participants.split(",") if event.participants else []
            
            result.append({
                "id": event.id,
                "title": event.title,
                "start_time": event.start_time.isoformat(),
                "end_time": event.end_time.isoformat() if event.end_time else None,
                "location": event.location or "",
                "participants": participants
            })
        
        return result
    
    def cancel_event(self, user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cancel a calendar event by title.
        
        Args:
            user_id: User ID
            data: Dictionary with event title
            
        Returns:
            Dict with status and message
        """
        event_title = data["event_title"]
        
        # Find the event
        event = crud.find_calendar_event_by_title(db=self.db, user_id=user_id, title=event_title)
        if not event:
            return {
                "status": "error",
                "message": f"Event '{event_title}' not found."
            }
        
        # Cancel the event
        success = crud.delete_calendar_event(db=self.db, event_id=event.id)
        
        if success:
            return {
                "status": "success",
                "message": f"Event '{event_title}' has been canceled."
            }
        else:
            return {
                "status": "error",
                "message": f"Failed to cancel event '{event_title}'."
            }